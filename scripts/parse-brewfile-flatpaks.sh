#!/usr/bin/bash
# Print the Flatpak application ids declared by a Brewfile, one per line.
#
# Single source of truth for the parse: scripts/verify-desktop-contract.py
# does the same in Python (parse_brewfile, regex ^flatpak\s+"([^"]+)"\s*$),
# and a Brewfile line such as `flatpak "id", args: "x"` is rejected on both
# sides so the contract check and the build-time bake can never disagree
# about which ids the file declares (issue #510). Keep the two filters
# aligned; tests/test_iso_ci.py asserts the bash helper and the Python
# parser produce the same list from the same Brewfile.
#
# Usage:
#   parse-brewfile-flatpaks.sh <path-to-Brewfile>
#   parse-brewfile-flatpaks.sh < <path-to-Brewfile>

set -euo pipefail

if [[ $# -gt 1 ]]; then
    echo "usage: $0 <brewfile>" >&2
    exit 2
fi

# POSIX ERE form of the Python regex. Trailing arguments after the closing
# quote are rejected, matching verify-desktop-contract.py's stricter
# definition -- the awk -F'"' forms this used to inline accepted lines
# like `flatpak "id", args: "x"` and silently widened the declared set
# past what the contract verifier counted. sed strips leading whitespace
# first because the Python parser does too, so an indented `flatpak "id"`
# line is accepted here the same way it is there.
# `|| true` keeps set -e quiet when grep finds nothing: a Brewfile with no
# declared flatpaks is otherwise indistinguishable from a broken pipe.
sed -E 's/^[[:space:]]+//' "$@" \
    | { grep -E '^flatpak[[:space:]]+"[^"]+"[[:space:]]*$' || true; } \
    | sed -E 's/^flatpak[[:space:]]+"([^"]+)"[[:space:]]*$/\1/'
