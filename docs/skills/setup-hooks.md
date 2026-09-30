---
name: setup-hooks
version: "1.0"
last_updated: "2026-09-27"
id: setup-hooks
one_line_purpose: Change a first-boot setup hook without breaking the once-only contract.
entry_point: docs/skills/setup-hooks.md
category: meta
mcp_compliance_level: partial
optimization_status: draft
status: active
dependencies: []
tags: [hooks, first-boot, version-script, libsetup]
description: >-
  First-boot setup hooks stamp completion through libsetup.sh. Use when editing
  a hook, migrating one off the legacy `version-script` gate, or debugging a
  hook that never runs or runs every boot.
metadata:
  type: procedure
---

# Setup hooks

Hooks live in two directories:

- `system_files/shared/usr/share/ublue-os/user-setup.hooks.d/` — runs per user.
- `system_files/shared/usr/share/ublue-os/privileged-setup.hooks.d/` — runs via
  pkexec as root, when a privileged action is needed.

Every hook sources `/usr/lib/ublue/setup-services/libsetup.sh` (shipped by
`projectbluefin/common` through the pinned `COMMON_IMAGE_SHA`).

## The once-only contract

A hook must stamp completion **after** its body succeeds, never before:

```bash
version-script-check <name> <scope> 1 || exit 0   # read-only: have we done this?

set -xeuo pipefail
# body
version-script-commit <name> <scope> 1            # record success
```

`projectbluefin/common#1196` split the old `version-script` helper in two. The
legacy helper recorded the version *before* the body ran, so a hook that failed
on first boot — a transient missing binary, an unreadable DMI node — was
skipped forever after. The new pair leaves the gate read-only and lets the hook
record success itself, so a failure retries on the next boot.

Two consequences to keep in mind when writing the body:

1. **Use `set -e`.** Without it the hook runs on past a failed body and commits
   a completion that never happened.
2. **Split skip paths by whether the condition can change.** A deliberate skip
   (wrong vendor, karg already applied) commits before `exit 0` so the hook
   stops re-running every boot. A transient skip (DMI unreadable, dependency
   missing) exits *without* committing so it retries.

## Compat shim

The pinned common image has no `version-script-check`/`version-script-commit`
until projectbluefin/common#1196 lands. Each hook therefore defines a shim so it
works in either merge order:

```bash
if ! declare -F version-script-check >/dev/null; then
    version-script-check() { version-script "$@"; }
    version-script-commit() { :; }
fi
```

As of this writing only `20-home-labels.sh` carries the shim. The other Utah
hooks (`10-tailscale.sh`, `11-framework-ucsi-workaround.sh`, `99-flatpaks.sh`,
`user-setup.hooks.d/20-framework.sh`) still call the legacy `version-script`
helper, pending #259.

## Tests

`tests/test_setup_hook_version_contract.py` asserts the contract on
`20-home-labels.sh`; run the suite with `just test`. `just check` syntax-checks
every hook (`bash -n`) through `scripts/check-script-syntax.py`; there is no
shellcheck gate in the Justfile or CI.
