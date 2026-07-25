"""Private web UI for managing monitored products."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from flask import Flask, abort, redirect, render_template, request, url_for

from database import Database
from retailers import resolve_retailer


def create_app(db: Database) -> Flask:
    app = Flask(__name__)
    csrf_token = secrets.token_urlsafe(32)

    def require_csrf() -> None:
        submitted = request.form.get("csrf_token", "")
        if not hmac.compare_digest(submitted, csrf_token):
            abort(400, "Invalid form token")

    @app.template_filter("timestamp")
    def timestamp(value: float | None) -> str:
        if value is None:
            return "Not checked yet"
        return datetime.fromtimestamp(value, UTC).strftime("%d %b %Y, %H:%M UTC")

    @app.get("/")
    def index():
        return render_template(
            "products.html",
            products=db.all(),
            csrf_token=csrf_token,
            error=request.args.get("error", ""),
        )

    @app.post("/products")
    def add_product():
        require_csrf()
        url = request.form.get("url", "").strip()
        name = request.form.get("name", "").strip() or None
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return redirect(url_for("index", error="Enter a valid HTTP product URL"))
        retailer = resolve_retailer(url).key
        db.add(url, retailer, name)
        return redirect(url_for("index"))

    @app.post("/products/<int:product_id>/delete")
    def delete_product(product_id: int):
        require_csrf()
        if not db.remove(product_id):
            abort(404)
        return redirect(url_for("index"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
