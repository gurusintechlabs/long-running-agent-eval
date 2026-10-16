# fixtures

- `seed_export_service/`: the seed repo for the pilot task (plain files; `build_seed.py` / `runner/seed.py`
  turn it into a one-commit repo whose SHA is pinned in `spec/examples/pilot.yaml`). **Do not edit it,
  and do not run formatters or linters over it**: any change alters the pinned SHA
  (`tests/unit/test_seed.py::test_real_fixture_still_builds_to_the_pinned_sha` guards this).
- `tasks/export_csv/`: task prompt, planted constraints and (Phase 3) hidden tests.
- `otel/`, `stream/`: real output captured from Claude Code CLI 1.0.126 (haiku, one trivial turn), with
  account identifiers removed. Used by the Phase 2 parser/counter tests.
