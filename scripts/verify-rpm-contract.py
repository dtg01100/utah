#!/usr/bin/env python3
"""Assert that Utah actually contains its Bluefin and GNOME 51 RPM contracts.

Mirrors assert_packages_present from projectbluefin/bluefin's
build_files/shared/package-lib.sh: name every missing package, once.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

# The NVIDIA userspace no longer arrives as RPMs. UBlue's akmods bundle used to
# supply nvidia-driver, nvidia-driver-cuda and nvidia-container-toolkit, but it
# publishes nothing for Hummingbird's kernel, so install-nvidia.sh builds the
# open module from NVIDIA's own source and installs the matching userspace from
# the same payload. Those files are what the image needs; the RPM names were
# only ever how they happened to arrive.
#
# nvidia-container-toolkit still arrives as an RPM, from NVIDIA own repository
# rather than from the akmods bundle, so it is asserted by name. It was recorded
# here as a real loss on the reasoning that the bundle was unusable; the bundle
# was one source, not the only one.
NVIDIA_PACKAGES: tuple[str, ...] = ("nvidia-container-toolkit",)


def section(path: Path, name: str) -> list[str]:
    data = tomllib.loads(path.read_text())
    return list(data.get(name, {}).get("packages", []))


def is_installed(pkg: str) -> bool:
    return subprocess.run(
        ["rpm", "-q", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("overlay", type=Path, nargs="?", default=None)
    args = parser.parse_args()
    overlay = args.overlay or args.manifest.with_name("utah.toml")

    flavor = os.environ.get("IMAGE_FLAVOR", "main")
    unavailable = set(section(overlay, "unavailable"))

    # Prefer the set install-packages.py actually resolved. Recomputing it here
    # is what let the two drift once: install added [fedora_v<major>] for the
    # running release and this check never did, so a contract package was
    # installed but never verified -- it could have gone missing silently. The
    # file is written by the install step, so in an image build it is always
    # present; the manifest path below is the off-image fallback for --check,
    # which asserts nothing about installation.
    resolved = Path("/usr/share/utah/contract.txt")
    if resolved.exists():
        # The contract file is the dedup'd install set: Bluefin first, then
        # each overlay section in the order install reads them. To attribute
        # names back to their owning section, walk the contract in order and
        # claim each name from the first section it appears in.
        contract = [line for line in resolved.read_text().split() if line]
        gnome_names = set(section(overlay, "gnome"))
        parity_names = set(section(overlay, "parity"))
        hardware_names = set(section(overlay, "hardware"))
        service_names = set(section(overlay, "services"))
        fedora_names = set(section(args.manifest, "fedora"))
        bluefin = []
        gnome = []
        parity = []
        hardware = []
        services = []
        for pkg in contract:
            if pkg in fedora_names:
                bluefin.append(pkg)
            elif pkg in gnome_names:
                gnome.append(pkg)
            elif pkg in parity_names:
                parity.append(pkg)
            elif pkg in hardware_names:
                hardware.append(pkg)
            elif pkg in service_names:
                services.append(pkg)
            # Anything outside fedora and the overlay sections is the
            # version-specific Bluefin section (fedora_v<major>); treat it as
            # Bluefin too. install writes the dedup'd contract in install
            # order, so the name is the right one for "is this present".
            else:
                bluefin.append(pkg)
    else:
        bluefin = [p for p in section(args.manifest, "fedora") if p not in unavailable]
        gnome = section(overlay, "gnome")
        parity = section(overlay, "parity")
        hardware = section(overlay, "hardware")
        services = section(overlay, "services")
    nvidia = list(NVIDIA_PACKAGES) if "nvidia" in flavor else []
    # Mirror install-packages.contract(): a name in both [fedora] and one of
    # the overlay sections (the #382 case for fish/zsh/ppp/libgda/libgda-sqlite)
    # appears in the install set exactly once, with the Bluefin order winning.
    # The verifier used to assert uniqueness without dedup, which started
    # failing the moment a stale [unavailable] entry moved into the contract.
    # Per-section counts track which section first owns each name so the
    # printed totals add up to len(expected) rather than double-counting.
    section_of: dict[str, str] = {}
    counts: dict[str, int] = {"bluefin": 0, "gnome": 0, "parity": 0,
                              "hardware": 0, "services": 0, "nvidia": 0}
    expected: list[str] = []
    for pkg in bluefin:
        if pkg not in section_of:
            section_of[pkg] = "bluefin"
            counts["bluefin"] += 1
            expected.append(pkg)
    for pkg in gnome:
        if pkg not in section_of:
            section_of[pkg] = "gnome"
            counts["gnome"] += 1
            expected.append(pkg)
    for pkg in parity:
        if pkg not in section_of:
            section_of[pkg] = "parity"
            counts["parity"] += 1
            expected.append(pkg)
    for pkg in hardware:
        if pkg not in section_of:
            section_of[pkg] = "hardware"
            counts["hardware"] += 1
            expected.append(pkg)
    for pkg in services:
        if pkg not in section_of:
            section_of[pkg] = "services"
            counts["services"] += 1
            expected.append(pkg)
    for pkg in nvidia:
        if pkg not in section_of:
            section_of[pkg] = "nvidia"
            counts["nvidia"] += 1
            expected.append(pkg)

    print(
        f"Verifying {counts['bluefin']} Bluefin packages, {counts['gnome']} GNOME desktop packages,"
        f" {counts['parity']} parity packages,"
        f" {counts['hardware']} firmware packages,"
        f" {counts['services']} desktop service packages, and {counts['nvidia']} NVIDIA packages",
        flush=True,
    )
    if args.check:
        assert len(set(expected)) == len(expected), "RPM contract contains duplicate package names"
        return 0

    missing = [pkg for pkg in expected if not is_installed(pkg)]
    if missing:
        print(
            f"ERROR: {len(missing)} of {len(expected)} contract packages are not installed:",
            file=sys.stderr,
        )
        for pkg in missing:
            print(f"  - {pkg}", file=sys.stderr)
        return 1
    print(f"All {len(expected)} contract packages are present.")

    if "nvidia" not in flavor:
        return 0

    # Assert what a source build actually produces: a module for every kernel
    # the image can boot, and the userspace that goes with it.
    ogc = Path("/usr/lib/utah/ogc-kernel-release")
    ogc_release = ogc.read_text().strip() if ogc.exists() else None

    # This deliberately mirrors install-nvidia.sh, including its fallback. `rpm
    # -q kernel` is not reliable here: `kernel` is a metapackage a bootc base may
    # not carry, and on failure rpm prints "package kernel is not installed" to
    # stdout -- whose last word is "installed", which this used to accept as a
    # release string and then report a missing module for a kernel of that name.
    base = subprocess.run(["rpm", "-q", "kernel", "--qf", "%{VERSION}-%{RELEASE}.%{ARCH}\n"],
                          capture_output=True, text=True).stdout.split()
    base = base[-1].strip() if base else ""
    # Identify the kernel by its module tree, not by a build tree. A build tree
    # only exists while kernel-devel is installed, and install-nvidia.sh removes
    # that again once the module is compiled -- 215 MiB there is no reason to
    # ship. Requiring one here meant plain nvidia could never pass: the OGC
    # flavors only satisfied it because install-ogc-kernel.sh leaves its own
    # tree behind. A module tree is what says the image can boot that kernel,
    # which is the thing being asserted.
    if not base or not Path(f"/usr/lib/modules/{base}").is_dir():
        candidates = sorted(d.name for d in Path("/usr/lib/modules").glob("*")
                            if d.name != ogc_release and d.is_dir())
        if not candidates:
            print("ERROR: no kernel module tree found; cannot verify NVIDIA modules",
                  file=sys.stderr)
            return 1
        base = candidates[-1]

    releases = [base]
    if flavor == "nvidia-gaming":
        releases.append(ogc.read_text().strip())

    failed = False
    for release in releases:
        release = release.strip() if release else ""
        if not release:
            print("ERROR: empty kernel release; no kernel to check NVIDIA module against",
                  file=sys.stderr)
            failed = True
            continue
        module = Path(f"/usr/lib/modules/{release}/extra/nvidia/nvidia.ko")
        if not module.exists():
            print(f"ERROR: NVIDIA module missing for kernel {release}", file=sys.stderr)
            failed = True
    for path in (Path("/usr/bin/nvidia-smi"), Path("/usr/lib/utah/nvidia-driver-version")):
        if not path.exists():
            print(f"ERROR: NVIDIA userspace incomplete, {path} is missing", file=sys.stderr)
            failed = True
    if failed:
        return 1
    version = Path("/usr/lib/utah/nvidia-driver-version").read_text().strip()
    print(f"NVIDIA {version} present for: {', '.join(releases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
