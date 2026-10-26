# Environment

- No internet access. Do not install anything.
- **Building:** `sh build.sh` runs Maven offline (`mvn package`: compile, test, build the plugin jar in
  `target/`); `sh build.sh test` runs the tests only; any other Maven arguments are passed through. The
  JDK is 21. Dependencies come from a shared read-only repository that holds the Jira API of the
  original plugin's Jira version, the original plugin's own declared dependencies, AMPS, JUnit 5 and
  Mockito. Anything that is not there cannot be used. Calling `mvn` directly, without `build.sh`, will
  not find that repository. The repository was filled for the seed on its own, the seed plus any one of
  those dependencies, and the seed plus all of them; another combination can resolve a library to a
  version that is not there, which the offline build reports. Pin the library's version in
  `<dependencyManagement>` to one the repository has.
- The reverse-engineering tools are in `~/lrae-tools/re/bin/` (not on `PATH`; call them by full path):

| Tool | Command | Notes |
|---|---|---|
| JADX | `~/lrae-tools/re/bin/jadx -d .decompiled/jadx vendor/<jar>` | Decompiles a whole jar to Java sources and resources. |
| Vineflower | `~/lrae-tools/re/bin/vineflower vendor/<jar> .decompiled/vineflower/` | Fernflower fork, often the most readable output. |
| CFR | `~/lrae-tools/re/bin/cfr vendor/<jar> --outputdir .decompiled/cfr` | Good with modern Java constructs. |
| Procyon | `~/lrae-tools/re/bin/procyon -jar vendor/<jar> -o .decompiled/procyon` | A third opinion on hard methods. |
| javap | `~/lrae-tools/re/bin/javap -c -p -classpath vendor/<jar> <class>` | Bytecode, when decompilers disagree. |
| jar | `~/lrae-tools/re/bin/jar tf vendor/<jar>` | List or extract the archive (e.g. `atlassian-plugin.xml`). |
| java, javac, mvn | `~/lrae-tools/re/bin/...` | JDK 21 and Maven (prefer `sh build.sh`). |

- When the harness provides it, the REA reverse-engineering MCP server is available as the
  `mcp__rea__*` tools.
