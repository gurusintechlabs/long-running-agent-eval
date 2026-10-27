"""J1: copy similarity of a clean-room rewrite against the scorer's own decompilation (scorer/clean_room.py)."""
import stat
import zipfile
from pathlib import Path

import pytest

from scorer import clean_room as cr
from scorer import metric_names as mn
from spec.schema import CleanRoomScoring

ORIGINAL = """package com.acme.approvals;

import com.atlassian.jira.issue.Issue;
import java.util.List;

/** Blocks a transition until enough approvers have signed off. */
public class ApprovalValidator {
    private final ApprovalStore store;
    private final int required;

    public ApprovalValidator(ApprovalStore store, int required) {
        this.store = store;
        this.required = required;
    }

    public boolean validate(Issue issue) {
        if (issue == null) {
            throw new IllegalArgumentException("issue");
        }
        List<String> approvers = store.approversFor(issue.getKey());
        int count = 0;
        for (String a : approvers) {
            if (a != null && !a.isEmpty() && !a.equals(issue.getReporterId())) {
                count++;
            }
        }
        if (count < required) {
            store.recordRejection(issue.getKey(), count, required);
            return false;
        }
        return true;
    }
}
"""

# the same code, identifiers renamed, comments and layout changed: a disguised copy
RENAMED = """package org.cleanroom.gate;

import java.util.List;

public class SignoffGate
{
    private final Ledger ledger;   // where signoffs live
    private final int threshold;

    public SignoffGate(Ledger ledger, int threshold) { this.ledger = ledger; this.threshold = threshold; }

    public boolean check(Ticket ticket)
    {
        if (ticket == null) { throw new IllegalArgumentException("ticket"); }
        List<String> names = ledger.namesFor(ticket.getId());
        int n = 0;
        for (String s : names) { if (s != null && !s.isEmpty() && !s.equals(ticket.getAuthor())) { n++; } }
        if (n < threshold) { ledger.logRefusal(ticket.getId(), n, threshold); return false; }
        return true;
    }
}
"""

# the same behaviour, written independently
INDEPENDENT = """package org.cleanroom.gate;

import java.util.Objects;

public final class SignoffPolicy {
    private final SignoffRepository repository;
    private final int minimum;

    public SignoffPolicy(SignoffRepository repository, int minimum) {
        this.repository = Objects.requireNonNull(repository);
        this.minimum = minimum;
    }

    public Decision decide(TicketView ticket) {
        Objects.requireNonNull(ticket, "ticket");
        long valid = repository.signers(ticket.id()).stream()
                .filter(name -> name != null && !name.isBlank())
                .filter(name -> !name.equals(ticket.author()))
                .count();
        return valid >= minimum ? Decision.allow() : Decision.deny(ticket.id(), valid, minimum);
    }
}
"""


def test_tokens_drop_comments_strings_package_and_imports():
    toks = cr.tokens('package a.b;\nimport x.Y;\n// c\n/* d */ class A { String s = "hi"; int n = 42; char c = \'x\'; }')
    assert [t for t, _ in toks] == ["class", "ID", "{", "ID", "ID", "=", "LIT", ";", "int", "ID", "=", "LIT", ";",
                                    "char", "ID", "=", "LIT", ";", "}"]
    assert [v for _, v in toks][:2] == ["class", "A"]


def test_disguised_copy_is_structurally_similar_but_lexically_not():
    ref = cr.fingerprints_of({"A.java": ORIGINAL}, k=12, window=3)
    copy = cr.similarity({"G.java": RENAMED}, ref, k=12, window=3)
    assert copy["structural"] >= 0.8 and copy["lexical"] < 0.35, copy


def test_independent_rewrite_is_dissimilar():
    ref = cr.fingerprints_of({"A.java": ORIGINAL}, k=12, window=3)
    own = cr.similarity({"P.java": INDEPENDENT}, ref, k=12, window=3)
    assert own["structural"] < 0.25 and own["lexical"] < 0.1, own


