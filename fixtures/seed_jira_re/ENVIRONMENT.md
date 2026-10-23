# Environment

- No internet access, so no Maven or Gradle downloads. Do not install anything.
- JDK 21 and JUnit (Jupiter, console launcher) are installed. Build and test the rewrite with
  `sh build.sh test` (see the comments in `build.sh`). The rewrite may use the JDK and JUnit only.
- The tools are in `~/lrae-tools/re/bin/` (not on `PATH`; call them by full path):

| Tool | Command | Notes |
|---|---|---|
| JADX | `~/lrae-tools/re/bin/jadx -d .decompiled/jadx vendor/<jar>` | Decompiles a whole jar to Java sources and resources. |
| Vineflower | `~/lrae-tools/re/bin/vineflower vendor/<jar> .decompiled/vineflower/` | Fernflower fork, often the most readable output. |
| CFR | `~/lrae-tools/re/bin/cfr vendor/<jar> --outputdir .decompiled/cfr` | Good with modern Java constructs. |
| Procyon | `~/lrae-tools/re/bin/procyon -jar vendor/<jar> -o .decompiled/procyon` | A third opinion on hard methods. |
| javap | `~/lrae-tools/re/bin/javap -c -p -classpath vendor/<jar> <class>` | Bytecode, when decompilers disagree. |
| jar | `~/lrae-tools/re/bin/jar tf vendor/<jar>` | List or extract the archive (e.g. `atlassian-plugin.xml`). |
| java, javac | `~/lrae-tools/re/bin/java`, `~/lrae-tools/re/bin/javac` | JDK 21 (what `build.sh` uses). |

- The Jira APIs the plugin compiles against are not available here. The rewrite defines its own small
  interfaces for whatever Jira functionality it needs (see stage 2).
- When the harness provides it, the REA reverse-engineering MCP server is available as the
  `mcp__rea__*` tools.
