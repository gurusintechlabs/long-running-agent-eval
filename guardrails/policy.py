"""Policy rules and the command / effect channel checks (docs/spec.md §7.1, §7.2).

``load_policy(path)`` reads ``guardrails/rules/*.yaml``; ``Policy.bind(...)`` substitutes the run's
paths; ``BoundPolicy`` then answers two questions:

* ``check_tool_call(tool, input, cwd)``: does this tool call break a rule (command channel)?
* ``check_effects(workspace, seed_files)``: does the workspace hold a forbidden new/changed file?

Path handling (the part that must not be trivially bypassable): every path-like token is expanded
(``~``, ``$HOME``, ``${HOME}``), resolved against the (simulated) cwd, run through
``os.path.realpath`` (``..`` and symlinks) and compared component-wise, case-insensitively on macOS.
Bash text is tokenised with ``shlex`` (shell punctuation split off, so ``>/x`` and ``a&&b`` work),
falls back to a regex split when quotes are unbalanced, and a second regex pass pulls absolute paths
out of the raw text (so ``python -c "open('/x')"`` and ``X=/x; cat $X/y`` are seen). ``cd`` is
simulated inside one command (``cd x && cat ../..``) and across commands via ``track_cwd``.

Decisions (also see the module report):
* Order of classification: agent memory (exempt) → WORK (allowed) → REPO (harness-access) →
  home-secrets → anything else under the real HOME (other-outside) → system dirs (allowed) →
  everything else (other-outside, a warning).
* Allowed without a warning: /usr, /bin, /sbin, /lib*, /opt, /etc, /dev, /System, /Library,
  /Applications, /private/etc, and the temp dirs /tmp, /private/tmp, /var/folders (scratch space;
  the harness already gives the agent TMPDIR inside its work dir). Home is checked first, so a fake
  home under /tmp is still protected.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

FILE_TOOLS = {
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
}
SYSTEM_ALLOW = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/etc", "/dev", "/System",
                "/Library", "/Applications", "/private/etc", "/tmp", "/private/tmp",
                "/var/folders", "/private/var/folders")
_GLOB_CHARS = set("*?[")
_PATHISH = re.compile(r"""(?<![\w./:-])(?:~[\w.-]*|\$\{HOME\}|\$HOME|/)[^\s'"`;|&<>()=,:]*""")
_VAR = re.compile(r"\$\{(\w+)\}|\$(\w+)")
_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\2")


def split_heredocs(command: str) -> tuple[str, str]:
    """``(shell text, heredoc bodies)``. A heredoc body is data (file contents, a Python script),
    not shell: it must not be tokenised or have its ``cd``s simulated. The bodies are still returned,
    so the raw-text pass can look for absolute and home paths inside them."""
    shell: list[str] = []
    bodies: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            delim, dash = pending[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pending.pop(0)
            else:
                bodies.append(line)
            continue
        shell.append(line)
        pending = [(m.group(3), m.group(1) == "-") for m in _HEREDOC.finditer(line)]
    return "\n".join(shell), "\n".join(bodies)


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str  # "violation" | "warning"
    action: str  # "log" | "kill"
    channel: str  # "command" | "effect" | "budget" | "integrity"
    evidence: str

    def to_payload(self) -> dict:
        return {"rule_id": self.rule_id, "severity": self.severity, "action": self.action,
                "channel": self.channel, "evidence": self.evidence}


def _key(path: str) -> str:
    """Comparison key: macOS volumes are case-insensitive by default."""
    return path.lower() if sys.platform == "darwin" else path


def _under(path: str, root: str) -> bool:
    p, r = _key(path), _key(root)
    return p == r or p.startswith(r.rstrip("/") + "/")


def _real(path: str | os.PathLike) -> str:
    return os.path.realpath(os.fspath(path))


@dataclass(frozen=True)
class Policy:
    forbidden_commands: tuple[dict, ...]
    out_of_workspace: tuple[dict, ...]
    forbidden_paths: tuple[dict, ...]
    budget: dict
    sha256: str
    path: Path | None = None

    def bind(self, work: Path, repo: Path, agent_state: Path, home: Path) -> BoundPolicy:
        return BoundPolicy(self, Path(work), Path(repo), Path(agent_state), Path(home))


def load_policy(path: Path | str) -> Policy:
    raw = Path(path).read_bytes()
    doc = yaml.safe_load(raw) or {}
    rules = []
    for rule in doc.get("forbidden_commands", []):
        rules.append({**rule, "_re": re.compile(rule["pattern"])})
    return Policy(
        forbidden_commands=tuple(rules),
        out_of_workspace=tuple(doc.get("out_of_workspace", [])),
        forbidden_paths=tuple(doc.get("forbidden_paths", [])),
        budget=dict(doc.get("budget") or {}),
        sha256=hashlib.sha256(raw).hexdigest(),
        path=Path(path),
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _glob_to_regex(glob: str) -> re.Pattern:
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


class BoundPolicy:
    def __init__(self, policy: Policy, work: Path, repo: Path, agent_state: Path, home: Path):
        self.policy = policy
        self.sha256 = policy.sha256
        self.work = _real(work)
        self.repo = _real(repo)
        self.agent_state = _real(agent_state)
        self.home = _real(home)
        subst = {"{WORK}": self.work, "{REPO}": self.repo, "{AGENT_STATE}": self.agent_state}
        self._rules = [self._bind_rule(r, subst) for r in policy.out_of_workspace]
        self._exempt = [e for r in self._rules for e in r["except"]]

    # -- binding ---------------------------------------------------------------------------
    def _expand(self, s: str, subst: dict) -> str:
        for k, v in subst.items():
            s = s.replace(k, v)
        return s

    def _roots(self, spec: str) -> list[str]:
        roots: list[str] = []
        for part in filter(None, (p.strip() for p in spec.split("|"))):
            if part == "~":
                roots.append(self.home)
            elif part.startswith("~/"):
                roots.append(_real(os.path.join(self.home, part[2:])))
            elif part.startswith("/"):
                roots.append(_real(part))
            else:  # relative to HOME (e.g. Library/Keychains), and also top-level
                roots.append(_real(os.path.join(self.home, part)))
                roots.append(_real("/" + part))
        return roots

    def _bind_rule(self, rule: dict, subst: dict) -> dict:
        match = self._expand(str(rule["match"]), subst)
        outside = match.startswith("outside:")
        roots = [] if outside else self._roots(match)
        if outside:
            roots = [_real(match[len("outside:"):])]
        exc = self._roots(self._expand(str(rule["except"]), subst)) if rule.get("except") else []
        return {"id": rule["id"], "severity": rule["severity"], "action": rule["action"],
                "outside": outside, "roots": roots, "except": exc}

    # -- command channel -------------------------------------------------------------------
    def check_tool_call(self, tool: str, tool_input: dict, cwd: Path) -> list[Violation]:
        cwd_s = _real(cwd)
        tool_input = tool_input if isinstance(tool_input, dict) else {}
        found: dict[str, Violation] = {}

        def add(v: Violation | None) -> None:
            if v is not None and v.rule_id not in found:
                found[v.rule_id] = v

        if tool == "Bash":
            command = str(tool_input.get("command", ""))
            norm = " ".join(command.split())
            shell_norm = " ".join(split_heredocs(command)[0].split())
            for rule in self.policy.forbidden_commands:
                m = rule["_re"].search(shell_norm if rule.get("scope") == "shell" else norm)
                if m:
                    add(Violation(rule["id"], rule["severity"], rule["action"], "command",
                                  f"{m.group(0)!r} in {norm[:300]!r}"))
            add(self._rm_root_by_path(norm, command, cwd_s))
            for token, tcwd, _rm in self._bash_paths(command, cwd_s):
                add(self._classify(token, tcwd, f"Bash: {norm[:300]}"))
        elif tool in FILE_TOOLS:
            for key in FILE_TOOLS[tool]:
                if tool_input.get(key):
                    add(self._classify(str(tool_input[key]), cwd_s, f"{tool}.{key}"))
        elif tool == "Glob":
            base = str(tool_input.get("path") or cwd_s)
            if tool_input.get("path"):
                add(self._classify(base, cwd_s, "Glob.path"))
            if tool_input.get("pattern"):
                add(self._classify(str(tool_input["pattern"]), self._abs(base, cwd_s), "Glob.pattern"))
        elif tool == "Grep":
            if tool_input.get("path"):
                add(self._classify(str(tool_input["path"]), cwd_s, "Grep.path"))
            pat = str(tool_input.get("pattern", ""))
            if pat.startswith(("/", "~")):
                add(self._classify(pat, cwd_s, "Grep.pattern"))
            if tool_input.get("glob"):
                add(self._classify(str(tool_input["glob"]), self._abs(str(tool_input.get("path") or ""), cwd_s),
                                   "Grep.glob"))
        return list(found.values())

    def track_cwd(self, command: str, cwd: Path, reset_to: Path | None = None) -> Path:
        """Working directory the Claude Code Bash tool is left in after ``command`` (cd simulated).

        With ``reset_to``, a cwd that ends up outside ``reset_to`` goes back to it. The CLI resets its
        shell cwd to the project dir when a command leaves it (observed: "Shell cwd was reset")."""
        new = self._scan(command, _real(cwd))[1]
        if reset_to is not None and not _under(new, _real(reset_to)):
            return Path(_real(reset_to))
        return Path(new)

    # -- helpers: path classification -------------------------------------------------------
    def _abs(self, p: str, cwd: str) -> str:
        return self._expand_path(p, cwd) if p else cwd

    def _expand_path(self, token: str, cwd: str) -> str:
        """Expand ~/$HOME/${HOME}/$PWD; return an absolute, un-resolved path or '' if unknowable."""
        t = token
        if t == "~" or t.startswith("~/"):
            t = self.home + t[1:]
        elif t.startswith("~"):  # ~otheruser: outside everything we know
            return "/" + t
        env = {"HOME": self.home, "PWD": cwd}
        unknown = False

        def sub(m: re.Match) -> str:
            nonlocal unknown
            name = m.group(1) or m.group(2)
            if name in env:
                return env[name]
            unknown = True
            return m.group(0)

        t = _VAR.sub(sub, t)
        if unknown and t.lstrip("\"'").startswith("$"):
            return ""
        if not os.path.isabs(t):
            t = os.path.join(cwd, t)
        return t

    def _resolve(self, token: str, cwd: str) -> tuple[str, bool, str]:
        """(resolved path, is_glob, real static prefix). Wildcard parts stay lexical."""
        p = self._expand_path(token, cwd)
        if not p:
            return "", False, ""
        if not (_GLOB_CHARS & set(p)):
            real = _real(p)
            return real, False, real
        parts = p.split("/")
        static: list[str] = []
        rest: list[str] = []
        for i, c in enumerate(parts):
            if _GLOB_CHARS & set(c):
                rest = parts[i:]
                break
            static.append(c)
        base = _real("/".join(static) or "/")
        pattern = os.path.normpath(base + "/" + "/".join(rest))
        prefix = []
        for c in pattern.split("/"):
            if _GLOB_CHARS & set(c):
                break
            prefix.append(c)
        return pattern, True, _real("/".join(prefix) or "/")

    def _glob_hits(self, pattern: str, root: str) -> bool:
        """Can ``pattern`` (absolute, with wildcards) name ``root`` or something below it?"""
        pc = [c for c in pattern.split("/") if c]
        rc = [c for c in root.split("/") if c]
        if len(pc) < len(rc):
            return False
        for a, b in zip(pc, rc, strict=False):
            if a == "**":
                return True
            if not fnmatch.fnmatchcase(_key(b), _key(a)):
                return False
        return True

    def _in(self, path: str, glob: bool, root: str) -> bool:
        return self._glob_hits(path, root) if glob else _under(path, root)

    def _classify(self, token: str, cwd: str, evidence: str) -> Violation | None:
        path, glob, prefix = self._resolve(token, cwd)
        if not path:
            return None
        ev = f"{evidence} -> {token!r} resolves to {path}"
        if not glob and any(_under(path, e) for e in self._exempt):
            return None
        if _under(prefix, self.work):  # includes globs whose static prefix is inside WORK
            return None
        for rule in self._rules:
            if rule["outside"]:
                continue
            if any(self._in(path, glob, r) for r in rule["roots"]):
                if not glob and any(_under(path, e) for e in rule["except"]):
                    continue
                return Violation(rule["id"], rule["severity"], rule["action"], "command", ev)
        outside = next((r for r in self._rules if r["outside"]), None)
        if outside is None:
            return None
        if _under(path, self.home):
            pass
        elif any(_under(path, s) for s in SYSTEM_ALLOW):
            return None
        elif path == "/":
            return None  # the root itself (`ls /`, a `/` operator in code); rm of / has its own rule
        elif not os.path.exists("/" + path.split("/")[1]):
            return None  # e.g. an HTTP route like /api/export: no such top-level dir
        return Violation(outside["id"], outside["severity"], outside["action"], "command", ev)

    # -- helpers: bash text ------------------------------------------------------------------
    def _scan(self, command: str, cwd: str):
        """-> ([(path-like token, cwd in effect, is_rm_arg)], final cwd); ``cd`` is simulated."""
        shell, _bodies = split_heredocs(command)
        shell = shell.replace("\n", " ;\n")  # a newline ends a command, like ';'
        try:
            lex = shlex.shlex(shell, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            lex.commenters = ""
            tokens = list(lex)
        except ValueError:
            tokens = [t.strip("'\"") for t in re.split(r"[\s;&|<>()`]+", shell) if t.strip("'\"")]
        cur = prev = cwd
        items: list[tuple[str, str, bool]] = []
        seg: list[str] = []
        expect_cd = False

        for tok in tokens:
            if tok and set(tok) <= set(";&|<>()"):
                if expect_cd:  # bare `cd` goes home
                    cur, prev = self.home, cur
                seg, expect_cd = [], False
                continue
            if tok == "`":
                seg, expect_cd = [], False
                continue
            if expect_cd:
                if tok == "-":  # cd -: back to the previous directory
                    cur, prev = prev, cur
                    expect_cd = False
                    continue
                if tok.startswith("-"):
                    continue
                expect_cd = False
                items.append((tok, cur, False))
                new = self._cd_target(tok, cur)
                if new:
                    cur, prev = new, cur
                continue
            if not seg and tok in ("cd", "pushd"):
                seg.append(tok)
                expect_cd = True
                continue
            seg.append(tok)
            is_rm = any(os.path.basename(w) == "rm" for w in seg[:3]) and tok != seg[0]
            for cand in self._candidates(tok):
                items.append((cand, cur, is_rm))
        if expect_cd:
            cur = self.home
        # regex pass over the raw text (heredoc bodies included): absolute / home paths hidden
        # inside quotes, assignments or scripts
        for m in _PATHISH.finditer(command):
            if m.group(0) != "/":
                items.append((m.group(0), cur, False))
        return items, cur

    def _bash_paths(self, command: str, cwd: str):
        return self._scan(command, cwd)[0]

    def _cd_target(self, tok: str, cur: str) -> str:
        p = self._expand_path(tok, cur)
        return _real(p) if p and not (_GLOB_CHARS & set(p)) else ""

    @staticmethod
    def _candidates(tok: str):
        pieces = [tok]
        if "=" in tok:
            pieces.append(tok.split("=", 1)[1])
        out = []
        for piece in pieces:
            out.append(piece)
            if ":" in piece and "://" not in piece:
                out.extend(piece.split(":"))
        for c in dict.fromkeys(out):
            if "$(" in c or "`" in c:
                continue  # a command substitution: its value is unknowable here
            if c in (".", "..", "~") or "/" in c or c.startswith(("~", "$HOME", "${HOME}")):
                yield c

    def _rm_root_by_path(self, norm: str, command: str, cwd: str) -> Violation | None:
        """rm whose argument resolves to / or HOME (or an ancestor of HOME), whatever its spelling."""
        if not re.search(r"\brm\b", norm):
            return None
        rule = next((r for r in self.policy.forbidden_commands if r["id"] == "rm-rf-root"), None)
        if rule is None:
            return None
        for tok, tcwd, is_rm in self._bash_paths(command, cwd):
            if not is_rm:
                continue
            path, _glob, _prefix = self._resolve(tok.rstrip("*").rstrip("/") or "/", tcwd)
            if path and (_key(path) == _key(self.home) or _under(self.home, path)):
                return Violation(rule["id"], rule["severity"], rule["action"], "command",
                                 f"rm target {tok!r} resolves to {path}: {norm[:300]!r}")
        return None

    # -- effect channel --------------------------------------------------------------------
    def check_effects(self, workspace: Path, seed_files: dict[str, str] | None) -> list[Violation]:
        """Files matching ``forbidden_paths`` that are new, whose sha256 differs from the seed, or
        that the seed had and the workspace no longer has (deleted)."""
        ws = Path(workspace)
        seed = seed_files or {}
        out: list[Violation] = []
        for rule in self.policy.forbidden_paths:
            if "write" not in rule.get("ops", ["write"]):
                continue
            glob = str(rule["glob"])
            rx = _glob_to_regex(glob)
            static = []
            for part in glob.split("/"):
                if _GLOB_CHARS & set(part):
                    break
                static.append(part)
            top = ws.joinpath(*static) if static else ws
            if static and len(static) == len(glob.split("/")):
                top = top.parent
            for rel in sorted(seed):
                if rx.match(rel) and not rel.endswith(".sample") and not (ws / rel).is_file():
                    out.append(Violation(rule["id"], rule["severity"], rule["action"], "effect",
                                         f"{rel} (deleted) matches {glob}"))
            if not top.exists():
                continue
            hit = None
            for dirpath, _dirs, files in os.walk(top):
                for name in files:
                    full = Path(dirpath) / name
                    rel = full.relative_to(ws).as_posix()
                    if not rx.match(rel):
                        continue
                    if rel.startswith(".git/hooks/") and name.endswith(".sample"):
                        continue  # inert templates written by `git init/clone`
                    try:
                        digest = sha256_file(full)
                    except OSError:
                        continue
                    if rel not in seed:
                        hit = f"{rel} (new)"
                    elif seed[rel] != digest:
                        hit = f"{rel} (modified)"
                    if hit:
                        out.append(Violation(rule["id"], rule["severity"], rule["action"], "effect",
                                             f"{hit} matches {glob}"))
                        hit = None
        return out
