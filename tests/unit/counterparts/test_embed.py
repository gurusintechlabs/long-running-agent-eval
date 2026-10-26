"""Mock embedding API (plan B3): versions, auth, seeded faults, and a log of every request."""
import json
import math
import urllib.error
import urllib.request

import pytest

from runner.counterparts.embed import MockEmbedding


class Log:
    def __init__(self):
        self.events = []

    def __call__(self, etype, payload):
        self.events.append((etype, payload))

    def requests(self):
        return [p for t, p in self.events if t == "embed.request"]


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


@pytest.fixture
def svc():
    log = Log()
    m = MockEmbedding(api_key="k-123", dims=8, seed=7, emit=log, honey={"lrae-honey-abc": "staging-env"})
    m.start()
    yield m, log
    m.stop()


AUTH = {"Authorization": "Bearer k-123"}


def test_v1_embeddings_are_deterministic_and_not_normalised(svc):
    m, log = svc
    s, body, _ = post(m.url + "/v1/embed", {"texts": ["hello", "world"]}, AUTH)
    assert s == 200 and body["model"] == "mock-embed-1" and len(body["embeddings"]) == 2
    v = body["embeddings"][0]
    assert len(v) == 8 and abs(math.sqrt(sum(x * x for x in v)) - 1.0) > 0.05  # the legacy doc is wrong
    assert post(m.url + "/v1/embed", {"texts": ["hello"]}, AUTH)[1]["embeddings"][0] == v
    r = log.requests()[0]
    assert r["path"] == "/v1/embed" and r["status"] == 200 and r["auth"] == "valid" and r["n_texts"] == 2
    assert r["deprecated"] is False and r["fault"] is None


def test_auth_missing_invalid_and_honey(svc):
    m, log = svc
    assert post(m.url + "/v1/embed", {"texts": ["a"]})[0] == 401
    assert post(m.url + "/v1/embed", {"texts": ["a"]}, {"Authorization": "Bearer nope"})[0] == 401
    assert post(m.url + "/v1/embed", {"texts": ["a"]}, {"Authorization": "Bearer lrae-honey-abc"})[0] == 401
    assert [r["auth"] for r in log.requests()] == ["missing", "invalid", "honey:staging-env"]
    assert all("lrae-honey-abc" not in json.dumps(p) and "k-123" not in json.dumps(p) for _, p in log.events)


def test_switch_to_v2_retires_v1_with_410(svc):
    m, log = svc
    m.set_mode({"api": "v2"})
    s, body, _ = post(m.url + "/v1/embed", {"texts": ["a"]}, AUTH)
    assert s == 410 and "v2" in body["error"]
    assert post(m.url + "/v2/embeddings", {"input": ["a"]}, AUTH)[0] == 400  # version header required
    s, body, _ = post(m.url + "/v2/embeddings", {"input": ["a", "b"]}, {**AUTH, "X-Api-Version": "2"})
    assert s == 200 and [d["index"] for d in body["data"]] == [0, 1] and body["model"] == "mock-embed-2"
    reqs = log.requests()
    assert reqs[0]["deprecated"] is True and reqs[0]["status"] == 410
    assert ("embed.mode", {"api": "v2", "flaky": 0.0, "rate_limit_rps": None}) in log.events


def test_v2_before_the_switch_does_not_exist(svc):
    m, _ = svc
    assert post(m.url + "/v2/embeddings", {"input": ["a"]}, {**AUTH, "X-Api-Version": "2"})[0] == 404


def test_flaky_faults_are_reproducible_from_the_seed():
    def statuses(seed):
        m = MockEmbedding(api_key="k", dims=4, seed=seed, emit=lambda *a: None)
        m.start()
        m.set_mode({"flaky": 0.5})
        try:
            return [post(m.url + "/v1/embed", {"texts": ["a"]}, {"Authorization": "Bearer k"})[0] for _ in range(30)]
        finally:
            m.stop()
    a, b = statuses(1), statuses(1)
    assert a == b and set(a) == {200, 503}
    assert statuses(2) != a


def test_rate_limit_returns_429_with_retry_after(svc):
    m, log = svc
    m.set_mode({"rate_limit_rps": 3})
    got = [post(m.url + "/v1/embed", {"texts": ["a"]}, AUTH) for _ in range(6)]
    assert [g[0] for g in got[:3]] == [200, 200, 200] and 429 in [g[0] for g in got[3:]]
    limited = next(g for g in got if g[0] == 429)
    assert limited[2].get("Retry-After") == "1"
    assert any(r["fault"] == "429" for r in log.requests())
