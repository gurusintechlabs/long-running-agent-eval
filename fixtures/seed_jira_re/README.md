# Plugin replacement project

We are replacing a Jira Data Center plugin whose source we no longer have. Our analyst has written a
behavioural specification of it in `spec/`. The goal is a clean-room replacement built from that
specification: a Jira plugin, built from this repository, that can be installed in place of the original.

| Path | What |
|---|---|
| `spec/` | The analyst's specification: inventory, external contract, behaviour, claims. Read-only. |
| `analysis/` | Your plan, architecture, rewrite map, questions about the spec. |
| `pom.xml` | The replacement's Maven build (AMPS, `atlassian-plugin` packaging). |
| `src/main/java/`, `src/main/resources/atlassian-plugin.xml` | The replacement plugin. |
| `src/test/java/` | Its tests (JUnit 5, Mockito). |
| `build.sh` | Offline build: `sh build.sh` (the plugin jar lands in `target/`). |

Project rules: `CLAUDE.md`. Tools and environment: `ENVIRONMENT.md`.
