#!/usr/bin/env bash
# Install the reverse-engineering and Java build toolchain of the jira-re task (docs/jira-re-design.md §3).
#
#   bash fixtures/tasks/jira_re/tools/install_re_tools.sh            # installs into ~/lrae-tools/re
#   LRAE_RE_TOOLS=/some/dir bash fixtures/tasks/jira_re/tools/install_re_tools.sh
#
# Everything lands OUTSIDE this repo, so nothing the agent sees (its PATH, ENVIRONMENT.md, the CLI's
# MCP config) names a harness path. Versions are pinned below; every downloaded file is checked against
# its SHA-256 when one is given here, and all hashes are written to MANIFEST.txt (the spec pins that
# file's hash, rule 4). Run it once, by hand, before the first run. It never touches ~/.claude, and it
# does NOT run `rea-agents setup` (that writes ~/.claude.json and ~/.claude/skills, D-15).
set -euo pipefail

DEST="${LRAE_RE_TOOLS:-$HOME/lrae-tools/re}"
JDK_MAJOR=21                      # Homebrew openjdk@21 (LTS). REA needs a full JDK >= 17.
REA_VERSION=6.7.0                 # npm rea-agents; published 2026-10-18
JADX_VERSION=1.5.6                # skylot/jadx CLI (also opens .jar, .class, .dex, .apk)
VINEFLOWER_VERSION=1.12.0         # maintained Fernflower fork
CFR_VERSION=0.152
PROCYON_VERSION=0.6.0
JADX_MCP_VERSION=0.7.1            # the engine REA drives for its Android tools (REA_JADX_MCP_JAR)
MAVEN_VERSION=3.9.16              # Apache Maven: builds the rewrite (a real plugin, AMPS) offline;
                                  # 3.9+ for maven.repo.local.tail (the shared read-only repo, m2/)

# Expected SHA-256 per file. Empty = trust on first use: the hash is recorded in MANIFEST.txt and
# should be copied here after the first install. The jadx-headless-mcp hash is the one REA's
# docs/android-analysis.md pins (cross-check it there before relying on it).
SHA_JADX=""
SHA_VINEFLOWER=""
SHA_CFR=""
SHA_PROCYON=""
SHA_JADX_MCP="6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75"
SHA512_MAVEN="831a8591fe20c8243b1dbe7d71e3244f31d1665b0804b2e825e38cbbe5ce0cafb8338851f90780735568773e0a6cd07bbec107cda0b896b008b861075358b6f6"   # Apache's .sha512

die() { echo "install_re_tools: $*" >&2; exit 1; }

command -v node >/dev/null || die "node not found (REA needs Node.js 22.19+ / 24.11+ / 26+)"
command -v npm >/dev/null || die "npm not found"
command -v curl >/dev/null || die "curl not found"
command -v unzip >/dev/null || die "unzip not found"
command -v shasum >/dev/null || die "shasum not found"
JAVA_HOME_PIN="$(/usr/libexec/java_home -v "$JDK_MAJOR" 2>/dev/null)" \
  || die "no JDK $JDK_MAJOR found; install it with: brew install openjdk@$JDK_MAJOR"
[ -x "$JAVA_HOME_PIN/bin/javac" ] || die "$JAVA_HOME_PIN is not a full JDK (no javac)"
NODE_BIN="$(command -v node)"

mkdir -p "$DEST"/{bin,lib,downloads}
MANIFEST="$DEST/MANIFEST.txt"
: > "$MANIFEST.tmp"

fetch() {  # fetch URL OUT EXPECTED_SHA [BITS: 256 (default) or 512]
  local url="$1" out="$2" want="$3" bits="${4:-256}" got
  if [ ! -f "$out" ]; then
    echo "downloading $url"
    curl -fsSL --retry 3 -o "$out.part" "$url" || die "download failed: $url"
    mv "$out.part" "$out"
  fi
  got="$(shasum -a "$bits" "$out" | cut -d' ' -f1)"
  if [ -n "$want" ] && [ "$got" != "$want" ]; then
    rm -f "$out"
    die "SHA-256 mismatch for $(basename "$out"): expected $want, got $got (file removed)"
  fi
  [ "$bits" = 256 ] || got="$(shasum -a 256 "$out" | cut -d' ' -f1)"   # the manifest is all SHA-256
  echo "$got  $(basename "$out")  $url" >> "$MANIFEST.tmp"
}

