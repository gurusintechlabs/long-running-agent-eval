# Plugin replacement project

We are replacing a Jira Data Center plugin whose source we no longer have. The plugin's jar is in
`vendor/`. The goal is a behavioural specification of the plugin and a clean-room rewrite of it in
Java.

| Path | What |
|---|---|
| `vendor/` | The plugin jar under study. Read-only. |
| `.decompiled/` | Your decompiler output. Git-ignored, never committed. |
| `analysis/` | Inventory, specification, claims, rewrite map, audit. |
| `src/main/java/` | The rewrite (Java 21, JDK only). |
| `src/test/java/` | Its tests (JUnit Jupiter). |
| `build.sh` | Offline build and test: `sh build.sh test`. |

Project rules: `CLAUDE.md`. Tools and environment: `ENVIRONMENT.md`.
