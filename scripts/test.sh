#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$project_dir/.runtime/system/usr/bin:$PATH"
export LD_LIBRARY_PATH="$project_dir/.runtime/system/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XDG_DATA_HOME="$project_dir/.runtime/data"
test_config="$(mktemp -d "${TMPDIR:-/tmp}/ts-test-config.XXXXXXXX")"
trap 'rm -rf -- "$test_config"' EXIT
export XDG_CONFIG_HOME="$test_config"
export XDG_CACHE_HOME="$project_dir/.runtime/cache"
export ARGOS_PACKAGES_DIR="$project_dir/.runtime/data/argos-translate/packages"
export TS_REQUIRE_INTEGRATION=1
export PYTHONDONTWRITEBYTECODE=1
"$project_dir/bin/python" -m pytest "$project_dir/tests" -p no:cacheprovider "$@"
