#!/usr/bin/env python3
"""Fill the shared offline Maven repository for the jira-re rewrite (docs/jira-re-design.md §4).

    .venv/bin/python fixtures/tasks/jira_re/tools/prime_maven_repo.py [--dry-run]

Run after ``install_re_tools.sh`` and ``prepare_seed.py``, with network. Runs need no network: the
agent's ``build.sh`` runs Maven offline with this repository as a read-only tail
(``maven.repo.local.tail``).

1. Priming builds (online): the seed alone (``clean package``); the seed plus each of the original
   plugin's dependencies on its own (``dependency:resolve``: Maven resolves one version per library per
   project, so each combination fetches different versions); and a temp copy of the seed whose pom also declares the original plugin's
   non-test dependencies (from the pom embedded in its jar), so the rewrite can use the same APIs:
   ``mvn clean package`` (AMPS packaging, compiler, surefire and its JUnit provider), then a best-effort
   ``dependency:go-offline``. Everything lands in ``<tools>/m2``. Artifacts no repository serves are
   excluded and the build retried; the list goes to ``target.yaml`` (``maven_exclusions``), and the seed
   pom must carry it too (re-run ``prepare_seed.py``; the script stops with exit 2 to say so).
2. Offline checks: a fresh copy of the seed, built exactly as the agent builds it (``sh build.sh``),
   must produce the plugin jar; the priming project must also build offline.
3. ``<tools>/m2`` and ``<tools>/browsers`` are made read-only, and ``<tools>/m2.manifest`` lists every artifact and browser file with its SHA-256
   (resolver bookkeeping files with timestamps excluded). Its hash pins the repository (rule 4).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
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
MAX_EXCLUSION_ROUNDS = 8
# What the implementer tests the UI with (owner 2026-10-30). Test scope only; the browser is installed once
# into <tools>/browsers by ``install_browser`` and pinned by the manifest.
UI_TEST_DEPS = (jira_target.Dep("com.microsoft.playwright", "playwright", "1.49.0", "test"),
                jira_target.Dep("org.jsoup", "jsoup", "1.23.1", "test"))
UI_CHECK_TEST = """import com.microsoft.playwright.*;
import org.jsoup.Jsoup;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class UiToolsCheckTest {
    @Test void browserAndParserWorkOffline() {
        try (Playwright pw = Playwright.create(); Browser browser = pw.chromium().launch()) {
            Page page = browser.newPage();
            page.setContent("<input id=i><script>window.seen=[];"
                + "document.getElementById('i').addEventListener('keydown',e=>seen.push(e.key));</script>");
            page.focus("#i");
            page.keyboard().press("Enter");
            assertEquals("Enter", page.evaluate("seen.join()"));
        }
        assertEquals("a", Jsoup.parse("<p id=p>a</p>").getElementById("p").text());
    }
}
"""
BOOKKEEPING = ("_remote.repositories", "resolver-status.properties", "maven-metadata-local.xml")


def tools_dir() -> Path:
    return Path(os.environ.get("LRAE_RE_TOOLS") or Path.home() / "lrae-tools" / "re").expanduser()


def run(cmd: list[str], cwd: Path, env: dict | None = None, *, check: bool = True) -> tuple[int, str]:
    """Run, echoing the output; return ``(returncode, output)``."""
    print("$", " ".join(cmd), f"   (in {cwd})", flush=True)
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout:
        print(line, end="")
        lines.append(line)
    rc = proc.wait()
    if check and rc != 0:
        raise SystemExit(f"failed ({rc}): {' '.join(cmd)}")
    return rc, "".join(lines)


def record_exclusions(exclusions: list[str]) -> None:
    """Write ``maven_exclusions`` into target.yaml (replacing the line, or appending it)."""
    text = jira_target.TARGET.read_text()
    line = "maven_exclusions: [" + ", ".join(f'"{x}"' for x in exclusions) + "]   # written by prime_maven_repo.py"
    pat = re.compile(r"^maven_exclusions:.*$", re.M)
    text = pat.sub(line, text) if pat.search(text) else text.rstrip("\n") + "\n" + line + "\n"
    jira_target.TARGET.write_text(text)


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


# Maven's two wordings: a fresh miss, and a miss cached in the local repository by an earlier attempt
_MISSING = re.compile(r"Could not find artifact ([^:\s]+):([^:\s]+):|([^:\s]+):([^:\s]+):\S+ was not found in ")


def to_prime(t: jira_target.Target, api_deps: list[jira_target.Dep]) -> list[jira_target.Dep]:
    """The original plugin's dependencies, then its public API's (phase JA1), once each by coordinates."""
    out = list(t.original_deps)
    return out + [d for d in api_deps if all(o.coords != d.coords for o in out)]


def missing_artifacts(maven_output: str) -> list[str]:
    """``group:artifact`` of every artifact Maven could not find in any repository, in order, once each."""
    out: list[str] = []
    for m in _MISSING.finditer(maven_output):
        ga = f"{m.group(1)}:{m.group(2)}" if m.group(1) else f"{m.group(3)}:{m.group(4)}"
        if ga not in out:
            out.append(ga)
    return out


def priming_pom(seed_pom: str, deps: list[jira_target.Dep], exclusions: list[str] = ()) -> str:
    present = {line.strip() for line in seed_pom.splitlines()}
    extra = []
    for d in deps:
        if f"<artifactId>{d.artifact}</artifactId>" in present:
            continue
        type_line = f"\n            <type>{d.type}</type>" if d.type != "jar" else ""
        excl = (f"\n            <exclusions>{jira_target.exclusions_xml(list(exclusions), '            ')}"
                f"\n            </exclusions>") if exclusions else ""
        extra.append(f"""        <dependency>
            <groupId>{d.group}</groupId>
            <artifactId>{d.artifact}</artifactId>
            <version>{d.version}</version>{type_line}
            <scope>provided</scope>{excl}
        </dependency>
