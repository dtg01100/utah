#!/usr/bin/bash
# Print the Flatpak application ids declared by a Brewfile, one per line.
#
# Delegate to the desktop verifier's canonical parse_brewfile implementation.
# Keep source and installed consumers on the same parser rather than copying
# Python's Unicode whitespace rules into another shell regular expression.
#
# Usage:
#   parse-brewfile-flatpaks.sh <path-to-Brewfile>
#   parse-brewfile-flatpaks.sh < <path-to-Brewfile>

set -euo pipefail

if [[ $# -gt 1 ]]; then
    echo "usage: $0 <brewfile>" >&2
    exit 2
fi

case "${BASH_SOURCE[0]##*/}" in
    utah-parse-brewfile-flatpaks)
        verifier="$(dirname "${BASH_SOURCE[0]}")/utah-verify-desktop-contract" ;;
    *)
        verifier="$(dirname "${BASH_SOURCE[0]}")/verify-desktop-contract.py" ;;
esac
exec python3 "$verifier" --flatpaks "${1-/dev/stdin}"
