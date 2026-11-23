import csv
import hashlib
import http.client
import io
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf as fitz
from flask import (
    Response,abort,current_app,flash,
    jsonify,redirect,render_template,request,send_file,url_for,
)
from werkzeug.utils import secure_filename

from src.analysis import latest_job, rescore, start_analysis
from src.checker.network import download_pdf
from src.database.db import (
    RESOURCE_TYPES,
    connection,
    facets,
    get_paper,
    get_resources,
    library_stats,
    list_papers,
    save_paper,
)
from src.paper.discovery import discover
from src.parser import CATEGORIES


def paper_or_404(paper_id):
    paper = get_paper(paper_id)
    if not paper:
        abort(404)
    return paper


def paper_pdf_source(paper):
    if paper["local_path"]:
        path = Path(paper["local_path"]).resolve()
        folder = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            abort(404, description="The uploaded PDF is no longer available.")
        if path.stat().st_size > current_app.config["MAX_CONTENT_LENGTH"]:
            abort(413, description="The PDF exceeds the download size limit.")
        return path
    if not paper["pdf_url"]:
        abort(404, description="This paper has no PDF. Upload a PDF or provide a PDF URL.")
    try:
        return io.BytesIO(download_pdf(paper["pdf_url"]))
    except (OSError, ValueError, RuntimeError, http.client.HTTPException):
        current_app.logger.warning("Could not retrieve PDF for paper %s", paper["id"], exc_info=True)
        abort(502, description="The PDF could not be retrieved from its source. Please try again later.")


def paper_pdf_filename(paper):
    title = secure_filename(paper["title"])[:160] or f"paper-{paper['id']}"
    return title if title.lower().endswith(".pdf") else title + ".pdf"


def filters():
    result = {
        key: request.args.get(key, "").strip()
        for key in ("q", "source", "area", "year", "min_score", "sort", "analysis_status")
    }
    result["q"] = result["q"][:200]
    if result["sort"] not in ("score", "newest", "year"):
        result["sort"] = "score"
    for key, low, high in (("year", 1000, 9999), ("min_score", 0, 100)):
        if result[key]:
            try:
                value = int(result[key])
                if not low <= value <= high:
                    raise ValueError
            except ValueError:
                abort(400, description="Year or minimum score is invalid.")
    return result

