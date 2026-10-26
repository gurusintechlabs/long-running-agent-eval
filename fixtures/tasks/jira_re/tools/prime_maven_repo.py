#!/usr/bin/env python3
"""Fill the shared offline Maven repository for the jira-re rewrite (docs/jira-re-design.md §4).

    .venv/bin/python fixtures/tasks/jira_re/tools/prime_maven_repo.py [--dry-run]

Run after ``install_re_tools.sh`` and ``prepare_seed.py``, with network. Runs need no network: the
agent's ``build.sh`` runs Maven offline with this repository as a read-only tail
(``maven.repo.local.tail``).

1. Priming build (online), in a temp copy of the seed whose pom also declares the original plugin's
   non-test dependencies (from the pom embedded in its jar), so the rewrite can use the same APIs:
   ``mvn package`` (AMPS packaging, compiler, surefire and its JUnit provider) and
   ``dependency:go-offline``. Everything lands in ``<tools>/m2``.
2. Offline checks: a fresh copy of the seed, built exactly as the agent builds it (``sh build.sh``),
   must produce the plugin jar; the priming project must also build offline.
3. ``<tools>/m2`` is made read-only, and ``<tools>/m2.manifest`` lists every artifact with its SHA-256
   (resolver bookkeeping files with timestamps excluded). Its hash pins the repository (rule 4).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jira_target  # noqa: E402

DEPENDENCY_PLUGIN = "org.apache.maven.plugins:maven-dependency-plugin:3.8.1"
REPOSITORIES = ("https://maven.artifacts.atlassian.com/", "https://repo1.maven.org/maven2/")
BOOKKEEPING = ("_remote.repositories", "resolver-status.properties", "maven-metadata-local.xml")


def tools_dir() -> Path:
    return Path(os.environ.get("LRAE_RE_TOOLS") or Path.home() / "lrae-tools" / "re").expanduser()


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("$", " ".join(cmd), f"   (in {cwd})", flush=True)
    res = subprocess.run(cmd, cwd=cwd, env=env)
    if res.returncode != 0:
        raise SystemExit(f"failed ({res.returncode}): {' '.join(cmd)}")


def _url_exists(url: str) -> bool:
    """HEAD through curl (the system trust store; python.org builds of Python on macOS ship without
    root certificates). 2xx: exists; 404/410: missing; anything else, including TLS and network
    errors, raises, because "unreachable" must never read as "missing"."""
    res = subprocess.run(["curl", "-sIL", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30", url],
                         capture_output=True, text=True)
    code = res.stdout.strip()
    if res.returncode == 0 and code.startswith("2"):
        return True
    if res.returncode == 0 and code in ("404", "410"):
        return False
    raise RuntimeError(f"cannot reach {url}: curl exit {res.returncode}, HTTP {code or '-'}")


def available(deps: list[jira_target.Dep], *, exists=_url_exists) -> tuple[list[jira_target.Dep], list[str]]:
    """Split ``deps`` into those a public repository serves (by their ``.pom``) and those it does not
    (private or internal artifacts: not primed, reported)."""
    kept, dropped = [], []
    for d in deps:
        path = f"{d.group.replace('.', '/')}/{d.artifact}/{d.version}/{d.artifact}-{d.version}.pom"
        if any(exists(base + path) for base in REPOSITORIES):
            kept.append(d)
        else:
            dropped.append(d.coords)
    return kept, dropped


def priming_pom(seed_pom: str, deps: list[jira_target.Dep]) -> str:
    present = {line.strip() for line in seed_pom.splitlines()}
    extra = []
    for d in deps:
        if f"<artifactId>{d.artifact}</artifactId>" in present:
            continue
        type_line = f"\n            <type>{d.type}</type>" if d.type != "jar" else ""
        extra.append(f"""        <dependency>
            <groupId>{d.group}</groupId>
            <artifactId>{d.artifact}</artifactId>
            <version>{d.version}</version>{type_line}
            <scope>provided</scope>
        </dependency>
