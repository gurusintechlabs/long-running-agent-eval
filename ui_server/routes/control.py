"""Phase U5 endpoints: launch (with the spend gate), stop, kill, resume, re-score, clean, state.

Every write goes through the global token + host/origin middleware. All spawning is delegated to
``ui_server.control_core.Control`` which runs the real ``lrae`` CLI (one code path)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from spec.loader import SpecError, load_spec
from ui_server import control_core as cc
from ui_server import spend, store
from ui_server.deps import run_dir_or_404
from ui_server.safety import scrub_paths
from ui_server.settings import Settings


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewBody(_Body):
    spec_path: str | None = None
    draft: str | None = None
    config: str | list[str] | None = None
    repeat: int | list[int] | None = None


class LaunchBody(_Body):
    nonce: str
    confirm_usd: float | str | None = None
    confirm_runs: int | None = None


class ResumePreviewBody(_Body):
    from_: str = Field(alias="from")


class ResumeBody(_Body):
    from_: str = Field(alias="from")
    nonce: str
    confirm_usd: float | str | None = None
    confirm_runs: int | None = None


class KillBody(_Body):
    confirm: str


class ScoreBody(_Body):
    checkpoint: int | None = None


def register(app: FastAPI, settings: Settings) -> None:
    ctl = cc.Control(cc.ControlConfig.from_settings(settings))
    app.state.control = ctl   # tests swap fields of ``ctl.cfg`` (spawner, spec roots, extra argv)
    home = Path.home()

    def C() -> cc.Control:
        return app.state.control

    @app.exception_handler(cc.ControlError)
    async def _control_error(_request, exc: cc.ControlError):
        body = {"code": exc.code, "message": exc.message, **exc.extra}
        return JSONResponse({"detail": scrub_paths(body, settings.repo_root, home)}, status_code=exc.status)

    def _load(real: Path):
        try:
            return load_spec(real, repo_root=settings.repo_root)
        except SpecError as exc:
            raise cc.ControlError(422, "spec_invalid", str(exc)[:2000]) from None

    def _checks(loaded, conflicts: list[str]) -> list[dict]:
        checks = [{"name": "spec validates (lrae validate)", "ok": True, "detail": loaded.spec_hash[:12]},
                  {"name": "no existing run folder for these run ids", "ok": not conflicts,
                   "detail": ", ".join(conflicts)}]
        if loaded.spec.agent.runtime == "claude_code":
            found = cc.which_claude()
            checks.append({"name": "claude binary on PATH (not executed)", "ok": bool(found), "detail": ""})
        return checks

    def _confirmation(est: dict) -> dict:
        if not est["real_spend"]:
            return {"required": False}
        return {"required": True, "fields": {"confirm_usd": est["max_spend_usd"], "confirm_runs": est["run_count"]},
                "message": "This uses the Claude subscription. Type the spend cap and the run count to confirm."}

    def _issue(kind: str, est: dict, real: Path, argv_tail: list[str], checks, conflicts, meta=None) -> dict:
        blockers = [f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]]
        act = C().active()
        info = [f"a harness process is alive (run {act[0]['run_id']}); launching is refused until it ends"] if act else []
        out = {"estimate": est, "checks": checks, "conflicts": conflicts, "blockers": blockers,
               "warnings": info, "launch_allowed_now": not act, "confirmation": _confirmation(est),
               "confirmation_nonce": None, "expires_in_s": None}
        if not blockers:
            rec = cc.NonceRecord(kind=kind, bound=est, spec_file=real, expires=C().cfg.clock() + C().cfg.nonce_ttl_s,
                                 argv_tail=argv_tail, meta=meta or {})
            out["confirmation_nonce"] = C().nonces.issue(rec)
            out["expires_in_s"] = C().cfg.nonce_ttl_s
        return scrub_paths(out, settings.repo_root, home)

    # -- launch --------------------------------------------------------------------------------
    @app.post("/api/launch/preview")
    def launch_preview(body: PreviewBody):
        real = cc.resolve_spec_path(C().cfg.spec_roots, C().cfg.repo_root, body.spec_path, body.draft)
        loaded = _load(real)
        est = cc.compute_estimate(loaded, C().cfg.repo_root, configs=body.config, repeats=body.repeat)
        est["kind"] = "launch"
        est["spec_path"] = cc._rel(C().cfg.repo_root, real)
        conflicts = cc.existing_conflicts(loaded, C().cfg.repo_root, est["run_ids"])
        argv_tail = ["run", str(real)]
        for c in est["configs"]:
            argv_tail += ["--config", c]
        for r in est["repeats"]:
            argv_tail += ["--repeat", str(r)]
        return _issue("launch", est, real, argv_tail, _checks(loaded, conflicts), conflicts)

    @app.post("/api/launch")
    def launch(body: LaunchBody):
        res = C().start_run_job(body.nonce, "launch", body.confirm_usd, body.confirm_runs)
        return JSONResponse(res, status_code=200 if res["manifest_seen"] else 202)

    # -- resume --------------------------------------------------------------------------------
    def _resume_ref(rid: str):
        d = run_dir_or_404(settings, rid)
        m = store.read_json(d / "manifest.json") or {}
        sp = m.get("spec_path")
        if not isinstance(sp, str):
            raise cc.ControlError(422, "spec_not_found", "the run's manifest has no spec_path")
        real = cc.resolve_spec_path(C().cfg.spec_roots, C().cfg.repo_root, sp, None)
        return m, real

    @app.post("/api/runs/{rid}/resume/preview")
    def resume_preview(rid: str, body: ResumePreviewBody):
        m, real = _resume_ref(rid)
        k = cc.parse_from(body.from_)
        loaded = _load(real)
        est = cc.resume_estimate(C().cfg, loaded, rid, k)
        checks = [{"name": "spec hash equals the run's", "ok": True, "detail": loaded.spec_hash[:12]},
                  {"name": f"snapshot t{k} exists", "ok": True, "detail": ""}]
        if loaded.spec.agent.runtime == "claude_code":
            checks.append({"name": "claude binary on PATH (not executed)", "ok": bool(cc.which_claude()), "detail": ""})
        return _issue("resume", est, real, ["resume", rid, "--from", f"t{k}"], checks, [],
                      meta={"run_id": rid, "from_k": k})

    @app.post("/api/runs/{rid}/resume")
    def resume(rid: str, body: ResumeBody):
        _resume_ref(rid)
        k = cc.parse_from(body.from_)
        rec = C().nonces.peek(body.nonce, "resume")
        if rec.meta.get("run_id") != rid or rec.meta.get("from_k") != k:
            raise cc.ControlError(400, "nonce_invalid", "this nonce was issued for a different run or checkpoint")
        res = C().start_run_job(body.nonce, "resume", body.confirm_usd, body.confirm_runs)
        return JSONResponse(res, status_code=200 if res["manifest_seen"] else 202)

    # -- stop / kill ---------------------------------------------------------------------------
    @app.post("/api/runs/{rid}/stop")
    def stop(rid: str):
        d = run_dir_or_404(settings, rid)
        return C().stop(rid, store.read_json(d / "manifest.json") or {})

    @app.post("/api/runs/{rid}/kill")
    def kill(rid: str, body: KillBody):
        d = run_dir_or_404(settings, rid)
        if body.confirm != rid:
            raise cc.ControlError(422, "confirmation_mismatch", "set confirm to the run id to hard-kill it")
        return C().kill(rid, store.read_json(d / "manifest.json") or {})

    # -- score / clean -------------------------------------------------------------------------
    @app.post("/api/runs/{rid}/score")
    def score(rid: str, body: ScoreBody | None = None):
        d = run_dir_or_404(settings, rid)
        m = store.read_json(d / "manifest.json") or {}
        k = body.checkpoint if body else None
        if k is not None and k < 1:
            raise cc.ControlError(422, "bad_checkpoint", "checkpoint must be >= 1")
        sp = m.get("spec_path")
        if not isinstance(sp, str):
            raise cc.ControlError(422, "spec_invalid", "the run's manifest has no spec_path")
        real = cc.resolve_spec_path(C().cfg.spec_roots, C().cfg.repo_root, sp, None)
        try:
            reasons = spend.spend_reasons(load_spec(real, repo_root=settings.repo_root).spec)
        except (SpecError, OSError, TypeError):
            raise cc.ControlError(422, "spec_invalid", "the run's spec does not load") from None
        if reasons:
            raise cc.ControlError(
                409, "judge_spends", "re-scoring would spend (" + "; ".join(reasons) + "); "
                "run `lrae score <run> --confirm-spend` in a terminal")
        tail = ["score", rid] + (["--checkpoint", str(k)] if k else [])
        return JSONResponse(C().start_simple_job("score", tail, wait_s=2.0), status_code=202)

    @app.post("/api/clean")
    def clean():
        res = C().start_simple_job("clean", ["clean"], wait_s=60.0)
        return JSONResponse(scrub_paths(res, settings.repo_root, home), status_code=200 if res["finished"] else 202)

    # -- state ---------------------------------------------------------------------------------
    @app.get("/api/control/state")
    def control_state():
        return scrub_paths(C().state(), settings.repo_root, home)

