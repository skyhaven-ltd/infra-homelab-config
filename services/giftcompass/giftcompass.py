from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, url_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    relationship TEXT NOT NULL DEFAULT '',
    birthday TEXT,
    interests TEXT NOT NULL DEFAULT '',
    dislikes TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    price REAL,
    status TEXT NOT NULL DEFAULT 'idea',
    event_name TEXT NOT NULL DEFAULT '',
    event_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

STATUSES = ("idea", "shortlisted", "purchased", "given", "rejected")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_PATH=os.environ.get("DATABASE_PATH", "/data/giftcompass.db")
    )
    if test_config:
        app.config.update(test_config)

    database_path = Path(app.config["DATABASE_PATH"])
    database_path.parent.mkdir(parents=True, exist_ok=True)

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(database_path)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    def person_or_404(person_id: int) -> sqlite3.Row:
        person = (
            db().execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        )
        if person is None:
            abort(404)
        return person

    with app.app_context():
        db().executescript(SCHEMA)
        db().commit()

    @app.teardown_appcontext
    def close_database(_error=None):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.get("/health")
    def health():
        db().execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/")
    def index():
        people = (
            db()
            .execute(
                """
            SELECT p.*, COUNT(g.id) AS gift_count,
                   SUM(CASE WHEN g.status = 'purchased' THEN 1 ELSE 0 END) AS purchased
            FROM people p LEFT JOIN gifts g ON g.person_id = p.id
            GROUP BY p.id ORDER BY p.name COLLATE NOCASE
            """
            )
            .fetchall()
        )
        return render_template("index.html", people=people)

    @app.route("/people/new", methods=("GET", "POST"))
    def person_new():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                return render_template(
                    "person_form.html", error="Name is required"
                ), 400
            cursor = db().execute(
                """INSERT INTO people
                   (name, relationship, birthday, interests, dislikes, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    request.form.get("relationship", "").strip(),
                    request.form.get("birthday") or None,
                    request.form.get("interests", "").strip(),
                    request.form.get("dislikes", "").strip(),
                    request.form.get("notes", "").strip(),
                ),
            )
            db().commit()
            return redirect(url_for("person_detail", person_id=cursor.lastrowid))
        return render_template("person_form.html")

    @app.get("/people/<int:person_id>")
    def person_detail(person_id: int):
        person = person_or_404(person_id)
        gifts = (
            db()
            .execute(
                """SELECT * FROM gifts WHERE person_id = ?
                   ORDER BY created_at DESC, id DESC""",
                (person_id,),
            )
            .fetchall()
        )
        interests = [x.strip() for x in person["interests"].split(",") if x.strip()]
        suggestions = [f"Something related to {interest}" for interest in interests[:5]]
        if not suggestions:
            suggestions = ["Add a few interests to generate starting points"]
        return render_template(
            "person_detail.html",
            person=person,
            gifts=gifts,
            suggestions=suggestions,
            statuses=STATUSES,
            today=date.today().isoformat(),
        )

    @app.route("/people/<int:person_id>/edit", methods=("GET", "POST"))
    def person_edit(person_id: int):
        person = person_or_404(person_id)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                return render_template(
                    "person_form.html", person=person, error="Name is required"
                ), 400
            db().execute(
                """UPDATE people SET name=?, relationship=?, birthday=?,
                   interests=?, dislikes=?, notes=? WHERE id=?""",
                (
                    name,
                    request.form.get("relationship", "").strip(),
                    request.form.get("birthday") or None,
                    request.form.get("interests", "").strip(),
                    request.form.get("dislikes", "").strip(),
                    request.form.get("notes", "").strip(),
                    person_id,
                ),
            )
            db().commit()
            return redirect(url_for("person_detail", person_id=person_id))
        return render_template("person_form.html", person=person)

    @app.post("/people/<int:person_id>/gifts")
    def gift_new(person_id: int):
        person_or_404(person_id)
        title = request.form.get("title", "").strip()
        if not title:
            abort(400, "Gift title is required")
        price_text = request.form.get("price", "").strip()
        price = float(price_text) if price_text else None
        status = request.form.get("status", "idea")
        if status not in STATUSES:
            abort(400, "Invalid status")
        db().execute(
            """INSERT INTO gifts (
                   person_id, title, category, price, status,
                   event_name, event_date, notes
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                person_id,
                title,
                request.form.get("category", "").strip(),
                price,
                status,
                request.form.get("event_name", "").strip(),
                request.form.get("event_date") or None,
                request.form.get("notes", "").strip(),
            ),
        )
        db().commit()
        return redirect(url_for("person_detail", person_id=person_id))

    @app.post("/gifts/<int:gift_id>/status")
    def gift_status(gift_id: int):
        status = request.form.get("status", "")
        if status not in STATUSES:
            abort(400, "Invalid status")
        gift = (
            db()
            .execute("SELECT person_id FROM gifts WHERE id = ?", (gift_id,))
            .fetchone()
        )
        if gift is None:
            abort(404)
        db().execute("UPDATE gifts SET status = ? WHERE id = ?", (status, gift_id))
        db().commit()
        return redirect(url_for("person_detail", person_id=gift["person_id"]))

    @app.post("/gifts/<int:gift_id>/delete")
    def gift_delete(gift_id: int):
        gift = (
            db()
            .execute("SELECT person_id FROM gifts WHERE id = ?", (gift_id,))
            .fetchone()
        )
        if gift is None:
            abort(404)
        db().execute("DELETE FROM gifts WHERE id = ?", (gift_id,))
        db().commit()
        return redirect(url_for("person_detail", person_id=gift["person_id"]))

    return app
