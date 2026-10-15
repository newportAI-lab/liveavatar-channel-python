#!/bin/sh
# Fail a commit or CI check unless this SDK's version number went up.
# Skip only when the author explicitly opts out. See AGENTS.md.
set -eu

cd "$(dirname "$0")/.."
root=$(git rev-parse --show-toplevel)
cd "$root"
mode=${1:-staged}
base=${2:-}

if [ "$mode" = "ci" ]; then
  if git log --format=%B "${base}..HEAD" | grep -qx 'SDK-Version-Bump: skip'; then
    echo "SDK version bump skipped by commit message."
    exit 0
  fi
fi

if [ -f liveavatar-channel-sdk/pom.xml ]; then
  file=liveavatar-channel-sdk/pom.xml
  extract() {
    awk '
      /<artifactId>liveavatar-channel-sdk<\/artifactId>/ { found=1 }
      found && /<version>/ {
        sub(/.*<version>/, "")
        sub(/<\/version>.*/, "")
        print
        exit
      }
    '
  }
elif [ -f pyproject.toml ]; then
  file=pyproject.toml
  extract() {
    awk -F '"' '/^version = / { print $2; exit }'
  }
else
  echo "No SDK version file found. Expected liveavatar-channel-sdk/pom.xml or pyproject.toml."
  exit 1
fi

read_old() {
  git show "$1:$file" | extract
}

if [ "$mode" = "ci" ]; then
  old=$(read_old "$base")
  new=$(read_old HEAD)
else
  old=$(read_old HEAD)
  if git diff --cached --quiet -- "$file"; then
    new=$old
  else
    new=$(git show ":$file" | extract)
  fi
fi

greater() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    split(a, A, ".")
    split(b, B, ".")
    for (i = 1; i <= 3; i++) {
      x = A[i] + 0
      y = B[i] + 0
      if (x > y) exit 0
      if (x < y) exit 1
    }
    exit 1
  }'
}

require_changelog() {
  name=$1
  if [ "$mode" = "ci" ]; then
    content=$(git show "HEAD:$name" 2>/dev/null || true)
  else
    if ! git diff --cached --name-only -- "$name" | grep -q .; then
      echo "Stage $name and add this heading: ## [$new] - YYYY-MM-DD"
      exit 1
    fi
    content=$(git show ":$name")
  fi
  if ! printf '%s\n' "$content" | grep -q "^## \[$new\]"; then
    echo "$name must contain this heading: ## [$new] - YYYY-MM-DD"
    exit 1
  fi
}

if greater "$new" "$old"; then
  require_changelog CHANGELOG.md
  require_changelog CHANGELOG.zh-CN.md
  echo "SDK version increased: $old -> $new"
  exit 0
fi

cat <<EOF
SDK version was not increased.
File: $file
Current version: $old
Version in this change: $new

This SDK must increase its version on every commit.
- Compatible addition or fix: increase the last number (1.3.1 -> 1.3.2).
- Breaking change: increase the middle number and reset the last number to 0.

Show the old and new version to the person making the change and wait for a yes before committing.
Do not skip this unless that person explicitly says not to bump the version.

To skip, put this exact line in the commit message:
SDK-Version-Bump: skip
EOF
exit 1
