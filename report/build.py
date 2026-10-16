"""Minimal one-page PDF report (docs/spec.md §13 item 5); Phase 6 replaces it with the real report."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from report.dashboard import collect_context, env

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
)


class ChromeNotFound(RuntimeError):
    pass


def find_chrome() -> str:
    override = os.environ.get("LRAE_CHROME")
    for cand in ([override] if override else []) + list(CHROME_CANDIDATES):
        path = cand if os.path.isabs(cand) and os.access(cand, os.X_OK) else shutil.which(cand)
        if path:
            return path
    raise ChromeNotFound("headless Chrome not found; install Google Chrome/Chromium or set LRAE_CHROME")


def build_pdf(db_path: Path, experiment_id: str, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    chrome = find_chrome()
    ctx = collect_context(db_path, experiment_id, out_dir)
    html_path = out_dir / "report.html"
    html_path.write_text(env().get_template("report_stub.html.j2").render(**ctx), encoding="utf-8")
    pdf = out_dir / "report.pdf"
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
             f"--user-data-dir={profile}", f"--print-to-pdf={pdf}", html_path.resolve().as_uri()],
            capture_output=True, text=True, timeout=120)
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(f"Chrome did not produce {pdf}: {proc.stderr[-500:]}")
    return pdf
