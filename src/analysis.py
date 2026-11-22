import http.client
import json
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import current_app

from src.checker import check_resource
from src.checker.network import download_pdf
from src.database.db import (
    connection,
    decode_resource,
    get_paper,
    now,
    save_analysis,
)
from src.paper.extractor import extract_paper
from src.parser import links_from_text
from src.scoring import calculate_score


_executor = ThreadPoolExecutor(max_workers=2)
MAX_LINKS = 60

LIMITATIONS = [
    "HTTP availability does not establish reproducibility.",
    "Resource categories are inferred and may need correction.",
    "Detected links may belong to cited papers.",
    "Scanned PDFs require OCR, which is not included.",
    "Network errors and access restrictions create uncertainty.",
    f"At most {MAX_LINKS} links are checked per report.",
]





















def latest_job(paper_id):
    with connection() as db:
        row = db.execute(
            """
            SELECT * FROM jobs
            WHERE paper_id = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (paper_id,),
        ).fetchone()

    return dict(row) if row else None


def _set_stage(job_id, stage):
    with connection() as db:
        db.execute(
            """
            UPDATE jobs
            SET status = 'running', stage = ?
            WHERE id = ?
            """,
            (stage, job_id),
        )


def _fail_job(job_id, paper_id):
    with connection() as db:
        db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                stage = 'Analysis failed',
                error = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (
                "Analysis failed. Check the server terminal for details.",
                now(),
                job_id,
            ),
        )
        db.execute(
            """
            UPDATE papers
            SET analysis_status = 'failed'
            WHERE id = ?
            """,
            (paper_id,),
        )

def recover_interrupted_jobs():
    with connection() as db:
        db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                stage = 'Analysis interrupted',
                error = 'Server restarted. Run analysis again.',
                finished_at = ?
            WHERE status IN ('queued', 'running')
            """,
            (now(),),
        )
        db.execute(
            """
            UPDATE papers
            SET analysis_status = 'failed'
            WHERE analysis_status = 'analyzing'
            """
        )


def start_analysis(paper_id, applicable):
    selected = calculate_score([], applicable)["applicable"]
    app = current_app._get_current_object()
    job_id = uuid.uuid4().hex

    with connection() as db:
        db.execute("BEGIN IMMEDIATE")

        paper = db.execute(
            "SELECT analysis_status FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()

        if paper is None:
            raise ValueError("Paper not found.")

        if paper["analysis_status"] == "analyzing":
            raise ValueError("This paper is already being analyzed.")

        db.execute(
            """
            INSERT INTO jobs (
                id, paper_id, status, stage, created_at
            )
            VALUES (?, ?, 'queued', 'Waiting to start', ?)
            """,
            (job_id, paper_id, now()),
        )
        db.execute(
            """
            UPDATE papers
            SET analysis_status = 'analyzing'
            WHERE id = ?
            """,
            (paper_id,),
        )

    try:
        _executor.submit(
            _run_analysis, app, job_id, paper_id, selected
        )
    except Exception:
        _fail_job(job_id, paper_id)
        raise

    return job_id


def _extract(paper):
    max_pages = current_app.config["MAX_PDF_PAGES"]

    if paper["local_path"]:
        path = Path(paper["local_path"]).resolve()
        folder = Path(
            current_app.config["UPLOAD_FOLDER"]
        ).resolve()

        if not path.is_relative_to(folder):
            raise ValueError("PDF is outside the upload folder.")

        return extract_paper(path, max_pages=max_pages), "Full PDF"

    if paper["pdf_url"]:
        try:
            data = download_pdf(paper["pdf_url"])

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "paper.pdf"
                path.write_bytes(data)
                extracted = extract_paper(
                    path, max_pages=max_pages
                )

            return extracted, "Full PDF"

        except (
            OSError,
            ValueError,
            RuntimeError,
            http.client.HTTPException,
        ):
            current_app.logger.warning(
                "PDF retrieval failed for paper %s",
                paper["id"],
                exc_info=True,
            )

    return {
        "resources": [],
        "text": "",
        "pages": None,
        "warnings": [
            "Full PDF unavailable. Only abstract links were analyzed."
        ],
    }, "Abstract only"






