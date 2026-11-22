import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DATABASE = ROOT / 'data' / 'paperlens.db'
    UPLOAD_FOLDER = ROOT / 'instance' / 'uploads'
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAX_PDF_PAGES = 300
    RECOVER_INTERRUPTED_JOBS = True
    SEMANTIC_SCHOLAR_API_KEY = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', '')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
