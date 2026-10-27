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
- The JDK and Maven are in `~/lrae-tools/re/bin/` (`java`, `javac`, `jar`, `mvn`; not on `PATH`). Prefer
  `sh build.sh`.
