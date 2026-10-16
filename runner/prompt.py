"""Assemble the t=0 prompt: task text plus the planted constraints, each stated exactly once."""
from __future__ import annotations

from pathlib import Path

import yaml


def assemble_prompt(prompt_file: Path | str, constraints_file: Path | str) -> str:
    body = Path(prompt_file).read_text().rstrip()
    doc = yaml.safe_load(Path(constraints_file).read_text()) or {}
    lines = [f"- {c['text']}" for c in doc.get("constraints", [])]
    if not lines:
        return body + "\n"
    return body + "\n\nConstraints (stated once, now; they apply for the whole task):\n" + "\n".join(lines) + "\n"
