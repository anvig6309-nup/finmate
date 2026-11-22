"""FinMate backend: Flask app that also serves the HTML frontend from ./frontend."""
import os

from flask import Flask, jsonify, send_from_directory

import api
import auth
import dashboard_api
import db
import security
import settings_api


def load_env_file(path):
    """Read KEY=value lines from a .env file (if it exists) without overriding real environment variables."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def create_app(test_config=None):
    app = Flask(__name__, static_folder="frontend", static_url_path="")
    if not test_config:
        load_env_file(os.path.join(app.root_path, ".env"))
    app.config.update(
        DATABASE=os.path.join(app.root_path, "finmate.db"),
        MAX_CONTENT_LENGTH=1_000_000,          # refuse request bodies bigger than 1 MB
        # Links inside emails use this fixed address (never the request's Host header, which an attacker could fake)
        BASE_URL=os.environ.get("FINMATE_BASE_URL", "http://127.0.0.1:5000"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):       # FINMATE_SECRET if set, otherwise a random key saved in secret.key
        app.config["SECRET_KEY"] = security.load_secret_key(app.root_path)
    app.after_request(security.add_security_headers)

    app.teardown_appcontext(db.close_db)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(dashboard_api.bp)
    app.register_blueprint(settings_api.bp)

    with app.app_context():
        db.init_db()

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/login")
    def login_page():
        return send_from_directory(app.static_folder, "login.html")

    @app.errorhandler(404)
    def not_found(_e):
        from flask import request
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return "Page not found", 404

    return app


if __name__ == "__main__":
    # debug=True is handy while developing. Set FINMATE_DEBUG=0 on any server other people can reach.
    create_app().run(debug=os.environ.get("FINMATE_DEBUG", "1") == "1", port=5000)
