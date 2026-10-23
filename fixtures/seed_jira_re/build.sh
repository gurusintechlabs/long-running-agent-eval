#!/bin/sh
# Build and test the rewrite with JDK 21 and JUnit, offline (no Maven or Gradle: there is no network).
#
#   sh build.sh compile    compile src/main/java into build/classes
#   sh build.sh test       compile, then run every test in src/test/java (the default)
#
# Test reports (JUnit XML) go to build/test-results/. build/ is git-ignored.
set -eu
TOOLS="${LRAE_RE_TOOLS:-$HOME/lrae-tools/re}"
JAVAC="$TOOLS/bin/javac"
JAVA="$TOOLS/bin/java"
JUNIT="$TOOLS/lib/junit-console.jar"
cd "$(dirname "$0")"

rm -rf build
mkdir -p build/classes build/test-classes
find src/main/java -name '*.java' > build/main-sources.txt
if [ -s build/main-sources.txt ]; then
  "$JAVAC" --release 21 -Xlint:all -d build/classes @build/main-sources.txt
fi
[ "${1:-test}" = compile ] && exit 0

find src/test/java -name '*.java' > build/test-sources.txt
if [ -s build/test-sources.txt ]; then
  "$JAVAC" --release 21 -d build/test-classes -cp "build/classes:$JUNIT" @build/test-sources.txt
fi
exec "$JAVA" -jar "$JUNIT" execute --disable-banner --details=summary \
  --class-path "build/classes:build/test-classes" --scan-class-path build/test-classes \
  --reports-dir build/test-results
