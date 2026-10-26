"""The live stream: SSE framing over fetch, resume, torn lines, latency, end detection, no writes, clean disconnect.

Finished runs are read through the in-process TestClient (it only supports responses that end). Runs in
progress are served by a real uvicorn on 127.0.0.1 in a thread, read with a streaming httpx client, because
that is the only honest way to test an endless response.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import psutil
import pytest

from tests.unit.ui_server.live_helpers import (
    CANARY_FORBIDDEN,
    HAIKU,
    FakeRun,
    install_fixture,
    snapshot_tree,
)
from ui_server.settings import Settings

TOKEN = "stream-test-token-0123456789"


def parse_sse(text: str) -> list[dict]:
    """Parse SSE the way the frontend must: blank-line separated frames of ``id:``/``event:``/``data:``."""
    out = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        rec: dict = {"event": "message", "id": None, "data": None, "retry": None}
        for ln in frame.split("\n"):
            if ln.startswith(":"):
                continue
            name, _, val = ln.partition(":")
            val = val[1:] if val.startswith(" ") else val
            if name == "data":
                rec["data"] = (rec["data"] + "\n" + val) if rec["data"] is not None else val
            elif name in ("event", "id", "retry"):
                rec[name] = val
        if rec["data"] is not None:
            rec["json"] = json.loads(rec["data"])
        out.append(rec)
    return out


def events_of(frames, name="ev"):
    return [f["json"] for f in frames if f["event"] == name]


def get_stream(client, rid, headers=None, **params):
    r = client.get(f"/api/runs/{rid}/stream", params=params, headers=headers or {})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


# ---- finished runs (in-process) -------------------------------------------------------------------------

def test_framing_headers_and_event_sequence(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    r = client.get(f"/api/runs/{HAIKU}/stream", params={"from": "start"})
    assert r.headers["cache-control"].startswith("no-store") and r.headers["x-accel-buffering"] == "no"
    assert r.text.startswith("retry: 2000\n\n")
    frames = parse_sse(r.text)
    names = [f["event"] for f in frames]
    assert names[0] == "message" and names[1] == "hello" and names[-1] == "run.ended"
    assert names.count("caught-up") == 1 and names.index("caught-up") > 2
    hello = frames[1]["json"]
    assert hello["mode"] == "start" and hello["ended"] is True and hello["schema"] == 1
    ended = frames[-1]["json"]
    assert ended["state"] == "BUDGET_EXHAUSTED" and ended["scoring_complete"] is True
    # every data payload is one physical line (a payload with a newline would forge frames)
    for ln in r.text.split("\n"):
        assert not ln.startswith("data:") or ln.count("\n") == 0


def test_every_event_has_the_display_shape_and_a_resume_id(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    frames = get_stream(client, HAIKU, **{"from": "start"})
    evs = [f for f in frames if f["event"] == "ev"]
    assert len(evs) > 100
    for f in evs:
        assert f["id"].startswith("v1:") and f["json"]["cursor"].count(":") == 1
        assert {"id", "cursor", "t_s", "source", "type", "kind", "title", "summary", "severity", "level",
                "payload_preview", "truncated"} <= set(f["json"])
        assert f["json"]["level"] == "info"            # debug rows are filtered by default


def test_from_start_merges_sources_in_time_order_and_folds_stalls(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    evs = events_of(get_stream(client, HAIKU, **{"from": "start"}))
    ts = [e["ts"] for e in evs if e["ts"]]
    assert ts == sorted(ts)
    assert {e["source"] for e in evs} >= {"orchestrator", "guardrail", "agent_stream", "counterpart", "env"}
    folds = [e for e in evs if e["id"] == "fold:telemetry_stall"]
    assert len(folds) == 212 and folds[-1]["fold"]["pairs"] == 106       # same id re-emitted, last is final
    assert not [e for e in evs if e["type"] == "guardrail.telemetry_stalled"]
    unfolded = events_of(get_stream(client, HAIKU, **{"from": "start", "fold": "false"}, level="debug"))
    assert len([e for e in unfolded if e["type"] == "guardrail.telemetry_stalled"]) == 106


def test_default_is_the_last_n_visible_events(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    all_ev = events_of(get_stream(client, HAIKU, **{"from": "start"}))
    tail = events_of(get_stream(client, HAIKU, backlog=25))
    assert len(tail) <= 27 and len(tail) >= 20
    assert [e["cursor"] for e in tail][-5:] == [e["cursor"] for e in all_ev][-5:]
    assert events_of(get_stream(client, HAIKU, **{"from": "now"})) == []


def test_source_and_level_filters(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    g = events_of(get_stream(client, HAIKU, sources="guardrail", **{"from": "start"}))
    assert g and {e["source"] for e in g} == {"guardrail"}
    d = events_of(get_stream(client, HAIKU, sources="otel", level="debug", **{"from": "start"}))
    assert d and all(e["source"] == "otel" and e["kind"] == "usage" for e in d)
    assert events_of(get_stream(client, HAIKU, sources="otel", **{"from": "start"})) == []


def test_resume_with_last_event_id_has_no_gaps_or_duplicates(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    frames = get_stream(client, HAIKU, **{"from": "start"})
    evs = [f for f in frames if f["event"] == "ev"]
    for cut in (1, len(evs) // 3, len(evs) - 1):
        rest = [f for f in get_stream(client, HAIKU, headers={"Last-Event-ID": evs[cut - 1]["id"]}) if f["event"] == "ev"]
        # fold rows are re-emitted with the same id; compare the ordered ids of everything else
        want = [f["json"]["cursor"] for f in evs[cut:] if f["json"]["id"] != "fold:telemetry_stall"]
        got = [f["json"]["cursor"] for f in rest if f["json"]["id"] != "fold:telemetry_stall"]
        assert got == want, cut
    # ?from=<cursor> is the same thing
    again = [f for f in get_stream(client, HAIKU, **{"from": evs[10]["id"]}) if f["event"] == "ev"]
    assert [f["json"]["cursor"] for f in again if f["json"]["id"] != "fold:telemetry_stall"] == \
        [f["json"]["cursor"] for f in evs[11:] if f["json"]["id"] != "fold:telemetry_stall"]


def test_follow_zero_ends_after_the_backlog(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    frames = get_stream(client, HAIKU, follow="false", **{"from": "start"})
    assert frames[-1]["event"] == "caught-up" and "run.ended" not in [f["event"] for f in frames]


def test_kill_run_streams_the_kill_event(client, runs_dir):
    install_fixture(runs_dir, CANARY_FORBIDDEN)
    evs = events_of(get_stream(client, CANARY_FORBIDDEN, **{"from": "start"}))
    kill = next(e for e in evs if e["type"] == "guardrail.kill")
    assert kill["kind"] == "kill" and kill["severity"] == "kill" and "rm-rf-root" in kill["summary"]


@pytest.mark.parametrize("bad", ["v2:x=1", "v1:agent_stream=-1", "v1:../etc=1", "v1:" + "a=1," * 900, "everything", ""])
def test_bad_cursor_is_400(client, runs_dir, bad):
    install_fixture(runs_dir, CANARY_FORBIDDEN)
    r = client.get(f"/api/runs/{CANARY_FORBIDDEN}/stream", params={"from": bad})
    assert r.status_code == 400


def test_cursor_not_on_a_line_boundary_is_400(client, runs_dir):
    install_fixture(runs_dir, CANARY_FORBIDDEN)
    assert client.get(f"/api/runs/{CANARY_FORBIDDEN}/stream", params={"from": "v1:guardrail=7"}).status_code == 400


def test_bad_params_and_unknown_run(client, runs_dir):
    install_fixture(runs_dir, CANARY_FORBIDDEN)
    assert client.get(f"/api/runs/{CANARY_FORBIDDEN}/stream", params={"level": "loud"}).status_code == 400
    assert client.get(f"/api/runs/{CANARY_FORBIDDEN}/stream", params={"sources": "a/b"}).status_code == 400
    assert client.get("/api/runs/nonexistent/stream").status_code == 404
    assert client.get("/api/runs/..%2f..%2fetc/stream").status_code in (400, 404)


def test_token_is_required_in_a_header_and_never_in_the_query(client, runs_dir, settings):
    install_fixture(runs_dir, CANARY_FORBIDDEN)
    url = f"/api/runs/{CANARY_FORBIDDEN}/stream"
    no_auth = {"X-LRAE-Token": ""}
    assert client.get(url, headers=no_auth).status_code == 401
    assert client.get(url, params={"token": settings.token}, headers=no_auth).status_code == 401
    assert client.get(url, params={"access_token": settings.token}, headers=no_auth).status_code == 401
    assert client.get(url, params={"follow": "false"}).status_code == 200      # the header (default) works
    # a foreign Origin (a web page elsewhere) is refused before anything streams
    assert client.get(url, headers={"Origin": "http://evil.example"}).status_code == 403


def test_streaming_a_finished_run_does_not_touch_it(client, runs_dir):
    for rid in (HAIKU, CANARY_FORBIDDEN):
        install_fixture(runs_dir, rid)
    before = snapshot_tree(runs_dir)
    for rid in (HAIKU, CANARY_FORBIDDEN):
        get_stream(client, rid, **{"from": "start"})
        get_stream(client, rid)
    assert snapshot_tree(runs_dir) == before


def test_paged_feed_matches_the_stream(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    streamed = [e["cursor"] for e in events_of(get_stream(client, HAIKU, **{"from": "start"}))
                if e["id"] != "fold:telemetry_stall"]
    got, cursor, pages = [], "start", 0
    while True:
        page = client.get(f"/api/runs/{HAIKU}/feed", params={"from": cursor, "limit": 70}).json()
        got += [e["cursor"] for e in page["events"] if e["id"] != "fold:telemetry_stall"]
        cursor, pages = page["next_cursor"], pages + 1
        if page["at_end"] or pages > 50:
            break
    assert got == streamed and pages > 1
    assert client.get(f"/api/runs/{HAIKU}/feed", params={"from": "bogus"}).status_code == 400


def test_feed_event_returns_one_event_with_bigger_caps(client, runs_dir):
    install_fixture(runs_dir, HAIKU)
    page = client.get(f"/api/runs/{HAIKU}/feed", params={"from": "start", "limit": 400}).json()
    ev = next(e for e in page["events"] if e["type"] == "assistant.text")
    one = client.get(f"/api/runs/{HAIKU}/feed/event", params={"ref": ev["cursor"]}).json()
    assert one["cursor"] == ev["cursor"] and one["raw_bytes"] > 0 and one["type"] == "assistant.text"
    assert client.get(f"/api/runs/{HAIKU}/feed/event", params={"ref": "guardrail:3"}).status_code == 404
    assert client.get(f"/api/runs/{HAIKU}/feed/event", params={"ref": "../x:1"}).status_code == 400


def test_feed_schema_endpoint(client):
    s = client.get("/api/feed-schema").json()
    assert s["version"] == 1 and "tool_call" in {k["kind"] for k in s["kinds"]}


# ---- runs in progress (real server) ----------------------------------------------------------------------

class Live:
    def __init__(self, runs_dir: Path):
        import uvicorn

        from ui_server.app import create_app
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.settings = Settings(repo_root=Path(__file__).resolve().parents[3], runs_dir=runs_dir, token=TOKEN,
                                 port=self.port, web_dist=runs_dir / "no-dist")
        cfg = uvicorn.Config(create_app(self.settings), host="127.0.0.1", port=self.port, log_level="warning",
                             lifespan="off")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started
        self.base = f"http://127.0.0.1:{self.port}"
        self.headers = {"X-LRAE-Token": TOKEN}

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)


class Reader:
    """Reads an SSE response on a thread into a list of (arrival time, frame)."""

    def __init__(self, live: Live, rid: str, headers=None, **params):
        self.frames: list[tuple[float, dict]] = []
        self.client = httpx.Client(base_url=live.base, headers={**live.headers, **(headers or {})}, timeout=None)
        self.status = None
        self.done = threading.Event()
        self._cm = self.client.stream("GET", f"/api/runs/{rid}/stream", params=params)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        buf = ""
        try:
            with self._cm as resp:
                self.status = resp.status_code
                for chunk in resp.iter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        frame, buf = buf.split("\n\n", 1)
                        for f in parse_sse(frame + "\n\n"):
                            f["_wall"] = time.time()
                            self.frames.append((time.monotonic(), f))
        except Exception:   # closed by the test
            pass
        finally:
            self.done.set()

    def wait_for(self, pred, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for t, f in list(self.frames):
                if pred(f):
                    return t, f
            time.sleep(0.01)
        raise AssertionError(f"timed out; saw {[f['event'] for _, f in self.frames][-10:]}")

    def close(self):
        self.client.close()
        self.thread.join(5)


@pytest.fixture
def live(runs_dir):
    lv = Live(runs_dir)
    yield lv
    lv.stop()


@pytest.fixture
def run(runs_dir):
    r = FakeRun(runs_dir)
    yield r
    r.close()


def test_new_events_arrive_within_two_seconds(live, run):
    rd = Reader(live, run.rid, heartbeat_s=0.5)
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        lat = []
        for i in range(5):
            t0 = time.monotonic()
            run.tool(i, command=f"echo {i}")
            t, _ = rd.wait_for(lambda f, i=i: f["event"] == "ev" and f["json"]["type"] == "tool.call"
                               and f["json"]["summary"] == f"echo {i}", 2.0)
            lat.append(t - t0)
        assert max(lat) < 2.0, lat
        assert sorted(lat)[len(lat) // 2] < 1.0, lat      # typically one poll interval
    finally:
        rd.close()


def test_torn_line_is_held_back_until_complete(live, run):
    rd = Reader(live, run.rid)
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        path = run.dir / "events" / "agent_stream.jsonl"
        full = (json.dumps({"ts": "2999-01-01T00:00:00Z", "mono_ns": 1, "run_id": run.rid, "source": "agent_stream",
                            "type": "assistant.text", "seq": 77, "payload": {"text": "whole message"}}) + "\n").encode()
        fd = __import__("os").open(path, __import__("os").O_WRONLY | __import__("os").O_APPEND | __import__("os").O_CREAT)
        try:
            __import__("os").write(fd, full[:30])
            time.sleep(1.0)
            assert not [f for _, f in rd.frames if f["event"] == "ev" and "whole message" in f["data"]]
            assert not [f for _, f in rd.frames if f["event"] == "ev" and f["json"]["type"] == "log.invalid"]
            __import__("os").write(fd, full[30:])
        finally:
            __import__("os").close(fd)
        _, f = rd.wait_for(lambda f: f["event"] == "ev" and "whole message" in f["data"], 2.0)
        assert f["json"]["kind"] == "assistant_text"
    finally:
        rd.close()


def test_events_from_a_file_that_appears_later_are_picked_up(live, run):
    rd = Reader(live, run.rid)
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        run.append("guardrail", "guardrail.violation", {"rule_id": "network-tool", "severity": "warning",
                                                        "action": "log", "channel": "command", "evidence": "curl x"})
        _, f = rd.wait_for(lambda f: f["event"] == "ev" and f["json"]["source"] == "guardrail", 2.0)
        assert f["json"]["kind"] == "guardrail" and f["json"]["severity"] == "warning"
    finally:
        rd.close()


def test_heartbeat_and_idle_connection(live, run):
    rd = Reader(live, run.rid, heartbeat_s=0.3)
    try:
        _, hb = rd.wait_for(lambda f: f["event"] == "heartbeat", 3.0)
        assert hb["json"]["cursor"].startswith("v1:") and "idle_s" in hb["json"]
        n = len([1 for _, f in rd.frames if f["event"] == "heartbeat"])
        time.sleep(1.0)
        assert len([1 for _, f in rd.frames if f["event"] == "heartbeat"]) > n
    finally:
        rd.close()


def test_reconnect_with_last_event_id_continues_exactly(live, run):
    for i in range(3):
        run.tool(i)
    rd = Reader(live, run.rid, **{"from": "start"})
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        seen = [f for _, f in rd.frames if f["event"] == "ev"]
        last_id = seen[-1]["id"]
    finally:
        rd.close()
    run.tool(10, command="after-disconnect")
    rd2 = Reader(live, run.rid, headers={"Last-Event-ID": last_id})
    try:
        rd2.wait_for(lambda f: f["event"] == "caught-up")
        rd2.wait_for(lambda f: f["event"] == "ev" and f["json"]["summary"] == "after-disconnect")
        again = [f["json"]["cursor"] for _, f in rd2.frames if f["event"] == "ev"]
        assert [c for c in again if c in {s["json"]["cursor"] for s in seen}] == []   # nothing re-sent
        assert len(again) == 2                                                         # tool.call + tool.result
    finally:
        rd2.close()


def test_run_end_is_announced_and_the_stream_closes(live, run):
    rd = Reader(live, run.rid)
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        run.tool(1)
        run.append("orchestrator", "scorer.queued", {"k": 1})
        run.finish("COMPLETED", cost=0.5, tokens=10)
        rd.wait_for(lambda f: f["event"] == "run.ending", 4.0)
        time.sleep(2.2)
        assert not [1 for _, f in rd.frames if f["event"] == "run.ended"], "scoring still in flight: not over yet"
        run.append("orchestrator", "scorer.finished", {"k": 1, "returncode": 0})
        _, ended = rd.wait_for(lambda f: f["event"] == "run.ended", 5.0)
        assert ended["json"]["state"] == "COMPLETED" and ended["json"]["scoring_complete"] is True
        assert rd.done.wait(3), "the server closes the response after run.ended"
        # the final state event was delivered before the end marker
        names = [f["json"]["type"] for _, f in rd.frames if f["event"] == "ev"]
        assert "state" in names
    finally:
        rd.close()


def test_a_crashed_harness_ends_the_stream_as_unfinished(live, run, runs_dir):
    rd = Reader(live, run.rid)
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        run.manifest["harness_pid"] = 2_147_483_000
        run.write_manifest()
        _, ended = rd.wait_for(lambda f: f["event"] == "run.ended", 8.0)
        assert ended["json"]["state"] == "UNFINISHED" and ended["json"]["crashed"] is True
    finally:
        rd.close()


def test_stream_issues_no_writes_and_leaves_no_files(live, run, runs_dir):
    run.start(interval_s=0.02)
    rd = Reader(live, run.rid, **{"from": "start"})
    try:
        rd.wait_for(lambda f: f["event"] == "caught-up")
        time.sleep(0.8)
        requests = httpx.Client(base_url=live.base, headers=live.headers)
        requests.get(f"/api/runs/{run.rid}/live")
        requests.get(f"/api/runs/{run.rid}/safety")
        requests.get(f"/api/runs/{run.rid}/feed")
        requests.close()
    finally:
        rd.close()
    run.stop.set()
    run.thread.join(5)
    files = set(snapshot_tree(run.dir))
    assert files == {"manifest.json", "events/", "events/orchestrator.jsonl", "events/agent_stream.jsonl",
                     "events/otel.jsonl"}
    # nothing appeared next to the runs either (no lock files, no cache dirs)
    assert {p.name for p in runs_dir.iterdir()} == {run.rid}
    # and the log content is exactly what the writer wrote: every line parses, seq is gapless
    for name in ("agent_stream", "otel", "orchestrator"):
        seqs = [json.loads(ln)["seq"] for ln in (run.dir / "events" / f"{name}.jsonl").read_text().splitlines()]
        assert seqs == list(range(len(seqs)))


def test_disconnect_leaks_no_threads_or_file_descriptors(live, run):
    proc = psutil.Process()
    run.start(interval_s=0.02)
    time.sleep(0.5)
    # warm up once so lazily created pools and sockets do not count
    rd = Reader(live, run.rid)
    rd.wait_for(lambda f: f["event"] == "caught-up")
    rd.close()
    time.sleep(1.0)
    fds0, threads0 = proc.num_fds(), threading.active_count()
    for _ in range(6):
        rd = Reader(live, run.rid, **{"from": "start"})
        rd.wait_for(lambda f: f["event"] == "caught-up")
        rd.close()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.num_fds() <= fds0 + 1 and threading.active_count() <= threads0 + 1:
            break
        time.sleep(0.2)
    assert proc.num_fds() <= fds0 + 2, (fds0, proc.num_fds())
    assert threading.active_count() <= threads0 + 2, (threads0, threading.active_count())
    # the server's own accounting agrees: no stream is still counted as open
    r = httpx.get(f"{live.base}/api/runs/{run.rid}/stream", params={"follow": "false", "from": "now"},
                  headers=live.headers, timeout=10)
    assert r.status_code == 200


def test_too_many_streams_are_refused_with_429(live, run):
    from ui_server.routes import live as live_routes
    readers = [Reader(live, run.rid) for _ in range(live_routes.MAX_STREAMS)]
    try:
        for r in readers:
            r.wait_for(lambda f: f["event"] == "caught-up")
        resp = httpx.get(f"{live.base}/api/runs/{run.rid}/stream", headers=live.headers, timeout=5)
        assert resp.status_code == 429
    finally:
        for r in readers:
            r.close()
    time.sleep(0.8)
    ok = httpx.get(f"{live.base}/api/runs/{run.rid}/stream", params={"follow": "false"}, headers=live.headers, timeout=5)
    assert ok.status_code == 200


def test_live_endpoint_over_http_tracks_a_running_run(live, run):
    c = httpx.Client(base_url=live.base, headers=live.headers)
    try:
        run.api_request(0.4, inp=100, out=10, cache_read=50_000)
        a = c.get(f"/api/runs/{run.rid}/live").json()
        assert a["live"] is True and a["state"] == "RUNNING" and a["cost"]["usd"] == pytest.approx(0.4)
        run.api_request(0.1)
        b = c.get(f"/api/runs/{run.rid}/live").json()
        assert b["cost"]["usd"] == pytest.approx(0.5) and b["cost"]["requests"] == 2
        t0 = time.monotonic()
        for _ in range(20):
            c.get(f"/api/runs/{run.rid}/live")
        assert (time.monotonic() - t0) / 20 < 0.1
    finally:
        c.close()
