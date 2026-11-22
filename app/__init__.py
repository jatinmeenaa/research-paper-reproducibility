import secrets
from pathlib import Path

from flask import Blueprint, Flask, abort, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from app.config import Config
from src.database.db import connection, init_db


def create_app(test_config=None, *, register_pages=True):
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'templates'),
                static_folder=str(root / 'static'))
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get('SECRET_KEY'):
        secret_path = root / 'instance' / 'secret.key'
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with secret_path.open('x', encoding='ascii') as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_path.read_text(encoding='ascii').strip()

    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()
        if app.config['RECOVER_INTERRUPTED_JOBS']:
            from src.analysis import recover_interrupted_jobs
            recover_interrupted_jobs()
        from src.analysis import upgrade_saved_scores
        upgrade_saved_scores()

    def csrf_token():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return session['csrf_token']

    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def validate_csrf():
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            expected = session.get('csrf_token', '')
            supplied = request.form.get('csrf_token', '')
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(400, description='Your form expired. Reload the page and try again.')

    @app.get('/health')
    def health():
        with connection() as db:
            db.execute('SELECT 1').fetchone()
        return jsonify(status='ok', database='connected')

    if register_pages:
        from app.routes import register_routes
        main = Blueprint('main', __name__)
        register_routes(main)
        app.register_blueprint(main)

    @app.errorhandler(HTTPException)
    def http_error(error):
        if not register_pages or request.path.endswith('/status'):
            return jsonify(error=error.description), error.code
        return render_template('error.html', code=error.code,
                               message=error.description), error.code

    @app.errorhandler(500)
    def server_error(error):
        if not register_pages:
            return jsonify(error='An unexpected error occurred.'), 500
        return render_template('error.html', code=500,
                               message='An unexpected error occurred. Please try again.'), 500

    return app
