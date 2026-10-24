"""``lrae ui``: stdlib-only so ``runner/cli.py`` can register it without the server dependencies."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

DEFAULT_PORT = 8765


def new_token() -> str:
    return secrets.token_urlsafe(32)


def launch_url(port: int, token: str) -> str:
    """The token goes in the fragment: browsers never send it to the server or put it in logs."""
    return f"http://127.0.0.1:{port}/#token={token}"


def cmd_ui(a) -> int:
    try:
        import uvicorn

        from ui_server.app import create_app
        from ui_server.settings import Settings
    except ImportError as exc:
        print(f"lrae ui needs the 'ui' extra (pip install -e '.[ui]'): {exc}", file=sys.stderr)
        return 2
    repo = Path(a.repo_root).resolve()
    runs_dir = Path(a.runs_dir).resolve() if a.runs_dir else repo / "runs"
    token = new_token()
    settings = Settings(repo_root=repo, runs_dir=runs_dir, token=token, port=a.port,
                        web_dist=repo / "ui" / "web" / "dist")
    url = launch_url(a.port, token)
    print(f"LRAE UI on {url}\n(local only; the token is new on every start)")
    if a.open:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=a.port, log_level="warning")
    return 0


def add_parsers(sp) -> None:
    u = sp.add_parser("ui", help="serve the local management UI on 127.0.0.1")
    u.add_argument("--port", type=int, default=DEFAULT_PORT)
    u.add_argument("--runs-dir", default=None, help="default: <repo>/runs")
    u.add_argument("--open", dest="open", action="store_true", help="open the browser")
    u.add_argument("--no-open", dest="open", action="store_false")
    u.set_defaults(func=cmd_ui, open=False)