""")
    head, sep, tail = seed_pom.partition("    </dependencies>")
    if not sep:
        raise SystemExit("seed pom.xml has no </dependencies>")
    return head + "".join(extra) + sep + tail


def _with_seed_exclusions(pom: str, exclusions: list[str]) -> str:
    """The priming copy of the seed pom carries the exclusions found so far on jira-api as well."""
    return jira_target._render_exclusions(pom, sorted(exclusions))


def set_writable(root: Path, writable: bool) -> None:
    for p in [root, *root.rglob("*")]:
        if p.is_symlink():
            continue
        mode = p.stat().st_mode
        w = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        p.chmod((mode | stat.S_IWUSR) if writable else (mode & ~w))


def install_browser(mvn: Path, m2: Path, browsers: Path, project: Path) -> None:
    """Install Playwright's pinned headless Chromium into ``browsers`` (a tool of the run: Chrome on the host
    updates itself). ``project``'s pom must declare Playwright."""
    cp = project / "playwright.classpath"
    run([str(mvn), "-B", "-ntp", f"-Dmaven.repo.local={m2}", f"{DEPENDENCY_PLUGIN}:build-classpath",
         f"-Dmdep.outputFile={cp}", "-DincludeScope=provided",
         "-DincludeGroupIds=com.microsoft.playwright,com.google.code.gson,org.java-websocket"], project)
    if browsers.exists():
        set_writable(browsers, True)
        shutil.rmtree(browsers)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)}
    run([str(mvn.parent / "java"), "-cp", cp.read_text().strip(), "com.microsoft.playwright.CLI",
         "install", "--only-shell", "chromium"], project, env)
    set_writable(browsers, False)