def register_routes(app):

    @app.route("/", methods=["GET"])
    def home():
        return redirect(url_for("main.search", **request.args.to_dict()))

    @app.route("/library/stats", methods=["GET"])
    def library_statistics():
        """Return current counters for pages left open during background analysis."""
        return jsonify(library_stats())

    @app.route("/search", methods=["GET"])
    def search():
        query = request.args.get("q", "").strip()
        source = request.args.get("source", "arXiv")
        if source not in ("arXiv", "Semantic Scholar", "both") or len(query) > 200:
            abort(400, description="Choose a valid source and a query of up to 200 characters.")
        papers, errors = [], []
        if query:
            found, errors = discover(query, source)
            papers = [get_paper(save_paper(paper)) for paper in found]
        return render_template(
            "search.html", papers=papers, errors=errors, query=query, source=source
        )

    @app.route("/library", methods=["GET"])
    def library():
        selected = filters()
        return render_template(
            "library.html", papers=list_papers(selected), filters=selected, facets=facets()
        )

    @app.route("/papers/add", methods=["GET", "POST"])
    def add_paper():
        """Save user-entered metadata and an optional PDF without discovery API calls."""
        limits = {
            "title": 300,
            "authors": 2000,
            "year": 4,
            "area": 80,
            "paper_url": 2048,
            "pdf_url": 2048,
            "abstract": 20000,
        }
        values = {field: request.form.get(field, "").strip() for field in limits}
        errors = {}
        if request.method == "GET":
            return render_template("add_paper.html", values=values, errors=errors)
        for field, maximum in limits.items():
            if len(values[field]) > maximum:
                errors[field] = f"Use no more than {maximum} characters."
        if not values["title"]:
            errors["title"] = "Enter the paper title."
        year = None
        if values["year"]:
            if not re.fullmatch(r"[1-9][0-9]{3}", values["year"]):
                errors["year"] = "Enter a four-digit publication year."
            else:
                year = int(values["year"])
        for field in ("paper_url", "pdf_url"):
            value = values[field]
            if not value:
                continue
            try:
                parts = urlsplit(value)
                _ = parts.port
                if (
                    parts.scheme not in ("http", "https")
                    or not parts.hostname
                    or parts.username is not None
                    or parts.password is not None
                    or any(char.isspace() or ord(char) < 32 for char in value)
                ):
                    raise ValueError
            except ValueError:
                errors[field] = "Enter a complete HTTP or HTTPS URL without a username or password."
        file = request.files.get("pdf")
        data = None
        if not errors and file and file.filename:
            try:
                if not file.filename.lower().endswith(".pdf"):
                    raise ValueError("Choose a PDF file.")
                data = file.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
                if len(data) > current_app.config["MAX_CONTENT_LENGTH"]:
                    abort(413)
                if b"%PDF-" not in data[:1024]:
                    raise ValueError("The file is not a PDF.")
                with fitz.open(stream=data, filetype="pdf") as document:
                    if document.needs_pass:
                        raise ValueError("Password-protected PDFs are not supported.")
                    if (
                        not document.is_pdf
                        or not 1 <= len(document) <= current_app.config["MAX_PDF_PAGES"]
                    ):
                        raise ValueError("Choose a PDF with 1 to 300 pages.")
            except (ValueError, RuntimeError, fitz.FileDataError) as error:
                errors["pdf"] = "Could not read this PDF: " + str(error)[:250]
        if errors:
            return render_template("add_paper.html", values=values, errors=errors), 400
        paper = {
            "title": values["title"],
            "authors": [
                name.strip() for name in re.split(r"[;\r\n]+", values["authors"]) if name.strip()
            ],
            "year": year,
            "area": values["area"] or "Uncategorized",
            "paper_url": values["paper_url"] or None,
            "pdf_url": values["pdf_url"] or None,
            "abstract": values["abstract"],
            "source": "Manual",
        }
        path = None
        if data is not None:
            paper["upload_hash"] = hashlib.sha256(data).hexdigest()
            path = Path(current_app.config["UPLOAD_FOLDER"]) / (uuid.uuid4().hex + ".pdf")
            path.write_bytes(data)
            paper["local_path"] = str(path)
        try:
            paper_id = save_paper(paper)
            saved = get_paper(paper_id)
            if path and saved["local_path"] != str(path):
                with connection() as db:
                    attached = db.execute(
                        "UPDATE papers SET local_path=? WHERE id=? AND local_path IS NULL",
                        (str(path), paper_id),
                    ).rowcount
                if not attached:
                    path.unlink(missing_ok=True)
        except Exception:
            if path:
                path.unlink(missing_ok=True)
            raise
        flash(
            "Paper saved to your library. Start analysis to check every extracted link.",
            "success",
        )
        return redirect(url_for("main.detail", paper_id=paper_id))

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        """Validate an uploaded PDF, avoid duplicates, and save its metadata."""
        if request.method == "GET":
            return render_template("upload.html")
        file = request.files.get("pdf")
        if not file or not file.filename or Path(file.filename).suffix.lower() != ".pdf":
            flash("Choose a PDF file to upload.", "error")
            return redirect(url_for("main.upload"))
        year = request.form.get("year", "").strip()
        if year:
            try:
                year = int(year)
                if not 1000 <= year <= 9999:
                    raise ValueError
            except ValueError:
                flash("Enter a valid four-digit publication year.", "error")
                return redirect(url_for("main.upload"))
        else:
            year = None
        data = file.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
        if len(data) > current_app.config["MAX_CONTENT_LENGTH"]:
            abort(413)
        try:
            if b"%PDF-" not in data[:1024]:
                raise ValueError("The file is not a PDF.")
            with fitz.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise ValueError("Password-protected PDFs are not supported.")
                if (
                    not document.is_pdf
                    or not 1 <= len(document) <= current_app.config["MAX_PDF_PAGES"]
                ):
                    raise ValueError("Choose a PDF with 1 to 300 pages.")
                title = (
                    request.form.get("title", "").strip()[:300]
                    or (document.metadata.get("title") or "").strip()[:300]
                    or Path(file.filename).stem[:300]
                )
        except (ValueError, RuntimeError, fitz.FileDataError) as exc:
            flash("Could not read this PDF: " + str(exc)[:250], "error")
            return redirect(url_for("main.upload"))
        fingerprint = hashlib.sha256(data).hexdigest()
        with connection() as db:
            existing = db.execute(
                "SELECT id FROM papers WHERE identity=?", ("upload:" + fingerprint,)
            ).fetchone()
        if existing:
            flash("This PDF is already in your library.", "info")
            return redirect(url_for("main.detail", paper_id=existing["id"]))
        path = Path(current_app.config["UPLOAD_FOLDER"]) / (uuid.uuid4().hex + ".pdf")
        path.write_bytes(data)
        try:
            paper_id = save_paper(
                {
                    "title": title,
                    "authors": [],
                    "source": "Upload",
                    "upload_hash": fingerprint,
                    "local_path": str(path),
                    "year": year,
                    "area": request.form.get("area", "").strip()[:80] or "Uncategorized",
                }
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if get_paper(paper_id)["local_path"] != str(path):
            path.unlink(missing_ok=True)
        flash("PDF saved. Start analysis to check every extracted link.", "success")
        return redirect(url_for("main.detail", paper_id=paper_id))

    @app.route("/papers/<int:paper_id>", methods=["GET"])
    def detail(paper_id):
        paper = paper_or_404(paper_id)
        return render_template(
            "paper.html",
            paper=paper,
            resources=get_resources(paper_id),
            job=latest_job(paper_id),
            categories=CATEGORIES,
        )

    @app.get("/papers/<int:paper_id>/pdf")
    def open_pdf(paper_id):
        paper = paper_or_404(paper_id)
        return send_file(paper_pdf_source(paper), mimetype="application/pdf",
                         download_name=paper_pdf_filename(paper), max_age=0)

    @app.get("/papers/<int:paper_id>/download.pdf")
    def download_paper_pdf(paper_id):
        paper = paper_or_404(paper_id)
        return send_file(paper_pdf_source(paper), mimetype="application/pdf",
                         as_attachment=True, download_name=paper_pdf_filename(paper), max_age=0)

    @app.get("/papers/<int:paper_id>/text")
    def view_paper(paper_id):
        paper = paper_or_404(paper_id)
        source = paper_pdf_source(paper)
        pages, text_size = [], 0
        try:
            document = (fitz.open(source) if isinstance(source, Path)
                        else fitz.open(stream=source.getvalue(), filetype="pdf"))
            with document:
                if document.needs_pass:
                    abort(422, description="Password-protected PDFs cannot be displayed as text.")
                if not document.is_pdf or not 1 <= len(document) <= current_app.config["MAX_PDF_PAGES"]:
                    abort(422, description="Choose a PDF with 1 to 300 pages.")
                for number, page in enumerate(document, 1):
                    text = page.get_text("text", sort=True)
                    text_size += len(text)
                    if text_size > 3_000_000:
                        abort(422, description="The PDF text exceeds the display limit.")
                    pages.append({"number": number, "text": text})
        except (OSError, ValueError, RuntimeError):
            abort(422, description="This PDF could not be read as text.")
        warnings = (["Little readable text was found. Scanned pages need OCR, which is not included."]
                    if sum(len(page["text"].strip()) for page in pages) < 100 else [])
        return render_template("paper_text.html", paper=paper, pages=pages, warnings=warnings)

    @app.route("/papers/<int:paper_id>/analyze", methods=["POST"])
    def analyze_paper(paper_id):
        paper_or_404(paper_id)
        try:
            start_analysis(paper_id)
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("main.detail", paper_id=paper_id))

    @app.route("/papers/<int:paper_id>/status", methods=["GET"])
    def analysis_status(paper_id):
        paper = paper_or_404(paper_id)
        return jsonify(status=paper["analysis_status"], job=latest_job(paper_id))

    @app.route("/resources/<int:resource_id>/category", methods=["POST"])
    def update_category(resource_id):
        category = request.form.get("category")
        if category not in CATEGORIES:
            abort(400, description="Invalid resource category.")
        with connection() as db:
            resource = db.execute("SELECT * FROM resources WHERE id=?", (resource_id,)).fetchone()
            if not resource:
                abort(404)
            paper_id = resource["paper_id"]
            if (
                db.execute("SELECT analysis_status FROM papers WHERE id=?", (paper_id,)).fetchone()[
                    0
                ]
                == "analyzing"
            ):
                flash("Wait for analysis to finish before editing categories.", "info")
                return redirect(url_for("main.detail", paper_id=paper_id))
        try:
            rescore(paper_id, resource_id=resource_id, category=category)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("main.detail", paper_id=paper_id))
        flash("Category updated. All links keep equal weight in the score.", "success")
        return redirect(url_for("main.detail", paper_id=paper_id, _anchor="resources"))

    @app.route("/papers/<int:paper_id>/report.json", methods=["GET"])
    def report_json(paper_id):
        paper = paper_or_404(paper_id)
        if not paper["report"]:
            abort(404, description="Analyze the paper before downloading its report.")
        paper.pop("local_path", None)
        return Response(
            json.dumps({"paper": paper, "resources": get_resources(paper_id)}, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="paperlens-{paper_id}.json"'},
        )

    def csv_safe(value):
        """Prevent spreadsheet applications from interpreting exported text as formulas."""
        value = "" if value is None else str(value)
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    @app.route("/library.csv", methods=["GET"])
    def library_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Title",
                "Authors",
                "Year",
                "Area",
                "Source",
                "Status",
                "Link accessibility score",
                "Analyzed at",
                "Paper URL",
            ]
        )
        for paper in list_papers(filters()):
            writer.writerow(
                [
                    csv_safe(value)
                    for value in (
                        paper["title"],
                        "; ".join(paper["authors"]),
                        paper["year"],
                        paper["area"],
                        paper["source"],
                        paper["analysis_status"],
                        paper["score"],
                        (paper["report"] or {}).get("analyzed_at"),paper["paper_url"],
                    )
                ]
            )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="paperlens-library.csv"'},
        )
