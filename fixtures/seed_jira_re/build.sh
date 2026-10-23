#!/bin/sh
# Build the plugin offline with Maven and AMPS (there is no network).
#
#   sh build.sh                 compile, run the tests, build the plugin jar in target/ (= mvn package)
#   sh build.sh test            compile and run the tests only
#   sh build.sh <maven args>    any other Maven goals or options, e.g. sh build.sh -Dtest=Foo test
#
# Dependencies come from the shared read-only repository in ~/lrae-tools/re/m2; anything Maven writes
# goes to .m2/ here (git-ignored). Only artifacts already in that repository can be used.
set -eu
TOOLS="${LRAE_RE_TOOLS:-$HOME/lrae-tools/re}"
cd "$(dirname "$0")"
[ $# -gt 0 ] || set -- package
exec "$TOOLS/bin/mvn" -o -B -ntp \
  -Dmaven.repo.local="$PWD/.m2/repository" -Dmaven.repo.local.tail="$TOOLS/m2" "$@"
