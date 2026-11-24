"""Run time from wall time, across resumes.

The orchestrator emits ``run.clock`` ``{start_epoch, offset_s}`` each time it enters RUNNING. On a resume from
checkpoint ``k`` it sets ``start_epoch = now - offset_s``, so ``start_epoch`` is already the virtual origin and
the segment really starts at ``start_epoch + offset_s``. An event in a segment is at run time
``epoch - start_epoch``; adding ``offset_s`` again counts it twice.

A segment that was followed by a resume ran past the checkpoint the resume picked up from, and that work was
discarded. Events from it (still real: a command did run) are placed at the resume point, the next segment's
``offset_s``, so they count once and never overlap the work that replaced them.
"""
from __future__ import annotations


class RunClock:
    def __init__(self, marks=()):
        self.marks: list[tuple[float, float]] = []   # (start_epoch, offset_s), ordered by real start
        for start, off in marks:
            self.add(start, off)

    def add(self, start_epoch, offset_s=0.0) -> None:
        if not _is_num(start_epoch):
            return
        mark = (float(start_epoch), float(offset_s) if _is_num(offset_s) else 0.0)
        if mark not in self.marks:
            self.marks.append(mark)
            self.marks.sort(key=lambda m: m[0] + m[1])

    @classmethod
    def from_events(cls, events) -> RunClock:
        c = cls()
        for ev in events:
            if ev.get("type") == "run.clock":
                p = ev.get("payload") or {}
                c.add(p.get("start_epoch"), p.get("offset_s"))
        return c

    def __bool__(self) -> bool:
        return bool(self.marks)

    @property
    def origin(self) -> float | None:
        """The current segment's origin (the last ``run.clock`` start), or None before any."""
        return self.marks[-1][0] if self.marks else None

    def t_s(self, epoch: float) -> float:
        """Run time of wall time ``epoch``. Before the first start: measured from it (negative)."""
        if not self.marks:
            raise ValueError("no run.clock")
        i = 0
        for j, (start, off) in enumerate(self.marks):
            if start + off <= epoch + 0.5:
                i = j
        t = epoch - self.marks[i][0]
        if i + 1 < len(self.marks):
            t = min(t, self.marks[i + 1][1])
        return t


def run_time(origin: float | RunClock, epoch: float) -> float:
    """``epoch`` on the run clock: ``origin`` is a RunClock, or a plain start epoch (a run never resumed)."""
    return origin.t_s(epoch) if isinstance(origin, RunClock) else epoch - origin


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)
