#!/usr/bin/bash
# Relabel /var/home once on systems installed before the image fixed its
# home-root label (scripts/fix-home-labels.sh, #261). There, /var/home and
# every home directory were created as default_t, so accounts-daemon could not
# add users and home directories carried the wrong type. /var persists across
# updates, so a new image alone does not correct existing labels.
#
# A restorecon that fails persistently (a home directory on a mount that rejects
# xattr relabel, for example) is never committed, so the full recursive relabel
# of /var/home is retried on every boot. That retry is the intended contract
# from common#1196, but it is a recurring cost on a machine that cannot complete
# the relabel; there is no attempt cap.

# shellcheck source=/dev/null
source /usr/lib/ublue/setup-services/libsetup.sh

# Compat shim: common libsetup.sh builds older than projectbluefin/common #1196
# have only version-script, which records the version before the body runs, and
# no version-script-check/version-script-commit pair. Fall back to that legacy
# gate and make the commit a no-op, so this hook works against both contracts.
if ! declare -F version-script-check >/dev/null; then
    version-script-check() { version-script "$@"; }
    version-script-commit() { :; }
fi

version-script-check home-labels privileged 1 || exit 0

set -xeuo pipefail
restorecon -RF /var/home

# Record success only after the body ran, so a failing first-boot hook retries
# next boot instead of being permanently skipped (common #1196 new contract).
version-script-commit home-labels privileged 1
