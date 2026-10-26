import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { _resetTokenForTests, authState } from "../api";
import { DataVersionProvider } from "../app/DataVersion";

import checkpointsEarly from "./fixtures/checkpoints_early.json";
import checkpointsHaiku from "./fixtures/checkpoints_haiku.json";
import experiments from "./fixtures/experiments.json";
import ingestStatus from "./fixtures/ingest_status.json";
import runEarly from "./fixtures/run_early.json";
import runHaiku from "./fixtures/run_haiku.json";
import runs from "./fixtures/runs.json";

export const fx = { checkpointsEarly, checkpointsHaiku, experiments, ingestStatus, runEarly, runHaiku, runs };

export type Handler = (init: RequestInit | undefined) => { status?: number; body: unknown };

/** Stub global fetch with a path -> response table (paths without the /api prefix). */
export function mockFetch(table: Record<string, unknown | Handler>) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^\/api/, "");
    calls.push({ path, init });
    const entry = table[path];
    if (entry === undefined) return new Response(JSON.stringify({ detail: "no such endpoint" }), { status: 404 });
    const r = typeof entry === "function" ? (entry as Handler)(init) : { body: entry };
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function resetAuth(token: string | null = "test-token") {
  _resetTokenForTests();
  authState.setDenied(false);
  window.sessionStorage.clear();
  if (token) window.sessionStorage.setItem("lrae.token", token);
}

export function renderRoute(ui: ReactElement, path: string, route: string) {
  return render(
    <DataVersionProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={ui} />
          <Route path="*" element={<div>elsewhere</div>} />
        </Routes>
      </MemoryRouter>
    </DataVersionProvider>,
  );
}

/** Stub fetch with a router function: receives the path WITH its query string (no /api prefix). */
export function mockRoutes(route: (path: string, init: RequestInit | undefined) => { status?: number; body: unknown } | undefined) {
  const calls: string[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^\/api/, "");
    calls.push(path);
    const r = route(path, init) ?? { status: 404, body: { detail: "no such endpoint" } };
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}
