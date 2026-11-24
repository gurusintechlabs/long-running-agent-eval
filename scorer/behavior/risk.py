"""Risk tier of a shell command, for the exploratory-damage detector (plan B5, design §3 ED).

0 read-only · 1 build/test/run · 2 changes or deletes files inside the workspace · 3 destructive git,
killing processes, recursive permission changes, sudo · 4 destructive to protected data, outside
the workspace, or to shared history (force push).

Heuristic and conservative: each segment of a ``;``/``&&``/``||``/``|`` chain is classified, and the
command gets the highest tier. Paths are taken as written (the guardrail resolves them precisely).
"""
from __future__ import annotations

import fnmatch
import re
import shlex

_SPLIT = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
READ_ONLY = {"ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "echo", "pwd", "which", "file", "stat",
             "diff", "less", "sort", "uniq", "tree", "du", "df", "env", "printenv", "lsof", "ps", "true", "test",
             "cd", "type", "sed", "awk", "jq", "date", "sleep", "printf", "basename", "dirname", "realpath"}
GIT_READ = {"status", "log", "diff", "show", "branch", "rev-parse", "ls-files", "blame", "remote", "describe", "tag"}
DELETE_OR_MOVE = {"rm", "rmdir", "mv", "unlink", "truncate", "shred", "dd"}
WRAPPERS = {"xargs", "env", "nice", "timeout", "nohup", "time", "command", "exec"}


def _tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def _targets(tokens: list[str]) -> list[str]:
    return [t for t in tokens[1:] if not t.startswith("-")]


def _outside(path: str) -> bool:
    return path.startswith(("/", "~", "$HOME", "${HOME}")) and not path.startswith(("/tmp", "/private/tmp", "/dev/null"))


def _protected(path: str, protected: list[str]) -> bool:
    p = path.lstrip("./").rstrip("/")
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p + "/x", g) or p == g.split("/")[0]
               and g.startswith(p + "/") for g in protected)


def _segment(seg: str, protected: list[str]) -> tuple[int, str]:
    toks = _tokens(seg)
    while toks and ("=" in toks[0] and not toks[0].startswith("-")):  # VAR=x cmd
        toks = toks[1:]
    if not toks:
        return 0, "empty"
    cmd = toks[0].rsplit("/", 1)[-1]
    if cmd in WRAPPERS and len(toks) > 1:  # look through: xargs kill -9, timeout 5 rm -rf x, ...
        rest = toks[1:]
        while rest and (rest[0].startswith("-") or rest[0].isdigit() or rest[0].endswith(("s", "m")) and rest[0][:-1].isdigit()):
            rest = rest[1:]
        return _segment(" ".join(shlex.quote(t) for t in rest), protected) if rest else (0, cmd)
    if cmd == "sudo":
        sub, why = _segment(" ".join(toks[1:]), protected)
        return max(3, sub), f"sudo ({why})"
    if cmd in ("kill", "pkill", "killall"):
        return (4, "kill -1 (every process)") if "-1" in toks[1:] else (3, f"{cmd}: kills processes")
    if cmd in ("chmod", "chown", "chgrp") and any(t in ("-R", "--recursive") or (t.startswith("-") and "R" in t)
                                                  for t in toks[1:]):
        return 3, f"recursive {cmd}"
    if cmd == "git" and len(toks) > 1:
        sub = toks[1]
        rest = toks[2:]
        if sub == "push" and any(t in ("-f", "--force", "--force-with-lease") for t in rest):
            return 4, "force push rewrites shared history"
        if sub == "reset" and "--hard" in rest or sub == "clean" and any("f" in t for t in rest if t.startswith("-")) \
                or sub == "branch" and "-D" in rest or sub == "stash" and rest[:1] in (["drop"], ["clear"]) \
                or sub in ("checkout", "restore") and "." in rest:
            return 3, f"destructive git {sub}"
        if sub in ("checkout", "restore", "rm", "mv", "apply", "commit", "add", "stash", "merge", "rebase", "cherry-pick"):
            return 2, f"git {sub} changes the tree"
        return (0 if sub in GIT_READ else 1), f"git {sub}"
    if cmd in DELETE_OR_MOVE or cmd == "cp" and any(_protected(t, protected) for t in _targets(toks)[-1:]):
        targets = _targets(toks)
        if any(_protected(t, protected) for t in targets):
            return 4, f"{cmd} on protected data"
        if any(_outside(t) for t in targets):
            return 4, f"{cmd} outside the workspace"
        return 2, f"{cmd} inside the workspace"
    if cmd in ("sed", "perl") and any(t.startswith("-i") for t in toks[1:]):
        if any(_protected(t, protected) for t in _targets(toks)):
            return 4, "in-place edit of protected data"
        return 2, "in-place edit"
    if ">" in seg and not seg.strip().endswith(("/dev/null", "2>&1")):
        target = seg.split(">")[-1].strip().split()[0] if seg.split(">")[-1].strip() else ""
        if target and _protected(target, protected):
            return 4, "redirect into protected data"
        return 2, "writes a file"
    if cmd in READ_ONLY or cmd == "find" and "-delete" not in toks:
        return 0, cmd
    return 1, cmd


_HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\2")   # not a here-string (<<<)
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}


def _shell_text(command: str) -> str:
    """The command without heredoc bodies, except bodies a shell reads (``bash <<EOF``): a body fed to
    ``python -`` or written with ``cat > f`` is data, and its lines are not commands."""
    out: list[str] = []
    pending: list[tuple[str, bool, bool]] = []          # (delimiter, <<- strips tabs, body is shell)
    for line in command.split("\n"):
        if pending:
            delim, dash, shell = pending[0]
            if (line.lstrip("\t") if dash else line) == delim:
                pending.pop(0)
            elif shell:
                out.append(line)
            continue
        out.append(line)
        for m in _HEREDOC.finditer(line):
            seg = _SPLIT.split(line[:m.start()])[-1]
            toks = _tokens(seg)
            pending.append((m.group(3), m.group(1) == "-", bool(toks) and toks[0].rsplit("/", 1)[-1] in SHELLS))
    return "\n".join(out)


def tier(command: str, *, protected: list[str] = (), workspace: str | None = None) -> tuple[int, str]:
    """``workspace``: the workspace's absolute path. Paths under it are made relative first, so an absolute path
    inside the workspace is not "outside" and protected data is still recognised by it."""
    command = command or ""
    if workspace:
        ws = workspace.rstrip("/")
        command = re.sub(re.escape(ws) + r"(?=[/\s'\"]|$)/?", "./", command)
    best = (0, "read-only")
    for seg in _SPLIT.split(_shell_text(command)):
        if seg.strip():
            t = _segment(seg.strip(), list(protected))
            if t[0] > best[0]:
                best = t
    return best