def test_verbatim_copy_is_one_and_files_are_ranked():
    ref = cr.fingerprints_of({"A.java": ORIGINAL}, k=12, window=3)
    res = cr.similarity({"A.java": ORIGINAL, "P.java": INDEPENDENT}, ref, k=12, window=3)
    assert res["files"][0]["path"] == "A.java" and res["files"][0]["structural"] == 1.0
    assert 0 < res["structural"] < 1


def test_background_fingerprints_are_excluded():
    ref = cr.fingerprints_of({"A.java": ORIGINAL}, k=12, window=3)
    background = cr.fingerprints_of({"A.java": ORIGINAL}, k=12, window=3)
    res = cr.similarity({"A.java": ORIGINAL}, ref, k=12, window=3, background=background)
    assert res["structural"] is None and res["fingerprints"] == 0   # nothing of its own left to compare


def test_reference_sources_from_dirs_and_archives(tmp_path):
    (tmp_path / "out" / "com" / "acme").mkdir(parents=True)
    (tmp_path / "out" / "com" / "acme" / "A.java").write_text(ORIGINAL)
    with zipfile.ZipFile(tmp_path / "out" / "plugin.jar", "w") as z:   # Vineflower keeps archives as archives
        z.writestr("com/acme/B.java", INDEPENDENT)
        z.writestr("atlassian-plugin.xml", "<x/>")
    srcs = cr.collect_sources(tmp_path / "out")
    assert set(srcs) == {"com/acme/A.java", "plugin.jar!com/acme/B.java"}


# ---- end to end, with a fake decompiler in a fake toolchain

def toolchain(tmp_path: Path, java: str) -> Path:
    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    (tmp_path / "decompiled.java").write_text(java)
    script = tools / "bin" / "vineflower"
    script.write_text(f'#!/bin/sh\necho run >> "{tmp_path}/runs.txt"\nmkdir -p "$2/com/acme"\n'
                      f'cp "{tmp_path}/decompiled.java" "$2/com/acme/ApprovalValidator.java"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return tools


def workspaces(tmp_path: Path, rewrite: str | None) -> tuple[Path, Path]:
    seed = tmp_path / "seed"
    (seed / "vendor").mkdir(parents=True)
    (seed / "vendor" / "approvals-1.4.jar").write_bytes(b"PK fake jar")
    (seed / "src" / "main" / "java").mkdir(parents=True)
    ws = tmp_path / "ws"
    (ws / "src" / "main" / "java" / "org" / "x").mkdir(parents=True)
    if rewrite is not None:
        (ws / "src" / "main" / "java" / "org" / "x" / "Gate.java").write_text(rewrite)
    return seed, ws


def test_score_clean_room_end_to_end_and_cached(tmp_path):
    tools = toolchain(tmp_path, ORIGINAL)
    seed, ws = workspaces(tmp_path, RENAMED)
    cfg = CleanRoomScoring(enabled=True, k=12, window=3)
    m = cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache")
    assert set(m) == {mn.CR_STRUCTURAL, mn.CR_LEXICAL}
    assert m[mn.CR_STRUCTURAL]["value"] >= 0.8 and m[mn.CR_LEXICAL]["value"] < 0.35
    d = m[mn.CR_STRUCTURAL]["detail"]
    assert d["decompiler"] == "vineflower" and d["reference_files"] == 1 and d["files"][0]["path"].endswith("Gate.java")
    cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache")
    assert (tmp_path / "runs.txt").read_text().count("run") == 1     # the reference is decompiled once


def test_score_clean_room_without_sources_or_jar(tmp_path):
    tools = toolchain(tmp_path, ORIGINAL)
    seed, ws = workspaces(tmp_path, None)
    cfg = CleanRoomScoring(enabled=True, k=12, window=3)
    m = cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache")
    assert m[mn.CR_STRUCTURAL]["value"] is None and m[mn.CR_STRUCTURAL]["detail"]["reason"] == "no_rewrite_sources"
    (seed / "vendor" / "approvals-1.4.jar").unlink()
    m = cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache2")
    assert m[mn.CR_LEXICAL]["value"] is None and "jar" in m[mn.CR_LEXICAL]["detail"]["reason"]


def test_score_clean_room_reads_a_harness_side_jar(tmp_path):
    """JA: with ``jar`` set the jar is not looked for in the seed (the implementer's seed has none)."""
    tools = toolchain(tmp_path, ORIGINAL)
    seed, ws = workspaces(tmp_path, RENAMED)
    (seed / "vendor" / "approvals-1.4.jar").unlink()
    outside = tmp_path / "task" / "vendor" / "approvals-1.4.jar"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"PK fake jar")
    cfg = CleanRoomScoring(enabled=True, k=12, window=3, jar=str(outside))
    m = cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache")
    assert m[mn.CR_STRUCTURAL]["value"] >= 0.8 and m[mn.CR_STRUCTURAL]["detail"]["jar"] == "approvals-1.4.jar"
    by_dir = CleanRoomScoring(enabled=True, k=12, window=3, jar=str(outside.parent))   # the spec names no jar
    assert cr.score_clean_room(by_dir, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache")[
        mn.CR_LEXICAL]["detail"]["jar"] == "approvals-1.4.jar"
    outside.unlink()
    m = cr.score_clean_room(cfg, tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "cache2")
    assert m[mn.CR_STRUCTURAL]["value"] is None and m[mn.CR_STRUCTURAL]["detail"]["reason"].startswith("no_jar")


