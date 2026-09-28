#!/usr/bin/bash
# Strip build-time residue that `bootc container lint --fatal-warnings` rejects.
#
# This mirrors the filesystem portion of Bluefin's
# build_files/shared/clean-stage.sh, deliberately: Utah keeps Bluefin's package
# contract, so it inherits Bluefin's image hygiene too. Bluefin's script also
# disables flatpak-add-fedora-repos.service and clears a dnf5 versionlock,
# neither of which exists here.
#
# The three lint checks this satisfies, all seen failing on a real build:
#
#   nonempty-run-tmp  /run/cockpit, /run/dnf and friends. /run is a tmpfs at
#                     runtime, so anything baked into the image is junk.
#   var-log           /var/log/dnf5.log and its rotations, written by the
#                     install step itself.
#   var-tmpfiles      /var/cache/ibus, ldconfig, libX11, swcatalog and ~40 more
#                     directories with no systemd tmpfiles.d entry.

set -eoux pipefail

# Applied as a prefix to every path so the script can be exercised against a
# temporary directory rather than the live filesystem.
CLEAN_ROOT="${CLEAN_ROOT:-/}"

# Everything under /var except the caches bootc expects to survive. This also
# takes /var/log and /var/lib, which is where the remaining lint offenders
# lived -- the ssh-host-keys migration stamp, the ibus registry, ldconfig's
# aux-cache and the swcatalog .xb files are all inside directories removed
# here, so no separate file sweep is needed.
find "${CLEAN_ROOT}/var"/* -maxdepth 0 -type d \! -name cache -exec rm -fr {} \;
# libdnf5 is not among them, despite what this used to say. The Containerfile
# already deletes /var/cache/libdnf5 outright after the main transaction, and
# main ships with no such directory and passes lint, so nothing needs it. What
# put it back on the NVIDIA flavors is the GPG key imported for NVIDIA own
# repository: `dnf clean all` removes the metadata but leaves the keyring, so
# the tree survives, and bootc lint rejects both the untracked directories and
# the key file inside them:
#   d /var/cache/libdnf5/nvidia-container-toolkit-<hash>/pubring
#   var/cache/libdnf5/nvidia-container-toolkit-<hash>/pubring/DDCAE044F796ECB0.pub
find "${CLEAN_ROOT}/var/cache"/* -maxdepth 0 -type d \! -name rpm-ostree -exec rm -fr {} \;

# /run and /tmp are cleared by emptying them, not by replacing them. The
# container runtime bind-mounts /run/.containerenv, so `rm -rf /run` fails with
#     rm: cannot remove '/run/.containerenv': Device or resource busy
# and takes the build with it. A bind mount is not part of the committed layer,
# so what lint sees is only what we leave behind inside these directories.
clear_dir() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
}
clear_dir "${CLEAN_ROOT:?}/run"
clear_dir "${CLEAN_ROOT:?}/tmp"

# The prebuilt kernel and NVIDIA archives the cache image supplies as its base
# layer. They are build input, not image content, and they are large -- three of
# the four flavors would otherwise ship roughly 1.5 GB of tarballs they have
# already unpacked. main never has this directory at all.
rm -rf "${CLEAN_ROOT:?}/utah-cache"

# dnf5 records every transaction in a SQLite database under the sysroot:
# usr/lib/sysimage/libdnf5/transaction_history.sqlite (with its -shm and -wal
# companions). It is build-time metadata -- nothing at runtime reads it -- and
# it carries a wall-clock mtime plus an in-memory page cache, so it both wastes
# space and churns the layer that carries it on every rebuild. Drop it the same
# way the residue above is dropped (utah#313).
for db in transaction_history.sqlite transaction_history.sqlite-shm transaction_history.sqlite-wal; do
    rm -f "${CLEAN_ROOT:?}/usr/lib/sysimage/libdnf5/${db}"
done

# Reproducible builds: a rebuild that changes nothing must produce an identical
# image. dnf, meson and the extension build write wall-clock mtimes into /usr
# and /etc, and chunkah splits those directories across layers, so a changed
# mtime in any tar header changes that layer's digest. Pin every file and
# directory under /usr and /etc to SOURCE_DATE_EPOCH so a layer's digest is a
# function of its content alone, not the CI wall-clock (utah#313). The value is
# a fixed epoch, identical for every build, so the digest no longer depends on
# when the build ran.
#
# -h is load-bearing: without it touch follows symlinks, and a real image tree
# is full of links whose target is not in the image -- /usr/lib/bootc/storage,
# /usr/share/licenses/malcontent/COPYING, the 32-bit libstdc++.a stubs. touch
# then reports "No such file or directory" per broken link and exits non-zero,
# which under `set -e` kills the whole build layer. -h stamps the link itself,
# which is also the mtime that lands in the tar header, so it is the correct
# target here and not merely a way to dodge the error.
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1704067200}"
for base in usr etc; do
    [ -d "${CLEAN_ROOT:?}/${base}" ] || continue
    find "${CLEAN_ROOT}/${base}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
done
