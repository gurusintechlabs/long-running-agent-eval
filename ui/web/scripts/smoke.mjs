#!/usr/bin/env node
// Headless-Chrome smoke check (no Playwright): loads the BUILT app from a running `lrae ui`, visits the
// Runs page and a Run-detail page, and fails on any console error, uncaught exception, failed request or
// HTTP >= 400. Optionally saves screenshots (light, dark, narrow).
//
//   npm run build
//   node scripts/smoke.mjs                      # starts `lrae ui` itself on a free port (read-only use of runs/)
//   node scripts/smoke.mjs --url "http://127.0.0.1:8765/#token=..."   # use an already running server
//   options: --run <run_id>  --shots <dir>  --runs-dir <dir>
//
// Exit codes: 0 pass, 1 fail, 0 with "SKIP" if Chrome is not installed (set LRAE_CHROME to point at it).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../../..");

const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
};

const CHROME_CANDIDATES = [
  process.env.LRAE_CHROME,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
].filter(Boolean);

async function which(cmd) {
  if (path.isAbsolute(cmd)) return existsSync(cmd) ? cmd : null;
  for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
    const p = path.join(dir, cmd);
    if (existsSync(p)) return p;
  }
  return null;
}

async function findChrome() {
  for (const c of CHROME_CANDIDATES) {
    const p = await which(c);
    if (p) return p;
  }
  return null;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
    s.on("error", reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, what, timeoutMs = 20000) {
  const end = Date.now() + timeoutMs;
  let last;
  while (Date.now() < end) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (e) {
      last = e;
    }
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${what}${last ? `: ${last.message}` : ""}`);
}

// ---------- server ----------
async function startServer() {
  const py = process.env.LRAE_PYTHON ?? [path.join(repoRoot, ".venv/bin/python")].find(existsSync) ?? "python3";
  const port = await freePort();
  const runsDir = opt("runs-dir") ?? process.env.LRAE_RUNS_DIR ?? path.join(repoRoot, "runs");
  const child = spawn(py, ["-u", "-m", "runner.cli", "ui", "--port", String(port), "--runs-dir", runsDir], {
    cwd: repoRoot,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let out = "";
  child.stdout.on("data", (d) => (out += d));
  child.stderr.on("data", (d) => (out += d));
  const url = await waitFor(() => out.match(/(http:\/\/127\.0\.0\.1:\d+\/#token=\S+)/)?.[1], "lrae ui to print its URL", 30000).catch((e) => {
    child.kill();
    throw new Error(`${e.message}\n--- server output ---\n${out}`);
  });
  return { url, stop: () => child.kill() };
}

// ---------- chrome / CDP ----------
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.handlers = [];
    ws.addEventListener("message", (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      } else if (msg.method) {
        this.handlers.forEach((h) => h(msg));
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  on(h) {
    this.handlers.push(h);
  }
}

async function launchChrome(chrome) {
  const port = await freePort();
  const profile = mkdtempSync(path.join(os.tmpdir(), "lrae-smoke-"));
  const proc = spawn(
    chrome,
    ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars", "about:blank"],
    { stdio: "ignore" },
  );
  const target = await waitFor(async () => {
    const r = await fetch(`http://127.0.0.1:${port}/json/list`);
    const list = await r.json();
    return list.find((t) => t.type === "page");
  }, "Chrome to start");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener("open", res);
    ws.addEventListener("error", () => rej(new Error("cannot connect to Chrome DevTools")));
  });
  const close = async () => {
    ws.close();
    proc.kill();
    await sleep(500);
    try {
      rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      /* a temp dir left behind is harmless */
    }
  };
  return { cdp: new Cdp(ws), close };
}

