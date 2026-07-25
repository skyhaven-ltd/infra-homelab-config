import re
import sqlite3

from database import Database
from web import create_app


def _client(tmp_path):
    db = Database(tmp_path / "web.db")
    app = create_app(db)
    app.config["TESTING"] = True
    return app.test_client(), db


def _csrf(client) -> str:
    page = client.get("/")
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)


def test_add_and_remove_product(tmp_path):
    client, db = _client(tmp_path)
    token = _csrf(client)

    added = client.post(
        "/products",
        data={
            "csrf_token": token,
            "url": "https://shop.example.com/widget",
            "name": "Useful widget",
        },
        follow_redirects=True,
    )
    assert added.status_code == 200
    assert "Useful widget" in added.text
    product = db.get("https://shop.example.com/widget")
    assert product.retailer == "generic"

    removed = client.post(
        f"/products/{product.id}/delete",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert removed.status_code == 200
    assert db.get("https://shop.example.com/widget") is None


def test_rejects_invalid_url_and_missing_csrf(tmp_path):
    client, db = _client(tmp_path)
    token = _csrf(client)

    invalid = client.post(
        "/products",
        data={"csrf_token": token, "url": "file:///etc/passwd"},
        follow_redirects=True,
    )
    assert "Enter a valid HTTP product URL" in invalid.text
    assert db.all() == []

    assert (
        client.post("/products", data={"url": "https://example.com"}).status_code == 400
    )


def test_existing_database_is_migrated_and_products_are_preserved(tmp_path):
    path = tmp_path / "existing.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            retailer TEXT NOT NULL,
            name TEXT,
            in_stock INTEGER NOT NULL DEFAULT 0,
            price TEXT,
            last_checked REAL,
            last_alert REAL,
            created REAL NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO products (url, retailer, created) VALUES (?, ?, ?)",
        ("https://shop.example/item", "generic", 1.0),
    )
    connection.commit()
    connection.close()

    db = Database(path)

    product = db.get("https://shop.example/item")
    assert product is not None
    assert product.enabled is True
