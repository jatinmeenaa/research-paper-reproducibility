from pathlib import Path

from flask import Flask, jsonify

from app.config import Config
from src.database.db import connection, init_db


def create_app(*, register_pages=False):
    root = Path(__file__).resolve().parents[1]

    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    app.config.from_object(Config)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(
        parents=True, exist_ok=True
    )

    with app.app_context():
        init_db()
        from src.analysis import recover_interrupted_jobs
        recover_interrupted_jobs()

    @app.get("/health")
    def health():
        with connection() as db:
            db.execute("SELECT 1").fetchone()

        return jsonify(
            status="ok",
            database="connected",
        )
    if register_pages:
        from app.routes import register_routes

        register_routes(app)

    return app