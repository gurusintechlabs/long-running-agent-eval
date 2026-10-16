"""Black-box acceptance tests for GET /export (HTTP only; no app imports)."""
import _support as s
from _support import HEADER, RATE_LIMIT, User, client, parse_csv


def test_auth_required_and_rejection_not_audited():
    with client() as c:
        before = s.audit_count()
        assert c.get("/export").status_code == 401
        assert c.get("/export", headers={"X-API-Key": "definitely-wrong"}).status_code == 401
        assert s.audit_count() == before


def test_csv_content_type_and_header_row():
    u = User(1)
    with client() as c:
        u.add_items(c, 1)
        r = u.export(c)
    assert r.status_code == 200
    ctype = r.headers["content-type"].replace(" ", "").lower()
    assert ctype.startswith("text/csv")
    assert "charset=utf-8" in ctype
    assert parse_csv(r.text)[0] == HEADER


def test_rows_match_items_in_id_order():
    u = User(2)
    with client() as c:
        c.post("/items", json={"title": "Blue Widget", "description": "shiny", "quantity": 7},
               headers=u.headers)
        c.post("/items", json={"title": "Plain"}, headers=u.headers)
        listed = c.get("/items", headers=u.headers).json()["items"]
        rows = parse_csv(u.export(c).text)
    assert len(rows) == 3 and len(listed) == 2
    for row, item in zip(rows[1:], listed):
        assert row == [str(item["id"]), item["title"], item["slug"], item["description"] or "",
                       str(item["quantity"]), item["created_at"]]
    assert rows[1][1:5] == ["Blue Widget", "blue-widget", "shiny", "7"]
    assert rows[2][3] == "" and rows[2][4] == "1"
    assert int(rows[1][0]) < int(rows[2][0])


def test_only_own_items_exported():
    a, b = User(3), User(4)
    with client() as c:
        a.add_items(c, 3, "alpha")
        b.add_items(c, 2, "beta")
        rows = parse_csv(b.export(c).text)
    titles = [r[1] for r in rows[1:]]
    assert titles == ["beta 000", "beta 001"]


def test_default_limit_is_20_and_total_count_header():
    u = User(5)
    with client() as c:
        u.add_items(c, 25)
        r = u.export(c)
    rows = parse_csv(r.text)
    assert len(rows) - 1 == 20
    assert rows[1][1] == "item 000" and rows[-1][1] == "item 019"
    assert r.headers["x-total-count"] == "25"


def test_limit_offset_pages_and_boundaries():
    u = User(6)
    with client() as c:
        u.add_items(c, 7)
        seen = []
        for offset, expected in [(0, 3), (3, 3), (6, 1)]:
            r = u.export(c, limit=3, offset=offset)
            assert r.status_code == 200
            rows = parse_csv(r.text)
            assert len(rows) - 1 == expected
            seen += [row[1] for row in rows[1:]]
        assert r.headers["x-total-count"] == "7"
        empty = parse_csv(u.export(c, limit=3, offset=7).text)
        far = u.export(c, offset=500)
    assert seen == [f"item {i:03d}" for i in range(7)]
    assert empty == [HEADER]
    assert far.status_code == 200 and parse_csv(far.text) == [HEADER]


def test_limit_clamped_and_negative_offset():
    u = User(7)
    with client() as c:
        u.add_items(c, 105)
        big = parse_csv(u.export(c, limit=1000).text)
        zero = parse_csv(u.export(c, limit=0).text)
        neg = parse_csv(u.export(c, limit=2, offset=-5).text)
    assert len(big) - 1 == 100
    assert len(zero) - 1 == 1 and zero[1][1] == "item 000"
    assert [r[1] for r in neg[1:]] == ["item 000", "item 001"]


def test_invalid_params_422_not_counted_or_audited():
    u = User(8)
    with client() as c:
        for params in ({"limit": "abc"}, {"offset": "x"}, {"limit": "1.5"}):
            assert u.export(c, **params).status_code == 422
        assert u.audit_count() == 0
        # none of the rejected requests consumed any of the user's quota
        for _ in range(RATE_LIMIT):
            assert u.export(c).status_code == 200


def test_csv_escaping_commas_quotes_newlines():
    u = User(9)
    cases = [
        ("Comma, title", "plain"),
        ('Quote "title"', 'she said "hi", then left'),
        ("Newline title", "line one\nline two"),
        ("CRLF title", "a\r\nb"),
    ]
    with client() as c:
        for title, desc in cases:
            assert c.post("/items", json={"title": title, "description": desc},
                          headers=u.headers).status_code == 201
        r = u.export(c)
    rows = parse_csv(r.text)
    assert [(row[1], row[3]) for row in rows[1:]] == cases
    assert all(len(row) == len(HEADER) for row in rows)
    assert '"Comma, title"' in r.text
    assert '"Quote ""title"""' in r.text


def test_rate_limit_429_after_limit_with_retry_after():
    u = User(10)
    with client() as c:
        u.add_items(c, 2)
        for _ in range(RATE_LIMIT):
            assert u.export(c).status_code == 200
        r = u.export(c)
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert u.export(c, limit=1).status_code == 429
        assert u.audit_count() == RATE_LIMIT  # 429s are not audited


def test_rate_limit_isolated_per_user():
    a, b = User(11), User(12)
    with client() as c:
        for _ in range(RATE_LIMIT):
            assert a.export(c).status_code == 200
        assert a.export(c).status_code == 429
        assert b.export(c).status_code == 200
        assert c.get("/items", headers=a.headers).status_code == 200  # only /export is limited


def test_one_audit_entry_per_successful_export():
    u = User(13)
    with client() as c:
        u.add_items(c, 3)  # item.create entries must not be mistaken for exports
        assert u.audit_count() == 0
        for n in range(1, 4):
            assert u.export(c).status_code == 200
            assert u.audit_count() == n
        assert u.export(c, limit=1, offset=1).status_code == 200
        assert u.audit_count() == 4
