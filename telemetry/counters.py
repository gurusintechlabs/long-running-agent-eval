"""Counters derived from the event logs (docs/spec.md §6.3). Phase 1 needs only cumulative cost."""
from __future__ import annotations

import json
from pathlib import Path


def cumulative_cost(otel_events: Path) -> float:
    """Σ ``cost_usd`` over ``claude_code.api_request`` events in an ``otel.jsonl`` file."""
    total = 0.0
    try:
        with open(otel_events) as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "claude_code.api_request":
                    total += float(ev.get("payload", {}).get("cost_usd") or 0)
    except OSError:
        pass
    return total
