import sqlite3

import pytest

from giftcompass import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE_PATH": tmp_path / "test.db"})


@pytest.fixture
def client(app):
    return app.test_client()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_profile_and_gift_flow(client, app):
    response = client.post(
        "/people/new",
        data={
            "name": "Alex",
            "relationship": "Friend",
            "birthday": "1990-12-10",
            "interests": "coffee, hiking",
            "dislikes": "clutter",
        },
    )
    assert response.status_code == 302
    person_url = response.headers["Location"]

    page = client.get(person_url)
    assert b"Alex" in page.data
    assert b"Something related to coffee" in page.data

    response = client.post(
        f"{person_url}/gifts",
        data={
            "title": "Insulated mug",
            "price": "24.99",
            "event_name": "Christmas",
        },
    )
    assert response.status_code == 302
    assert b"Insulated mug" in client.get(person_url).data

    with sqlite3.connect(app.config["DATABASE_PATH"]) as connection:
        gift_id = connection.execute("SELECT id FROM gifts").fetchone()[0]

    response = client.post(f"/gifts/{gift_id}/status", data={"status": "purchased"})
    assert response.status_code == 302

    with sqlite3.connect(app.config["DATABASE_PATH"]) as connection:
        assert (
            connection.execute("SELECT status FROM gifts").fetchone()[0] == "purchased"
        )


def test_name_is_required(client):
    response = client.post("/people/new", data={"name": ""})
    assert response.status_code == 400
    assert b"Name is required" in response.data


def test_unknown_person_returns_not_found(client):
    assert client.get("/people/999").status_code == 404
