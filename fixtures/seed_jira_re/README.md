# Plugin replacement project

We are replacing a Jira Data Center plugin whose source we no longer have. The plugin's jar is in
`vendor/`. The goal is a behavioural specification of the plugin and a clean-room replacement: a Jira
plugin, built from this repository, that can be installed in place of the original.

| Path | What |
|---|---|
| `vendor/` | The plugin jar under study. Read-only. |
| `.decompiled/` | Your decompiler output. Git-ignored, never committed. |
| `analysis/` | Inventory, specification, claims, rewrite map, audit. |
| `pom.xml` | The replacement's Maven build (AMPS, `atlassian-plugin` packaging). |
| `src/main/java/`, `src/main/resources/atlassian-plugin.xml` | The replacement plugin. |
| `src/test/java/` | Its tests (JUnit 5, Mockito). |
| `build.sh` | Offline build: `sh build.sh` (the plugin jar lands in `target/`). |

Project rules: `CLAUDE.md`. Tools and environment: `ENVIRONMENT.md`.
