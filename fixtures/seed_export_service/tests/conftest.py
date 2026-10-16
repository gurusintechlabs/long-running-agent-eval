import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    with TestClient(create_app(":memory:")) as c:
        yield c


@pytest.fixture()
def alice():
    return {"X-API-Key": "key-alice"}


@pytest.fixture()
def bob():
    return {"X-API-Key": "key-bob"}
