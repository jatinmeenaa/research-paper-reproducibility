import os
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    DATABASE = ROOT / "data" / "paperlens.db"
    UPLOAD_FOLDER = ROOT / "instance" / "uploads"

    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAX_PDF_PAGES = 300

    SEMANTIC_SCHOLAR_API_KEY = os.environ.get(
        "SEMANTIC_SCHOLAR_API_KEY", ""
    )