"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory
from flask_cors import CORS

from api.routes import api_bp

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "change-me"  # noqa: S105

    # CORS for Vite dev server
    CORS(app, origins=["http://localhost:5173"])

    # Register API blueprint
    app.register_blueprint(api_bp)

    # Health check
    @app.route("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