D="$DEST/downloads"
fetch "https://github.com/skylot/jadx/releases/download/v$JADX_VERSION/jadx-$JADX_VERSION.zip" \
      "$D/jadx-$JADX_VERSION.zip" "$SHA_JADX"
fetch "https://github.com/Vineflower/vineflower/releases/download/$VINEFLOWER_VERSION/vineflower-$VINEFLOWER_VERSION.jar" \
      "$DEST/lib/vineflower-$VINEFLOWER_VERSION.jar" "$SHA_VINEFLOWER"
fetch "https://github.com/leibnitz27/cfr/releases/download/$CFR_VERSION/cfr-$CFR_VERSION.jar" \
      "$DEST/lib/cfr-$CFR_VERSION.jar" "$SHA_CFR"
fetch "https://github.com/mstrobel/procyon/releases/download/v$PROCYON_VERSION/procyon-decompiler-$PROCYON_VERSION.jar" \
      "$DEST/lib/procyon-decompiler-$PROCYON_VERSION.jar" "$SHA_PROCYON"
fetch "https://github.com/1013503897/jadx-headless-mcp/releases/download/v$JADX_MCP_VERSION/jadx-headless-mcp-$JADX_MCP_VERSION-all.jar" \
      "$DEST/lib/jadx-headless-mcp-$JADX_MCP_VERSION-all.jar" "$SHA_JADX_MCP"

fetch "https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries/apache-maven-$MAVEN_VERSION-bin.tar.gz" \
      "$D/apache-maven-$MAVEN_VERSION-bin.tar.gz" "$SHA512_MAVEN" 512
if [ ! -x "$DEST/apache-maven-$MAVEN_VERSION/bin/mvn" ]; then
  rm -rf "$DEST/apache-maven-$MAVEN_VERSION"
  tar -xzf "$D/apache-maven-$MAVEN_VERSION-bin.tar.gz" -C "$DEST"
fi
mkdir -p "$DEST/m2"   # the shared offline repository, filled by prime_maven_repo.py

# JADX: unpack once, versioned directory.
if [ ! -x "$DEST/jadx-$JADX_VERSION/bin/jadx" ]; then
  rm -rf "$DEST/jadx-$JADX_VERSION"
  unzip -q "$D/jadx-$JADX_VERSION.zip" -d "$DEST/jadx-$JADX_VERSION"
  chmod +x "$DEST/jadx-$JADX_VERSION/bin/"*
fi

# REA: a private npm prefix with an exact version and a lockfile (pins the transitive tree).
# --ignore-scripts: no install hooks from the dependency tree run on this machine.
REA_DIR="$DEST/rea-$REA_VERSION"
if [ ! -f "$REA_DIR/node_modules/rea-agents/package.json" ]; then
  mkdir -p "$REA_DIR"
  ( cd "$REA_DIR" && echo '{"name":"lrae-rea","private":true}' > package.json \
    && npm install --save-exact --ignore-scripts --no-fund --no-audit "rea-agents@$REA_VERSION" )
fi
REA_ENTRY="$REA_DIR/node_modules/rea-agents/scripts/rea.mjs"
[ -f "$REA_ENTRY" ] || die "REA entry point not found: $REA_ENTRY"
echo "$(shasum -a 256 "$REA_DIR/package-lock.json" | cut -d' ' -f1)  package-lock.json  rea-agents@$REA_VERSION" >> "$MANIFEST.tmp"

