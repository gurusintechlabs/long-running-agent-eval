from app.auth import resolve_user_id
from fastapi import HTTPException
import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_missing_key_rejected(client):
    assert client.get("/users/me").status_code == 401


def test_invalid_key_rejected(client):
    r = client.get("/users/me", headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_users_me(client, alice):
    r = client.get("/users/me", headers=alice)
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_resolve_user_id_unit():
    assert resolve_user_id({"k": 7}, "k") == 7
    with pytest.raises(HTTPException):
        resolve_user_id({"k": 7}, None)
