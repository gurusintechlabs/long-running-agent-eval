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
      await waitFor(async () => /spec hash/i.test(await text()), "the run detail page");
      const t = await text();
      check("run detail shows header, tabs and hazards", /spec hash/i.test(t) && /Hazards/.test(t) && /Timeline/.test(t) && /Transcript/.test(t));
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


      // 2b. The U3 tabs, each loaded by URL (deep links) against the real server.
      const base = origin + href;
      const count = (sel) => evaluate(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
      const tabs = [
        { id: "timeline", ready: () => count("canvas"), marker: /Incidents \(/, label: "timeline chart and incident list" },
        { id: "tests", ready: async () => ((await count("canvas")) > 0 || /need ingest/.test(await text()) ? 1 : 0), marker: /Test outcomes|need ingest|No per-test data/, label: "test heatmap (or its not-ingested call to action)" },
        { id: "transcript", ready: () => count(".tr-item"), marker: /Transcript/, label: "transcript items" },
        { id: "events", ready: () => count(".ev"), marker: /Events/, label: "event rows" },
        { id: "checkpoints", ready: () => count("tbody tr"), marker: /Checkpoints \(/, label: "checkpoints table" },
      ];
      for (const tab of tabs) {
        await goto(`${base}?tab=${tab.id}`);
        let ok = true;
        try {
          await waitFor(async () => tab.marker.test(await text()) && (await tab.ready()) > 0, `the ${tab.id} tab`, 30000);
        } catch (e) {
          ok = false;
          check(`${tab.id} tab renders ${tab.label}`, false, e.message);
        }
        if (ok) check(`${tab.id} tab renders ${tab.label}`, true);
        await sleep(1500);
        await shot(`tab-${tab.id}-light`);
        await shot(`tab-${tab.id}-dark`, { dark: true });
        if (tab.id === "timeline" || tab.id === "transcript") await shot(`tab-${tab.id}-narrow`, { width: 420, height: 900 });
      }

      // transcript: expand the first tool call, then a deep link to a time window.
      await goto(`${base}?tab=transcript`);
      await waitFor(async () => (await count(".tool-head")) > 0, "a tool call row");
      await evaluate("document.querySelector('.tool-head').click()");
      await waitFor(async () => (await count(".tool-detail pre")) > 0, "the expanded tool call", 15000).catch(() => {});
      check("transcript tool call expands with full input/result", (await count(".tool-detail")) > 0);
      await shot("tab-transcript-expanded-light");
      await goto(`${base}?tab=transcript&t_s=5000`);
      await waitFor(async () => (await count(".tr-hl")) > 0, "the highlighted target item", 15000).catch(() => {});
      check("transcript deep link highlights the target item", (await count(".tr-hl")) > 0);
      await shot("tab-transcript-deeplink-light");

      // events: open the first row (JSON viewer).
      await goto(`${base}?tab=events`);
      await waitFor(async () => (await count(".ev-head")) > 0, "event rows");
      await evaluate("document.querySelectorAll('.ev-head')[3].click()");
      await sleep(300);
      check("event row opens a JSON viewer", (await count(".json .j-row")) > 0);
      await shot("tab-events-open-light");

      // checkpoint drawer via URL: diff, then the scorer log.
      await goto(`${base}?tab=checkpoints&k=1`);
      await waitFor(async () => (await count('[role="dialog"]')) > 0 && (/Changes from|No git view|No new commits/.test(await text())), "the checkpoint drawer", 30000);
      check("checkpoint drawer shows the git view", true);
      await sleep(500);
      await shot("drawer-diff-light");
      await shot("drawer-diff-dark", { dark: true });
      await evaluate("[...document.querySelectorAll('[role=tab]')].find(b => b.textContent.startsWith('Scorer log')).click()");
      await sleep(1200);
      await shot("drawer-scorer-light");
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