def write_manifest(m2: Path, out: Path, browsers: Path | None = None) -> str:
    lines = []
    for p in sorted(m2.rglob("*")):
        if p.is_file() and p.name not in BOOKKEEPING and not p.name.endswith(".lastUpdated"):
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(m2).as_posix()}")
    for p in sorted(browsers.rglob("*")) if browsers else ():
        rel = p.relative_to(browsers).as_posix()
        if p.is_file() and not p.is_symlink() and not rel.startswith(".links/"):
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ../browsers/{rel}")
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
    mvn, m2, browsers = tools / "bin" / "mvn", tools / "m2", tools / "browsers"

    print(f"jira {t.jira_version} ({t.sources['jira_version']}), amps {t.amps_version} "
          f"({t.sources['amps_version']}), java release {t.java_release} ({t.sources['java_release']})")
    print(f"embedded pom: {t.pom_name or '(none)'}")
    print(f"vendor's own modules (rewritten, not primed): {len(t.vendor_deps)}")
    for c in t.vendor_deps:
        print(f"  {c}")
    wanted = to_prime(t, jira_target.public_api_dependencies(t)) + list(UI_TEST_DEPS)
    if t.public_api:
        print(f"public API (rewritten, not primed; its dependencies are): {', '.join(t.public_api)}")
    deps, missing = available(wanted)
    print(f"dependencies to prime (the plugin's, then its public API's): {len(deps)} of {len(wanted)}")
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
        online = [str(mvn), "-B", "-ntp", f"-Dmaven.repo.local={m2}"]
        exclusions = list(t.exclusions)
        for _ in range(MAX_EXCLUSION_ROUNDS):   # artifacts no repository serves are excluded, then retried
            (prime / "pom.xml").write_text(_with_seed_exclusions(priming_pom(seed_pom, deps, exclusions), exclusions))
            rc, out = run(online + ["clean", "package"], prime, check=False)   # clean: agents run it too
            if rc == 0:
                break
            new = [x for x in missing_artifacts(out) if x not in exclusions]
            if not new:
                raise SystemExit("priming build failed (see above), and not for a missing artifact")
            print(f"\nnot in any repository, excluding and retrying: {', '.join(new)}\n", flush=True)
            exclusions += new
        else:
            raise SystemExit(f"priming still fails after {MAX_EXCLUSION_ROUNDS} rounds of exclusions")
        # Maven picks one version of each library per project, so the combined build above does not fetch
        # the versions the seed alone, or the seed plus one dependency, resolves to. Prime those too: they
        # are what the agent builds first.
        alone = Path(tmp) / "alone"
        shutil.copytree(jira_target.SEED, alone, ignore=ignore)
        (alone / "pom.xml").write_text(_with_seed_exclusions(seed_pom, exclusions))
        run(online + ["clean", "package"], alone)
        for d in deps:
            (alone / "pom.xml").write_text(_with_seed_exclusions(priming_pom(seed_pom, [d], exclusions), exclusions))
            rc, out = run(online + [f"{DEPENDENCY_PLUGIN}:resolve"], alone, check=False)
            new = [x for x in missing_artifacts(out) if x not in exclusions]
            if rc != 0 and not new:
                raise SystemExit(f"resolving {d.coords} on its own failed (see above), and not for a missing artifact")
            exclusions += new
        if sorted(exclusions) != t.exclusions:
            record_exclusions(sorted(exclusions))
            print(f"\nrecorded maven_exclusions in {jira_target.TARGET.name}: {sorted(exclusions)}\n"
                  "The seed's jira-api must exclude them too. Re-run prepare_seed.py, then this script.")
            return 2
        # Best effort: go-offline also resolves build plugins' own dependencies, where project exclusions do
        # not apply (AMPS 9.2.3 needs commons-httpclient 3.1-jenkins-3, which no repository serves). The
        # offline builds below are the check that counts.
        rc, _ = run(online + [f"{DEPENDENCY_PLUGIN}:go-offline"], prime, check=False)
        if rc != 0:
            print("\nwarning: dependency:go-offline incomplete (see above); relying on the offline builds below\n",
                  flush=True)

        install_browser(mvn, m2, browsers, prime)

        verify = Path(tmp) / "verify"
        shutil.copytree(jira_target.SEED, verify, ignore=ignore)
        env = {**os.environ, "LRAE_RE_TOOLS": str(tools)}
        run(["sh", "build.sh"], verify, env)
        jars = sorted((verify / "target").glob("*.jar"))
        if not jars:
            raise SystemExit("offline build of the seed produced no plugin jar in target/")
        shutil.rmtree(prime / "target", ignore_errors=True)
        shutil.copyfile(verify / "build.sh", prime / "build.sh")
        check = prime / "src" / "test" / "java" / "UiToolsCheckTest.java"
        check.parent.mkdir(parents=True, exist_ok=True)
        check.write_text(UI_CHECK_TEST)
        run(["sh", "build.sh"], prime, env)   # the primed project, with the UI test tools at work

    digest = write_manifest(m2, tools / "m2.manifest", browsers)
    set_writable(m2, False)
    size = sum(p.stat().st_size for p in m2.rglob("*") if p.is_file())
    print(f"\nprimed {m2} ({size / 1e6:.0f} MB), now read-only; offline build verified ({jars[0].name})")
    print(f"m2.manifest sha256 (spec task.toolchain.m2_manifest_sha256, phase J1): {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
