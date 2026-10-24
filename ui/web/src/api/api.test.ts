import { beforeEach, describe, expect, it } from "vitest";
import { mockFetch, resetAuth } from "../test/helpers";
import { ApiAuthError, ApiError, api, authState, getToken, initToken, parseFragmentToken } from ".";

beforeEach(() => {
  resetAuth(null);
  window.history.replaceState(null, "", "/");
});

describe("token handling", () => {
  it("parses the fragment", () => {
    expect(parseFragmentToken("#token=abc-DEF_123")).toBe("abc-DEF_123");
    expect(parseFragmentToken("#other=1")).toBeNull();
    expect(parseFragmentToken("")).toBeNull();
  });

  it("reads the token once, keeps it in memory and sessionStorage, and strips it from the address bar", () => {
    window.history.replaceState(null, "", "/runs?x=1#token=secret123");
    expect(initToken()).toBe("secret123");
    expect(getToken()).toBe("secret123");
    expect(window.sessionStorage.getItem("lrae.token")).toBe("secret123");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/runs?x=1");
    expect(window.localStorage.getItem("lrae.token")).toBeNull();
  });

  it("recovers the token from sessionStorage after a reload", () => {
    window.sessionStorage.setItem("lrae.token", "persisted");
    expect(initToken()).toBe("persisted");
  });

  it("has no token when neither source has one", () => {
    expect(initToken()).toBeNull();
  });
});

describe("apiFetch", () => {
  it("sends the token header on every request", async () => {
    resetAuth("tok");
    initToken();
    const { calls } = mockFetch({ "/runs": { runs: [] } });
    await api.runs();
    const h = calls[0].init?.headers as Record<string, string>;
    expect(h["X-LRAE-Token"]).toBe("tok");
  });

  it("refuses to call the server without a token and flags access denied", async () => {
    const { fn } = mockFetch({ "/runs": { runs: [] } });
    await expect(api.runs()).rejects.toBeInstanceOf(ApiAuthError);
    expect(fn).not.toHaveBeenCalled();
    expect(authState.isDenied()).toBe(true);
  });

  it("turns a 401 into ApiAuthError and flags access denied", async () => {
    resetAuth("wrong");
    initToken();
    mockFetch({ "/runs": () => ({ status: 401, body: { detail: "missing or wrong token" } }) });
    await expect(api.runs()).rejects.toBeInstanceOf(ApiAuthError);
    expect(authState.isDenied()).toBe(true);
  });

  it("raises ApiError with the server detail on other failures", async () => {
    resetAuth("tok");
    initToken();
    mockFetch({ "/runs/nope": () => ({ status: 404, body: { detail: "no such run" } }) });
    const err = await api.run("nope").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("no such run");
  });

  it("url-encodes run ids", async () => {
    resetAuth("tok");
    initToken();
    const { calls } = mockFetch({ "/runs/a%2Fb%20c": { run: {}, manifest: {}, hazards: [] } });
    await api.run("a/b c");
    expect(calls[0].path).toBe("/runs/a%2Fb%20c");
  });

  it("returns a failed ingest as a result, not an exception", async () => {
    resetAuth("tok");
    initToken();
    mockFetch({ "/ingest": () => ({ status: 500, body: { ok: false, output: "boom" } }) });
    expect(await api.ingest()).toEqual({ ok: false, output: "boom" });
  });
});
