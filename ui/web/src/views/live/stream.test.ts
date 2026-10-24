import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { _resetTokenForTests, authState, initToken } from "../../api";
import { SseParser } from "./sse";
import { buildStreamUrl, followStream, toFrame, type StreamStatus } from "./streamClient";
import type { StreamFrame } from "./types";

import streamFixture from "../../test/fixtures/stream_haiku_tail.sse?raw";

function ev(id: string, extra: Record<string, unknown> = {}) {
  return { id, cursor: id, ts: "2026-10-23T10:00:00Z", t_s: 1, source: "agent_stream", type: "tool.call", kind: "tool_call", title: "Edit", summary: "x", severity: "info", pair: null, payload_preview: {}, fold: null, ...extra };
}
function frame(event: string, data: unknown, id?: string) {
  return `${id ? `id: ${id}\n` : ""}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("SseParser", () => {
  it("parses a frame split at every possible position", () => {
    const text = `retry: 2000\n\nid: v1:a=5\nevent: ev\ndata: {"a":1}\n\n`;
    for (let cut = 1; cut < text.length; cut++) {
      const p = new SseParser();
      const frames = [...p.push(text.slice(0, cut)), ...p.push(text.slice(cut))];
      expect(frames).toEqual([{ event: "ev", id: "v1:a=5", data: '{"a":1}', retry: null }]);
    }
  });

  it("returns several frames from one chunk, in order, and ignores comments", () => {
    const p = new SseParser();
    const out = p.push(`: hi\n\nevent: heartbeat\ndata: {"n":1}\n\nevent: ev\ndata: {"n":2}\n\nevent: ev\ndata: {"n":3}\n\n`);
    expect(out.map((f) => f.event)).toEqual(["heartbeat", "ev", "ev"]);
    expect(out.map((f) => JSON.parse(f.data).n)).toEqual([1, 2, 3]);
  });

  it("accepts CRLF and CR line ends, even with CR/LF split across chunks", () => {
    const p = new SseParser();
    const a = p.push("event: ev\r\ndata: 1\r");
    const b = p.push("\n\r\n");
    expect([...a, ...b]).toEqual([{ event: "ev", id: null, data: "1", retry: null }]);
    const c = new SseParser().push("event: ev\rdata: 2\r\rX");
    expect(c.map((f) => f.data)).toEqual(["2"]);
  });

  it("joins multi-line data with newlines and strips one leading space only", () => {
    const f = new SseParser().push("data:  two spaces\ndata: next\n\n");
    expect(f[0].data).toBe(" two spaces\nnext");
  });

  it("does not dispatch frames without data and drops a BOM", () => {
    const p = new SseParser();
    expect(p.push("﻿event: x\n\n")).toEqual([]);
    expect(p.push("data: 1\n\n")).toHaveLength(1);
  });

  it("keeps forged frames inside escaped text as text (the server sends one-line JSON)", () => {
    const evil = 'text\n\nevent: run.ended\ndata: {"state":"COMPLETED"}\n\nid: v1:forged=1';
    const wire = frame("ev", ev("agent_stream:1", { payload_preview: { text: evil }, summary: evil }), "v1:agent_stream=10");
    // the JSON.stringify output has no raw newline in the data line
    expect(wire.split("\n").filter((l) => l.startsWith("data:"))).toHaveLength(1);
    const p = new SseParser();
    const frames = [...p.push(wire.slice(0, 40)), ...p.push(wire.slice(40))];
    expect(frames).toHaveLength(1);
    expect(frames[0].id).toBe("v1:agent_stream=10");
    const f = toFrame(frames[0]) as Extract<StreamFrame, { event: "ev" }>;
    expect(f.event).toBe("ev");
    expect((f.data.payload_preview as { text: string }).text).toBe(evil);
  });

  it("parses the recorded haiku stream fixture", () => {
    const frames = new SseParser().push(streamFixture).map(toFrame).filter(Boolean) as StreamFrame[];
    expect(frames[0].event).toBe("hello");
    expect(frames.filter((f) => f.event === "ev").length).toBeGreaterThan(20);
    expect(frames.some((f) => f.event === "caught-up")).toBe(true);
    const ids = frames.filter((f) => f.event === "ev").map((f) => f.id);
    expect(ids.every((i) => i?.startsWith("v1:"))).toBe(true);
  });
});

describe("toFrame", () => {
  it("ignores unknown event names, bad JSON and malformed ev payloads", () => {
    expect(toFrame({ event: "evil", id: null, data: "{}" })).toBeNull();
    expect(toFrame({ event: "ev", id: null, data: "{not json" })).toBeNull();
    expect(toFrame({ event: "ev", id: null, data: '{"id":1}' })).toBeNull();
    expect(toFrame({ event: "heartbeat", id: null, data: "[]" })).toBeNull();
    expect(toFrame({ event: "heartbeat", id: null, data: '{"idle_s":3}' })?.event).toBe("heartbeat");
  });
});

describe("buildStreamUrl", () => {
  it("never puts the token in the URL and encodes the run id", () => {
    const u = buildStreamUrl("a b/c", { from: "tail", backlog: 50, level: "info", sources: ["guardrail", "scorer"], fold: false }, null);
    expect(u).toBe("/api/runs/a%20b%2Fc/stream?from=tail&backlog=50&sources=guardrail%2Cscorer&level=info&fold=false");
    expect(u).not.toMatch(/token/i);
  });
  it("uses the cursor instead of from/backlog on resume", () => {
    expect(buildStreamUrl("r", { from: "tail", backlog: 50 }, "v1:a=1")).toBe("/api/runs/r/stream?from=v1%3Aa%3D1");
  });
});

// ---- followStream ------------------------------------------------------------------------------------

const enc = new TextEncoder();
function body(chunks: string[], hold?: AbortSignal) {
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      if (hold) hold.addEventListener("abort", () => { try { c.error(new DOMException("aborted", "AbortError")); } catch { /* closed */ } });
      else c.close();
    },
  });
}

describe("followStream", () => {
  let calls: { url: string; headers: Record<string, string> }[];
  beforeEach(() => {
    _resetTokenForTests();
    authState.setDenied(false);
    window.history.replaceState(null, "", "/#token=tok");
    initToken();
  });
  afterEach(() => vi.unstubAllGlobals());

  function stub(responses: ((signal: AbortSignal) => Response)[]) {
    calls = [];
    let i = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url: String(url), headers: init.headers as Record<string, string> });
      const r = responses[Math.min(i++, responses.length - 1)];
      return r(init.signal as AbortSignal);
    }));
  }
  const noSleep = async () => {};

  it("sends the token header, delivers frames, and stops at run.ended", async () => {
    stub([() => new Response(body([frame("hello", { heartbeat_s: 10 }), frame("ev", ev("a:1"), "v1:a=1"), frame("run.ended", { state: "COMPLETED" })]), { status: 200 })]);
    const got: StreamFrame[] = [];
    const st: StreamStatus[] = [];
    const res = await followStream({ runId: "r1", signal: new AbortController().signal, onFrame: (f) => got.push(f), onStatus: (s) => st.push(s), sleep: noSleep });
    expect(res).toBe("ended");
    expect(got.map((f) => f.event)).toEqual(["hello", "ev", "run.ended"]);
    expect(calls).toHaveLength(1);
    expect(calls[0].headers["X-LRAE-Token"]).toBe("tok");
    expect(calls[0].url).not.toContain("tok");
    expect(st).toContain("open");
  });

  it("reconnects with Last-Event-ID and from=<cursor> after a dropped connection, with backoff", async () => {
    stub([
      () => new Response(body([frame("hello", {}), frame("ev", ev("a:1"), "v1:a=1"), frame("ev", ev("a:2"), "v1:a=2")]), { status: 200 }), // closes without run.ended
      () => new Response("", { status: 503 }),
      () => new Response(body([frame("hello", {}), frame("ev", ev("a:3"), "v1:a=3"), frame("run.ended", { state: "COMPLETED" })]), { status: 200 }),
    ]);
    const sleeps: number[] = [];
    const got: string[] = [];
    const st: StreamStatus[] = [];
    await followStream({
      runId: "r1", signal: new AbortController().signal, params: { from: "tail", backlog: 10 },
      onFrame: (f) => { if (f.event === "ev") got.push(f.data.id); }, onStatus: (s) => st.push(s),
      sleep: async (ms) => { sleeps.push(ms); },
    });
    expect(got).toEqual(["a:1", "a:2", "a:3"]);
    expect(calls).toHaveLength(3);
    expect(calls[0].headers["Last-Event-ID"]).toBeUndefined();
    expect(calls[1].headers["Last-Event-ID"]).toBe("v1:a=2");
    expect(calls[1].url).toContain("from=v1%3Aa%3D2");
    expect(calls[1].url).not.toContain("backlog");
    expect(calls[2].headers["Last-Event-ID"]).toBe("v1:a=2");
    expect(sleeps).toEqual([1000, 2000]); // second failure backs off further
    expect(st.filter((s) => s === "reconnecting").length).toBeGreaterThanOrEqual(2);
  });

  it("uses the heartbeat cursor when no ev arrived", async () => {
    stub([
      () => new Response(body([frame("hello", {}), frame("heartbeat", { cursor: "v1:z=9" })]), { status: 200 }),
      () => new Response(body([frame("run.ended", {})]), { status: 200 }),
    ]);
    await followStream({ runId: "r", signal: new AbortController().signal, onFrame: () => {}, sleep: noSleep });
    expect(calls[1].headers["Last-Event-ID"]).toBe("v1:z=9");
  });

  it("restarts from the tail and calls onReset when the server rejects the cursor (400)", async () => {
    stub([
      () => new Response(body([frame("hello", {}), frame("ev", ev("a:1"), "v1:a=1")]), { status: 200 }),
      () => new Response(JSON.stringify({ detail: "bad cursor" }), { status: 400 }),
      () => new Response(body([frame("run.ended", {})]), { status: 200 }),
    ]);
    const onReset = vi.fn();
    await followStream({ runId: "r", signal: new AbortController().signal, params: { from: "tail" }, onFrame: () => {}, onReset, sleep: noSleep });
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(calls[2].headers["Last-Event-ID"]).toBeUndefined();
    expect(calls[2].url).toContain("from=tail");
  });

  it("401 marks auth denied and stops; 404 fails without retrying", async () => {
    stub([() => new Response("", { status: 401 })]);
    expect(await followStream({ runId: "r", signal: new AbortController().signal, onFrame: () => {}, sleep: noSleep })).toBe("unauthorized");
    expect(authState.isDenied()).toBe(true);
    authState.setDenied(false);
    stub([() => new Response("", { status: 404 })]);
    expect(await followStream({ runId: "r", signal: new AbortController().signal, onFrame: () => {}, sleep: noSleep })).toBe("failed");
    expect(calls).toHaveLength(1);
  });

  it("a silent connection is aborted by the watchdog and reconnected", async () => {
    stub([
      (sig) => new Response(body([frame("hello", {})], sig), { status: 200 }), // then silence
      () => new Response(body([frame("run.ended", {})]), { status: 200 }),
    ]);
    const st: StreamStatus[] = [];
    await followStream({ runId: "r", signal: new AbortController().signal, watchdogMs: 30, onFrame: () => {}, onStatus: (s) => st.push(s), sleep: noSleep });
    expect(calls).toHaveLength(2);
    expect(st).toContain("reconnecting");
  });

  it("aborting stops everything (unmount) and passes the abort signal to fetch", async () => {
    const ctl = new AbortController();
    stub([(sig) => new Response(body([frame("hello", {})], sig), { status: 200 })]);
    const p = followStream({ runId: "r", signal: ctl.signal, onFrame: () => {}, sleep: noSleep });
    await new Promise((r) => setTimeout(r, 20));
    ctl.abort();
    expect(await p).toBe("ended");
    expect(calls).toHaveLength(1);
  });

  it("a finite stream (follow=false) ends after its backlog", async () => {
    stub([() => new Response(body([frame("hello", {}), frame("caught-up", { cursor: "v1:a=1", delivered: 0 })]), { status: 200 })]);
    const r = await followStream({ runId: "r", signal: new AbortController().signal, params: { follow: false }, onFrame: () => {}, sleep: noSleep });
    expect(r).toBe("ended");
    expect(calls).toHaveLength(1);
  });
});
