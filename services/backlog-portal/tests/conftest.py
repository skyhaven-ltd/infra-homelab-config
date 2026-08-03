import json
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="backlog-portal-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TMP / 'test.db'}"
os.environ["PORTAL_USERNAME"] = "liam"
os.environ["PORTAL_PASSWORD"] = "secret"
os.environ["WORKER_TOKEN"] = "worker-secret"
os.environ["GITHUB_TOKEN"] = "github-secret"
os.environ["PORTAL_TARGETS"] = json.dumps(
    [
        {
            "id": "github-infra",
            "provider": "github",
            "label": "Homelab config",
            "organisation": "skyhaven-ltd",
            "container": "infra-homelab-config",
            "item_types": ["Bug", "Feature", "Task"],
            "project_id": "PVT_test",
            "template": "Use the infrastructure template.",
        }
    ]
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as value:
        yield value


@pytest.fixture()
def auth():
    return ("liam", "secret")
