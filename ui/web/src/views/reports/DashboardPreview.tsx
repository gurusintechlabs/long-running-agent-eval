import { useEffect, useState } from "react";
import { compareApi } from "../../api";
import { Spinner } from "../../components";

function blobToDataUrl(b: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new Error("could not read figure"));
    r.readAsDataURL(b);
  });
}

/** Replace relative `figures/<name>.png` references with data: URLs fetched through the token-guarded API
 * (an <img> in the iframe cannot send the token). Only names the server listed are fetched. */
export async function inlineFigures(html: string, figures: Map<string, string>): Promise<string> {
  return html.replace(/(\bsrc=)(["'])(figures\/[A-Za-z0-9][A-Za-z0-9._-]*\.png)\2/g, (m, attr: string, q: string, name: string) => {
    const url = figures.get(name);
    return url ? `${attr}${q}${url}${q}` : m;
  });
}

export async function buildDashboardDoc(experiment: string, figureNames: string[]): Promise<string> {
  const html = await compareApi.fileText(experiment, "dashboard.html");
  const used = figureNames.filter((n) => html.includes(n));
  const entries = await Promise.all(
    used.map(async (n) => [n, await blobToDataUrl(await compareApi.fileBlob(experiment, n))] as const),
  );
  return inlineFigures(html, new Map(entries));
}

/**
 * Open a Blob (fetched with the token) in a new tab. The tab is opened synchronously inside the click so
 * popup blockers allow it; if it is blocked we fall back to a download.
 */
export async function openBlob(pending: Promise<Blob>, filename: string): Promise<void> {
  const tab = window.open("", "_blank");
  if (tab) tab.opener = null;
  try {
    const blob = await pending;
    const url = URL.createObjectURL(blob);
    if (tab) {
      tab.location.href = url;
    } else {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
    }
    setTimeout(() => URL.revokeObjectURL(url), 120_000);
  } catch (e) {
    tab?.close();
    throw e;
  }
}

/** The dashboard inside a fully sandboxed iframe (no scripts, no same-origin): it is generated static HTML
 * that must never be able to reach the API or the token. `srcdoc` keeps it off the network entirely. */
export function DashboardPreview({ experiment, figures, builtAt }: { experiment: string; figures: string[]; builtAt: number }) {
  const [doc, setDoc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setDoc(null);
    setError(null);
    buildDashboardDoc(experiment, figures)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [experiment, builtAt]);

  if (error) return <p className="rp-hint rp-bad" role="alert">Could not load the dashboard: {error}</p>;
  if (doc == null) return <Spinner label="Loading dashboard" />;
  return <iframe className="rp-frame" title={`Dashboard of ${experiment}`} sandbox="" srcDoc={doc} />;
}
