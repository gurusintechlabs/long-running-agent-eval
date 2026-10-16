from app import audit
from app.pagination import clamp_page, has_more
from vendor.slugify_lite import slugify


def test_clamp_defaults_and_bounds():
    assert clamp_page(None, None).limit == 20
    assert clamp_page(1000, -5, max_limit=50) == clamp_page(50, 0)
    assert clamp_page(0, 0).limit == 1


def test_has_more():
    assert has_more(10, clamp_page(5, 0))
    assert not has_more(10, clamp_page(5, 5))


def test_list_pagination(client, alice):
    for i in range(5):
        client.post("/items", json={"title": f"item {i}"}, headers=alice)
    r = client.get("/items?limit=2&offset=2", headers=alice).json()
    assert r["total"] == 5
    assert [i["title"] for i in r["items"]] == ["item 2", "item 3"]


def test_audit_records_mutations(client, alice):
    item_id = client.post("/items", json={"title": "A"}, headers=alice).json()["id"]
    client.delete(f"/items/{item_id}", headers=alice)
    actions = [e["action"] for e in audit.list_entries(user_id=1)]
    assert actions == ["item.create", "item.delete"]


def test_slugify_vendor():
    assert slugify("  Crème Brûlée!! ") == "creme-brulee"
    assert slugify("a" * 200, max_length=10) == "a" * 10
