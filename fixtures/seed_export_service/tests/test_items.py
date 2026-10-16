def _create(client, headers, title="Blue Widget", **kw):
    return client.post("/items", json={"title": title, **kw}, headers=headers)


def test_create_item_generates_slug(client, alice):
    r = _create(client, alice, "Hello, World!")
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "hello-world"
    assert body["owner_id"] == 1


def test_duplicate_titles_get_unique_slugs(client, alice):
    _create(client, alice, "Thing")
    r = _create(client, alice, "Thing")
    assert r.json()["slug"] == "thing-2"


def test_get_item(client, alice):
    item_id = _create(client, alice).json()["id"]
    r = client.get(f"/items/{item_id}", headers=alice)
    assert r.status_code == 200
    assert r.json()["title"] == "Blue Widget"


def test_items_scoped_to_user(client, alice, bob):
    item_id = _create(client, alice).json()["id"]
    assert client.get(f"/items/{item_id}", headers=bob).status_code == 404
    assert client.get("/items", headers=bob).json()["total"] == 0


def test_delete_item(client, alice):
    item_id = _create(client, alice).json()["id"]
    assert client.delete(f"/items/{item_id}", headers=alice).status_code == 204
    assert client.get(f"/items/{item_id}", headers=alice).status_code == 404


def test_delete_missing_404(client, alice):
    assert client.delete("/items/999", headers=alice).status_code == 404


def test_validation_error(client, alice):
    assert _create(client, alice, "").status_code == 422
    assert _create(client, alice, "x", quantity=-1).status_code == 422
