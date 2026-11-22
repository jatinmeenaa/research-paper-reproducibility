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


