async function main() {
  const dist = path.join(here, "..", "dist", "index.html");
  if (!existsSync(dist)) {
    console.error("FAIL: ui/web/dist is missing; run `npm run build` first");
    return 1;
  }
  const chrome = await findChrome();
  if (!chrome) {
    console.log("SKIP: headless Chrome not found (install Google Chrome/Chromium or set LRAE_CHROME)");
    return 0;
  }

  let server = null;
  let url = opt("url") ?? process.env.LRAE_UI_URL;
  if (!url) {
    server = await startServer();
    url = server.url;
  }
  const origin = new URL(url).origin;
  const shots = opt("shots");
  if (shots) mkdirSync(shots, { recursive: true });

  const { cdp, close } = await launchChrome(chrome);
  const problems = [];
  const consoleLines = [];
  cdp.on((m) => {
    if (m.method === "Runtime.consoleAPICalled" && ["error", "assert"].includes(m.params.type)) {
      problems.push(`console.${m.params.type}: ${m.params.args.map((a) => a.value ?? a.description ?? "").join(" ")}`);
    } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "warning") {
      consoleLines.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
    } else if (m.method === "Runtime.exceptionThrown") {
      problems.push(`exception: ${m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text}`);
    } else if (m.method === "Log.entryAdded" && m.params.entry.level === "error") {
      problems.push(`log: ${m.params.entry.text} ${m.params.entry.url ?? ""}`);
    } else if (m.method === "Network.responseReceived" && m.params.response.status >= 400) {
      problems.push(`http ${m.params.response.status}: ${m.params.response.url}`);
    } else if (m.method === "Network.loadingFailed" && !m.params.canceled) {
      problems.push(`request failed: ${m.params.errorText}`);
    }
  });
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");

  const evaluate = async (expression) => {
    const r = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return r.result.value;
  };
  const text = () => evaluate("document.body.innerText");
  const shot = async (name, { dark = false, width = 1360, height = 900 } = {}) => {
    if (!shots) return;
    await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
    await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }] });
    await sleep(500);
    const r = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    writeFileSync(path.join(shots, `${name}.png`), Buffer.from(r.data, "base64"));
  };
  const goto = async (u) => {
    await cdp.send("Page.navigate", { url: u });
    await sleep(300);
  };

  const results = [];
  const check = (name, ok, detail = "") => {
    results.push({ name, ok, detail });
    console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` (${detail})` : ""}`);
  };

  try {
    // 1. Runs page. The token arrives in the fragment and must be stripped from the address bar.
    await goto(url);
    await waitFor(async () => /\d+ of \d+ runs/.test(await text()), "the run table");
    check("runs page renders the run table", /Runs/.test(await text()) && (await evaluate("document.querySelectorAll('tbody tr').length")) > 0);
    check("token is stripped from the address bar", !(await evaluate("location.href")).includes("token"));
    await sleep(800);
    await shot("runs-light");
    await shot("runs-dark", { dark: true });
    await shot("runs-narrow", { width: 420, height: 900 });

    // 2. Run detail: preferred run, else the first row with metrics, else the first row.
    const want = opt("run");
    const href = await evaluate(`(() => {
      const links = [...document.querySelectorAll('a[href^="/runs/"]')];
      const hit = ${JSON.stringify(want ?? "")} && links.find(a => a.getAttribute('href') === '/runs/' + encodeURIComponent(${JSON.stringify(want ?? "")}));
      return (hit || links[0] || {}).getAttribute?.('href') ?? null;
    })()`);
    check("a run link exists", !!href);
    if (href) {
      await goto(origin + href);
      await waitFor(async () => /Checkpoints \(/.test(await text()), "the run detail page");
      const t = await text();
      check("run detail shows header, checkpoints and hazards", /spec hash/i.test(t) && /Checkpoints \(/.test(t) && /Hazards/.test(t));
      await sleep(1200); // let lazy ECharts load and paint
      await shot("run-detail-light");
      await shot("run-detail-dark", { dark: true });
      await shot("run-detail-narrow", { width: 420, height: 900 });
      // Run actions: open (never confirm) the dialog of the first action offered, then Esc.
      const label = await evaluate(`(() => { const b = [...document.querySelectorAll('.run-actions button')].find(x => /Stop…|Resume…|Re-score…/.test(x.textContent)); if (!b) return null; b.click(); return b.textContent; })()`);
      if (label) {
        await waitFor(async () => (await evaluate("document.querySelectorAll('[role=dialog]').length")) === 1, "the run-action dialog");
        await sleep(400);
        await shot("run-action-dialog-light");
        await shot("run-action-dialog-dark", { dark: true });
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await sleep(200);
        check(`run action "${label}" dialog opens and Esc closes it`, (await evaluate("document.querySelectorAll('[role=dialog]').length")) === 0);
      }
    }

    // 2b. Launch view: preview a SCRIPTED spec (no spend; preview starts nothing). Never touches a claude_code spec.
    await goto(`${origin}/launch`);
    await waitFor(async () => /Choose a spec/.test(await text()), "the Launch view");
    check("control bar is visible", /No run is active|A run is active/.test(await text()));
    await shot("launch-light");
    const picked = await evaluate(`(() => {
      const sel = document.querySelector('select');
      const opt = [...sel.options].find(o => o.value === 'spec/examples/pilot-scripted.yaml');
      if (!opt) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, opt.value);
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    check("scripted example spec is selectable", !!picked);
    if (picked) {
      await evaluate(`[...document.querySelectorAll('button')].find(b => b.textContent === 'Preview estimate').click()`);
      await waitFor(async () => /2\. Estimate/.test(await text()), "the estimate");
      const t = await text();
      check("scripted preview shows no-spend banner, max spend and checks", /no spend/i.test(t) && /max spend/i.test(t) && /pre-flight checks/i.test(t));
      await shot("launch-preview-light");
      await shot("launch-preview-dark", { dark: true });
      await shot("launch-preview-narrow", { width: 420, height: 900 });
      // The button is disabled when the server issued no nonce (blockers, e.g. the run folder already exists).
      const blocked = await evaluate(`[...document.querySelectorAll('button')].find(b => /Review and launch/.test(b.textContent)).disabled`);
      if (blocked) {
        check("blocked preview: confirm button disabled (no nonce)", true);
      } else {
        await evaluate(`[...document.querySelectorAll('button')].find(b => /Review and launch/.test(b.textContent)).click()`);
        await waitFor(async () => (await evaluate("document.querySelectorAll('[role=dialog]').length")) === 1, "the confirm dialog");
        check("confirm dialog opens (nothing launched)", /Scripted run: nothing is spent/.test(await text()));
        await shot("launch-confirm-light");
        await shot("launch-confirm-dark", { dark: true });
        await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
        await sleep(200);
        check("Esc closes the dialog", (await evaluate("document.querySelectorAll('[role=dialog]').length")) === 0);
      }
    }

    // 2c. Live view: replay finished runs (haiku pilot, canary kills) when they exist in this runs dir.
    const runIds = await evaluate(`fetch('/api/runs', { headers: { 'X-LRAE-Token': sessionStorage.getItem('lrae.token') } }).then(r => r.json()).then(j => j.runs.map(r => r.run_id))`);
    const replay = async (id, label) => {
      await goto(`${origin}/runs/${encodeURIComponent(id)}/live`);
      await waitFor(async () => (await evaluate("document.querySelectorAll('[data-testid^=card-]').length")) > 3, `${label} feed cards`);
      await waitFor(async () => (await evaluate("!!document.querySelector('.sl')")), `${label} status light`);
      await sleep(1500); // sparklines
      return evaluate("document.querySelector('.sl')?.dataset.status");
    };
    const haiku = runIds.find((r) => r.startsWith("minidb-v3-pilot-haiku"));
    if (haiku) {
      const st = await replay(haiku, "haiku replay");
      const t = await text();
      check("haiku replay: killed, 31 incidents, kill banner, budget", st === "killed" && (await evaluate("!!document.querySelector('[data-testid=kill-banner]')")) && /31/.test(t) && /Replay/.test(t));
      await shot("live-haiku-replay-light");
      await shot("live-haiku-replay-dark", { dark: true });
      await shot("live-haiku-replay-narrow", { width: 420, height: 900 });
      // expand the first incident's context
      await evaluate(`[...document.querySelectorAll('button')].find(b => /Show context/.test(b.textContent))?.click()`);
      await waitFor(async () => (await evaluate("document.querySelectorAll('.ctx-list li').length")) > 3, "incident context");
      check("incident context loads inline", true);
      await evaluate("document.querySelector('.ctx')?.scrollIntoView({block:'center'})");
      await shot("live-haiku-incident-context-light", { height: 1100 });
      // feed controls: warnings-only filter
      await evaluate(`(() => { const s = document.querySelector('select[aria-label="Minimum severity"]'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, 'warning'); s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
      await sleep(400);
      check("severity filter narrows the feed", /shown of/.test(await evaluate("document.querySelector('.feed-count')?.textContent ?? ''")));
    } else {
      console.log("note: no haiku pilot in this runs dir; skipping its replay check");
    }
    for (const prefix of ["canary-forbidden", "canary-harness-read"]) {
      const id = runIds.find((r) => r.startsWith(prefix));
      if (!id) continue;
      const st = await replay(id, `${prefix} replay`);
      check(`${prefix} replay shows the kill`, st === "killed" && (await evaluate("!!document.querySelector('[data-testid=kill-banner]')")));
      await shot(`live-${prefix}-light`);
      await shot(`live-${prefix}-dark`, { dark: true });
    }
    await goto(`${origin}/live`);
    // With exactly one active run /live jumps to it; otherwise the picker is shown.
    await waitFor(async () => /(Replay a finished run|Running now)/.test(await text()) || /\/runs\/.+\/live$/.test(await evaluate("location.pathname")), "the live run picker or redirect");
    check("/live shows the picker or jumps to the one active run", true);
    await shot("live-picker-light");

    // 2d. A LIVE scripted run (opt-in: `--live`, against a server whose runs dir has a scripted run in progress,
    // started with `lrae run ... --no-caffeinate`; scripted = no spend). `/live` must jump to the active run.
    if (args.includes("--live")) {
      await goto(`${origin}/live`);
      await waitFor(async () => /\/runs\/.+\/live$/.test(await evaluate("location.pathname")), "/live to redirect to the active run");
      await waitFor(async () => (await evaluate("document.querySelectorAll('[data-testid^=card-]').length")) > 3, "live feed cards");
      check("live page follows the active run (live badge, stream open)", (await evaluate("document.querySelector('.feed-bar')?.textContent ?? ''")).match(/live|catching up/) !== null);
      await sleep(4000);
      await shot("live-scripted-running-light");
      await shot("live-scripted-running-dark", { dark: true });
      await shot("live-scripted-running-narrow", { width: 420, height: 900 });
      const before = await evaluate("document.querySelectorAll('[data-testid^=card-]').length");
      await waitFor(async () => (await evaluate("document.querySelectorAll('[data-testid^=card-]').length")) > before, "new events to stream in", 120000);
      check("new events stream into the feed", true);
      await waitFor(async () => /Run ended/.test(await evaluate("document.querySelector('.feed-foot')?.textContent ?? ''")), "the run to end", 600000);
      await sleep(2500);
      check("end of run is announced", true);
      await shot("live-scripted-ended-light");
    }

    // 3. A placeholder route still loads through the SPA fallback.
    await goto(`${origin}/compare`);
    await waitFor(async () => /Not built yet/.test(await text()), "the Compare placeholder");
    check("placeholder route renders", true);
  } catch (e) {
    check("smoke flow", false, e.message);
  }

  check("no console errors, exceptions or failed requests", problems.length === 0, problems.slice(0, 5).join(" | "));
  if (consoleLines.length) console.log(`note: ${consoleLines.length} console warning(s): ${consoleLines[0]}`);

  await close();
  server?.stop();
  const failed = results.filter((r) => !r.ok);
  console.log(failed.length ? `\nSMOKE FAILED (${failed.length})` : "\nSMOKE PASSED");
  return failed.length ? 1 : 0;
}

main().then((code) => process.exit(code), (e) => {
  console.error("FAIL:", e.message);
  process.exit(1);
});
