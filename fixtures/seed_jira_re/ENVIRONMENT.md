# Environment

- No internet access. Do not install anything.
- **Building:** `sh build.sh` runs Maven offline (`mvn package`: compile, test, build the plugin jar in
  `target/`); `sh build.sh test` runs the tests only; any other Maven arguments are passed through. The
  JDK is 21. Dependencies come from a shared read-only repository that holds the Jira API of the
  original plugin's Jira version, the original plugin's own declared dependencies, the dependencies of
  its public Java API (see `spec/SPEC.md`), AMPS, JUnit 5 and Mockito. Anything that is not there cannot be used. Calling `mvn` directly, without `build.sh`, will
  not find that repository. The repository was filled for the seed on its own, the seed plus any one of
  those dependencies, and the seed plus all of them; another combination can resolve a library to a
  version that is not there, which the offline build reports. Pin the library's version in
  `<dependencyManagement>` to one the repository has.
- The JDK and Maven are in `~/lrae-tools/re/bin/` (`java`, `javac`, `jar`, `mvn`; not on `PATH`). Prefer
  `sh build.sh`.
- **Testing the UI:** there is no running Jira, so UI claims are tested in JUnit too, in a real headless
  browser. To use it, add these two to `pom.xml` with `<scope>test</scope>`: `com.microsoft.playwright:playwright:1.49.0`
  (drives the browser, with a real DOM, keyboard, mouse and drag-and-drop) and `org.jsoup:jsoup:1.23.1` (parses
  HTML, for server-rendered pages). `build.sh` points Playwright at the pinned Chromium in
  `~/lrae-tools/re/browsers`, which is headless only, so call `playwright.chromium().launch()` with no
  browser path or channel, and nothing is downloaded. Only `sh build.sh` sets this up. Load your own JS into a page with
  `page.setContent(...)` or `page.addScriptTag(...)`, with your own stand-ins for what Jira provides (its page
  objects, its JS libraries) and `page.route(...)` for REST replies. Share one browser per test class: starting
  one takes seconds.