# Wrappers on a fixed bin/ path, each pinned to the same JDK.
wrap_jar() {  # wrap_jar NAME JAR
  cat > "$DEST/bin/$1" <<EOF
#!/bin/sh
JAVA_HOME="$JAVA_HOME_PIN"; export JAVA_HOME
exec "\$JAVA_HOME/bin/java" -jar "$2" "\$@"
EOF
  chmod +x "$DEST/bin/$1"
}
wrap_jar cfr "$DEST/lib/cfr-$CFR_VERSION.jar"
wrap_jar vineflower "$DEST/lib/vineflower-$VINEFLOWER_VERSION.jar"
wrap_jar procyon "$DEST/lib/procyon-decompiler-$PROCYON_VERSION.jar"
cat > "$DEST/bin/mvn" <<EOF
#!/bin/sh
JAVA_HOME="$JAVA_HOME_PIN"; export JAVA_HOME
exec "$DEST/apache-maven-$MAVEN_VERSION/bin/mvn" "\$@"
EOF
chmod +x "$DEST/bin/mvn"
cat > "$DEST/bin/jadx" <<EOF
#!/bin/sh
JAVA_HOME="$JAVA_HOME_PIN"; export JAVA_HOME
exec "$DEST/jadx-$JADX_VERSION/bin/jadx" "\$@"
EOF
chmod +x "$DEST/bin/jadx"
for t in java javac javap jar; do
  cat > "$DEST/bin/$t" <<EOF
#!/bin/sh
exec "$JAVA_HOME_PIN/bin/$t" "\$@"
EOF
  chmod +x "$DEST/bin/$t"
done
# The REA MCP server as the harness starts it (the env file below is merged into its MCP config).
cat > "$DEST/bin/rea-mcp" <<EOF
#!/bin/sh
exec "$NODE_BIN" "$REA_ENTRY" mcp "\$@"
EOF
chmod +x "$DEST/bin/rea-mcp"
cat > "$DEST/rea.env" <<EOF
REA_JADX_MCP_JAR=$DEST/lib/jadx-headless-mcp-$JADX_MCP_VERSION-all.jar
JAVA_HOME=$JAVA_HOME_PIN
REA_JADX_OPERATION_TIMEOUT_MS=600000
EOF

{
  echo "# lrae jira-re toolchain (no timestamp: the manifest hash must only change when a tool does)"
  echo "# java: $("$JAVA_HOME_PIN/bin/java" -version 2>&1 | head -1)  ($JAVA_HOME_PIN)"
  echo "# node: $("$NODE_BIN" --version)  ($NODE_BIN)"
  echo "# rea-agents $REA_VERSION, jadx $JADX_VERSION, vineflower $VINEFLOWER_VERSION, cfr $CFR_VERSION, procyon $PROCYON_VERSION, jadx-headless-mcp $JADX_MCP_VERSION, maven $MAVEN_VERSION"
  sort -k2 "$MANIFEST.tmp"
} > "$MANIFEST"
rm -f "$MANIFEST.tmp"

# Smoke checks: every tool starts.
"$DEST/bin/cfr" --version >/dev/null 2>&1 || "$DEST/bin/cfr" --help >/dev/null 2>&1 || die "cfr does not start"
"$DEST/bin/jadx" --version >/dev/null || die "jadx does not start"
"$DEST/bin/javap" -version >/dev/null 2>&1 || die "javap does not start"
"$DEST/bin/mvn" -v >/dev/null || die "mvn does not start"
"$NODE_BIN" "$REA_ENTRY" --version >/dev/null 2>&1 || echo "warning: 'rea --version' failed; check $REA_ENTRY by hand" >&2

echo
echo "installed into $DEST"
echo "  tools:    $DEST/bin  (jadx cfr vineflower procyon java javac javap jar mvn rea-mcp)"
echo "  next:     put the jar in place, run prepare_seed.py, then prime_maven_repo.py (fills $DEST/m2)"
echo "  manifest: $MANIFEST"
echo "  manifest sha256 (put it in spec task.toolchain.manifest_sha256):"
echo "    $(shasum -a 256 "$MANIFEST" | cut -d' ' -f1)"