""")
    head, sep, tail = seed_pom.partition("    </dependencies>")
    if not sep:
        raise SystemExit("seed pom.xml has no </dependencies>")
    return head + "".join(extra) + sep + tail


def set_writable(root: Path, writable: bool) -> None:
    for p in [root, *root.rglob("*")]:
        if p.is_symlink():
            continue
        mode = p.stat().st_mode
        w = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        p.chmod((mode | stat.S_IWUSR) if writable else (mode & ~w))


def write_manifest(m2: Path, out: Path) -> str:
    lines = []
    for p in sorted(m2.rglob("*")):
        if p.is_file() and p.name not in BOOKKEEPING and not p.name.endswith(".lastUpdated"):
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(m2).as_posix()}")
    out.write_text("\n".join(lines) + "\n")
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="show what would be primed; run nothing")
    args = ap.parse_args()

    t = jira_target.load()
    seed_pom = (jira_target.SEED / "pom.xml").read_text()
    if seed_pom != jira_target.render_seed_pom(seed_pom, t):
        raise SystemExit("the seed's pom.xml is not pinned to the resolved versions: run prepare_seed.py first")
    tools = tools_dir()
    mvn, m2 = tools / "bin" / "mvn", tools / "m2"

    print(f"jira {t.jira_version} ({t.sources['jira_version']}), amps {t.amps_version} "
          f"({t.sources['amps_version']}), java release {t.java_release} ({t.sources['java_release']})")
    print(f"embedded pom: {t.pom_name or '(none)'}")
    print(f"vendor's own modules (rewritten, not primed): {len(t.vendor_deps)}")
    for c in t.vendor_deps:
        print(f"  {c}")
    deps, missing = available(t.original_deps)
    print(f"original plugin dependencies to prime: {len(deps)} of {len(t.original_deps)}")
    for d in deps:
        print(f"  {d.coords} ({d.scope})")
    for c in missing:
        print(f"  not in a public repository, not primed: {c}")
    for s in t.skipped_deps:
        print(f"  skipped: {s}")
    print(f"repository: {m2}")
    if args.dry_run:
        return 0
    if not mvn.exists():
        raise SystemExit(f"{mvn} not found: run install_re_tools.sh first")

    m2.mkdir(parents=True, exist_ok=True)
    set_writable(m2, True)   # re-priming after an earlier run left it read-only
    ignore = shutil.ignore_patterns("vendor", "target", ".m2", ".git")
    with tempfile.TemporaryDirectory(prefix="lrae-prime-") as tmp:
        prime = Path(tmp) / "prime"
        shutil.copytree(jira_target.SEED, prime, ignore=ignore)
        (prime / "pom.xml").write_text(priming_pom(seed_pom, deps))
        online = [str(mvn), "-B", "-ntp", f"-Dmaven.repo.local={m2}"]
        run(online + ["package"], prime)
        run(online + [f"{DEPENDENCY_PLUGIN}:go-offline"], prime)

        verify = Path(tmp) / "verify"
        shutil.copytree(jira_target.SEED, verify, ignore=ignore)
        env = {**os.environ, "LRAE_RE_TOOLS": str(tools)}
        run(["sh", "build.sh"], verify, env)
        jars = sorted((verify / "target").glob("*.jar"))
        if not jars:
            raise SystemExit("offline build of the seed produced no plugin jar in target/")
        shutil.rmtree(prime / "target", ignore_errors=True)
        shutil.copyfile(verify / "build.sh", prime / "build.sh")
        run(["sh", "build.sh"], prime, env)

    digest = write_manifest(m2, tools / "m2.manifest")
    set_writable(m2, False)
    size = sum(p.stat().st_size for p in m2.rglob("*") if p.is_file())
    print(f"\nprimed {m2} ({size / 1e6:.0f} MB), now read-only; offline build verified ({jars[0].name})")
    print(f"m2.manifest sha256 (spec task.toolchain.m2_manifest_sha256, phase J1): {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
