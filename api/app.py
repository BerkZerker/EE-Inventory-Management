"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from api.routes import api_bp
from config import settings

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

    # CORS for Vite dev server
    CORS(app, origins=["http://localhost:5173"])

    # Register API blueprint
    app.register_blueprint(api_bp)

    # Health check
    @app.route("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Error handlers ---

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": "File too large", "details": "Maximum upload size is 20MB"}), 413

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found"}), 404
        # SPA fallback for non-API routes
        index = _FRONTEND_DIST / "index.html"
        if index.is_file():
            return send_from_directory(str(_FRONTEND_DIST), "index.html")
        resp = jsonify(message="Frontend not built. Run: cd frontend && npm run build")
        resp.status_code = 404
        return resp

    # SPA catch-all: serve frontend/dist/index.html in production
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path: str) -> Response:
        # Serve static file if it exists
        full = _FRONTEND_DIST / path
        if path and full.is_file():
            return send_from_directory(str(_FRONTEND_DIST), path)
        # Otherwise serve index.html for client-side routing
        index = _FRONTEND_DIST / "index.html"
        if index.is_file():
            return send_from_directory(str(_FRONTEND_DIST), "index.html")
        resp = jsonify(message="Frontend not built. Run: cd frontend && npm run build")
        resp.status_code = 404
        return resp

    return app
