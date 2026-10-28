# spec/: the specification of the plugin being replaced (read-only)

Written by the analyst from the original plugin. It describes behaviour, never code.

| File | What |
|---|---|
| `SPEC.md` | The external contract first (everything the replacement must keep exactly), then each module's behaviour. |
| `API.md` | Part 2 of `SPEC.md`: the public Java API, every type and signature exactly, with the meaning of each. |
| `INVENTORY.md` | What the plugin is for and how its modules fit together. |
| `inventory.json` | Every module: key, type, contract class name where the contract fixes one, purpose. |
| `claims.jsonl` | One testable behaviour per line, with a permanent id (`C-0001`), the module it belongs to, and a confidence. |
| `api-tests/` | JUnit tests of the plugin's public Java API (a sample of its exact signatures, and a few behaviours). Copy them into `src/test/java/`; they must pass unchanged. |
| `CHANGES-*.md` | Later corrections by the analyst; they override the files above where they differ. |