def test_score_clean_room_decompiler_failure_is_reported(tmp_path):
    tools = toolchain(tmp_path, ORIGINAL)
    (tools / "bin" / "vineflower").write_text("#!/bin/sh\necho broken >&2\nexit 3\n")
    seed, ws = workspaces(tmp_path, RENAMED)
    m = cr.score_clean_room(CleanRoomScoring(enabled=True), tools_dir=tools, seed_ws=seed, ws=ws,
                            cache_dir=tmp_path / "cache")
    assert m[mn.CR_STRUCTURAL]["value"] is None
    assert m[mn.CR_STRUCTURAL]["detail"]["reason"].startswith("decompile_failed")


@pytest.mark.parametrize("name", [lambda: mn.CR_STRUCTURAL, lambda: mn.CR_LEXICAL])
def test_names_are_otel_style(name):
    import re
    assert re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", name()) and name().startswith(mn.CR_PREFIX)


def test_extra_jars_join_the_reference(tmp_path):
    """JA1: the bundled public API is decompiled too (``extra_jars``: a jar or a dir of jars), so copying from
    it shows; without it the same rewrite looks independent."""
    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    script = tools / "bin" / "vineflower"      # "decompiles" a jar by copying its text
    script.write_text('#!/bin/sh\nmkdir -p "$2/x"\ncp "$1" "$2/x/$(basename "$1" .jar).java"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    seed, ws = workspaces(tmp_path, RENAMED)
    plugin = tmp_path / "task" / "vendor" / "plugin.jar"
    api = tmp_path / "task" / "vendor" / "api" / "acme-api-2.1.jar"
    api.parent.mkdir(parents=True)
    plugin.write_text(INDEPENDENT)
    api.write_text(ORIGINAL)
    base = dict(enabled=True, k=12, window=3, jar=str(plugin.parent))
    alone = cr.score_clean_room(CleanRoomScoring(**base), tools_dir=tools, seed_ws=seed, ws=ws, cache_dir=tmp_path / "c")
    for extra in (api.parent, api):
        m = cr.score_clean_room(CleanRoomScoring(**base, extra_jars=str(extra)), tools_dir=tools, seed_ws=seed, ws=ws,
                                cache_dir=tmp_path / "c")
        d = m[mn.CR_STRUCTURAL]["detail"]
        assert m[mn.CR_STRUCTURAL]["value"] >= 0.8 > alone[mn.CR_STRUCTURAL]["value"]
        assert d["extra_jars"] == ["acme-api-2.1.jar"] and d["reference_files"] == 2
    api.unlink()
    m = cr.score_clean_room(CleanRoomScoring(**base, extra_jars=str(api.parent)), tools_dir=tools, seed_ws=seed, ws=ws,
                            cache_dir=tmp_path / "c")
    assert m[mn.CR_STRUCTURAL]["value"] is None and m[mn.CR_STRUCTURAL]["detail"]["reason"].startswith("no_extra_jars")
