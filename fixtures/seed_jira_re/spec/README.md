# spec/: the specification of the plugin being replaced (read-only)

Written by the analyst from the original plugin. It describes behaviour, never code.

| File | What |
|---|---|
| `PILOT.md` | **Start here.** What this pilot covers, out of everything below. |
| `pilot-claims.jsonl` | The claims in the pilot's scope: the same lines as in `claims.jsonl`. |
| `SPEC.md` | The external contract first (everything the replacement must keep exactly), then each module's behaviour. |
| `API.md` | Part 2 of `SPEC.md`: the public Java API, every type and signature exactly, with the meaning of each. |
| `INVENTORY.md` | What the plugin is for and how its modules fit together. |
| `inventory.json` | Every module: key, type, contract class name where the contract fixes one, purpose. |
| `claims.jsonl` | One testable behaviour per line, with a permanent id (`C-0001`), what it belongs to, and a confidence. A claim belongs either to a module (`module`, its key) or to a type of the public Java API (`module` null, `api` the type's fully qualified name; a claim about a member type names its top-level type). A claim with `"suspected_bug": true` states behaviour of the original that the analyst believes is a mistake; see below. |
| `api-tests/` | JUnit tests of the plugin's public Java API (a sample of its exact signatures, and a few behaviours). Copy them into `src/test/java/`; they must pass unchanged. |
| `CHANGES-*.md` | Later corrections by the analyst; they override the files above where they differ. |

Tests run with Java assertions enabled (Maven Surefire's default). Where the original checks an input only
with an `assert`, its claim states both outcomes, with assertions enabled and disabled; the hidden tests see
the first.

**Suspected bugs.** Claims flagged `"suspected_bug": true` describe the original faithfully, including what
looks like a bug (their text says "as the original does"). They are the contract until a `CHANGES-*.md` file
says otherwise: implement them as stated, and check each one as you implement it (stage 2 says how).

**`<product>`.** Wherever text quoted in a claim has `<product>`, the replacement shows its own display name
(`SPEC.md` 1.1), so 'Welcome to `<product>`' is the claim's exact text with your name in it.
