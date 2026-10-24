"""Checkpoint diff (from the run's mirror.git) and scorer log (U3)."""
from __future__ import annotations

import os

from fastapi import HTTPException, Query

from ui_server import gitview, safefs, store
from ui_server.deps import run_dir_or_404

LOG_DEFAULT, LOG_MAX = 200_000, 2_000_000


def register(app, settings) -> None:
    def checkpoint(rd, k: int) -> dict:
        cps = store.orchestrator_info(rd)["checkpoints"]
        if k not in cps:
            raise HTTPException(404, "no such checkpoint")
        return cps

    @app.get("/api/runs/{rid}/checkpoints/{k}/diff")
    def diff(rid: str, k: int, base: str | None = Query(None, max_length=64),
             max_bytes: int = Query(gitview.DEFAULT_DIFF_BYTES, ge=1000)):
        rd = run_dir_or_404(settings, rid)
        cps = checkpoint(rd, k)
        head = cps[k].get("head_sha")
        out = {"run_id": rid, "k": k, "head": head, "dirty": cps[k].get("dirty"), "base": None, "base_kind": None,
               "available": False,
               "reason": None, "commits": [], "commits_truncated": False, "files": [], "files_truncated": False,
               "diff": "", "diff_truncated": False}
        if base is not None and not gitview.valid_sha(base):
            raise HTTPException(400, "base must be a 40-character lowercase hex sha")
        repo, why = gitview.mirror_check(rd)
        if repo is None:
            out["reason"] = why
            return out
        if not gitview.valid_sha(head):
            out["reason"] = "the checkpoint has no valid head sha"
            return out
        try:
            if not gitview.has_commit(repo, head):
                out["reason"] = "the head commit is not in mirror.git"
                return out
            if base is not None:
                kind, bsha = "param", base
            else:
                prev = [c for c in cps if c < k and gitview.valid_sha(cps[c].get("head_sha"))]
                if prev:
                    kind, bsha = "previous_checkpoint", cps[max(prev)]["head_sha"]
                else:
                    mf = store.read_json(rd / "manifest.json") or {}
                    seed = mf.get("seed_commit")
                    kind, bsha = ("seed", seed) if gitview.valid_sha(seed) else ("root", None)
            if bsha is not None and not gitview.has_commit(repo, bsha):
                if base is not None:
                    raise HTTPException(404, "base commit is not in mirror.git")
                kind, bsha = "root", None
            out.update(base=bsha, base_kind=kind, available=True)
            tree_base = bsha or gitview.EMPTY_TREE
            out["commits"], out["commits_truncated"] = gitview.commits(repo, bsha, head)
            out["files"], out["files_truncated"] = gitview.numstat(repo, tree_base, head)
            out["diff"], out["diff_truncated"] = gitview.diff_text(repo, tree_base, head, max_bytes)
        except gitview.GitError as e:
            out.update(available=False, reason=str(e))
        return out

    @app.get("/api/runs/{rid}/checkpoints/{k}/scorer-log")
    def scorer_log(rid: str, k: int, max_bytes: int = Query(LOG_DEFAULT, ge=1000, le=LOG_MAX)):
        rd = run_dir_or_404(settings, rid)
        if k < 1 or k > 100000:
            raise HTTPException(404, "no such checkpoint")
        with safefs.open_file(rd / "scorer" / f"score-t{int(k)}.log") as fh:   # no symlink anywhere below rd
            if fh is None:
                raise HTTPException(404, "no scorer log")
            size = os.fstat(fh.fileno()).st_size
            if size > max_bytes:
                fh.seek(size - max_bytes)
            raw = fh.read(max_bytes)
        text = raw.decode("utf-8", "replace").replace("\x00", "�")
        return {"run_id": rid, "k": k, "size": size, "truncated": size > max_bytes,
                "text": text if size <= max_bytes else "…[earlier output cut]\n" + text}
