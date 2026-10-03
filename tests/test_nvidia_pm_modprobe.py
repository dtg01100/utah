"""The NVIDIA GSP-firmware suspend quirk must survive every Utah build.

On the 595.x open kernel modules Utah builds from NVIDIA's `.run` installer
(``scripts/install-nvidia.sh``), the GSP firmware crashes during the suspend
unload phase on Turing notebooks (the reporter's #492 hardware is a GTX 1650
Ti Mobile). The kernel log sequence is:

    NVRM: nvAssertFailedNoLog: ... @ kern_bus_vbar2.c:346
    NVRM: kgspHealthCheck_TU102: * GSP-CrashCat Report *
    NVRM: Xid (PCI:0000:01:00): 1, GSP task exception: load access fault
    NVRM: gpuPowerManagementEnter: GSP unload failed at suspend: 0x65
    NVRM: gpuPowerManagementResume: cannot init libOS PMU logging structures
    NVRM: Xid (PCI:0000:01:00): 119, Timeout after Ns of waiting for RPC ...
    BUG: unable to handle page fault for address: 00000000000026b0
    Oops: 0000 in nvEvoDisableVblankSemControl

-- see projectbluefin/utah#492.

NVIDIA's RTD3 documentation (Chapter 22, RTD3 Power Management, ``595.71.05``)
defines ``NVreg_DynamicPowerManagement`` with four values. The driver default
is ``0x03``: on Ampere-or-newer notebooks this translates to ``0x02``
(fine-grained runtime D3); on pre-Ampere notebooks (including the reporter's
Turing GTX 1650 Ti Mobile) and on all desktop SKUs, ``0x03`` *disables*
runtime D3 power management entirely. The candidate workaround is
``NVreg_DynamicPowerManagement=0x01``, which enables coarse-grained runtime
D3 so the driver tears down the GSP firmware state cleanly across suspend.
Reporter-side verification on the actual hardware is owed before the fix is
declared authoritative.

The fix is a single modprobe option, ``NVreg_DynamicPowerManagement=0x01``,
in ``system_files/shared/usr/lib/modprobe.d/zz-nvidia-pm.conf``. The file
lives in the shared layer because the option is inert on systems without
the nvidia module (the kernel ignores options for absent modules), so
shipping it on every flavor is safe. The ``zz-`` prefix sorts the file
after the driver package's ``nvidia.conf`` so this assignment wins any
duplicate. The option does not overlap with common#1176's
``zz-nvidia-suspend.conf``, which pins ``UseKernelSuspendNotifiers=1`` and
``TemporaryFilePath=/var/tmp`` -- a different failure mode (the driver
vetoes suspend), a sibling quirk that has to keep working, and which
lives in projectbluefin/common.

These tests guard three independent regressions:

- the file disappears from the source tree (CI never builds an image with
  the option set),
- the option is removed or mutated away from ``0x01`` (silent drift; the
  values ``0x00``, ``0x02``, and ``0x03`` are all rejected on sight),
- the option is left in place but the ``zz-`` prefix is dropped -- the
  driver package's ``nvidia.conf`` ships at ``/usr/lib/modprobe.d/nvidia.conf``;
  if Utah's file ever loses its ``zz-`` prefix, a duplicate on
  ``nvidia.conf`` would silently win.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "system_files" / "shared"
PM_CONF = SHARED / "usr" / "lib" / "modprobe.d" / "zz-nvidia-pm.conf"


class NvidiaPmModprobeTests(unittest.TestCase):
    def test_the_quirk_file_is_shipped(self):
        """The PM quirk is the fix for #492. Without this file every
        nvidia flavor boots into the same GSP-firmware crash on suspend."""
        self.assertTrue(
            PM_CONF.is_file(),
            f"{PM_CONF.relative_to(ROOT)} must exist -- see "
            "projectbluefin/utah#492 and "
            "docs/skills/kernel-cache.md 'The NVIDIA suspend / PM quirk'",
        )

    def test_pins_DynamicPowerManagement_to_0x01(self):
        """The 0x01 value is the candidate workaround for #492. The
        driver default 0x03 and the fine-grained 0x02 must both be
        rejected on sight; 0x00 must be rejected as it disables RTD3."""
        content = PM_CONF.read_text()
        match = re.search(
            r"^options\s+nvidia\s+NVreg_DynamicPowerManagement\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*$",
            content,
            re.MULTILINE,
        )
        self.assertIsNotNone(
            match,
            f"{PM_CONF.relative_to(ROOT)} must contain "
            "'options nvidia NVreg_DynamicPowerManagement=0x01' on its own line; "
            f"found:\n{content}",
        )
        self.assertEqual(
            match.group(1).lower(),
            "0x01",
            "NVreg_DynamicPowerManagement must be 0x01 (the candidate workaround "
            "for #492). 0x00 disables RTD3 entirely; 0x02 is fine-grained; 0x03 "
            "is the driver default and on Turing notebooks and desktops disables "
            "RTD3, which is the state #492 reproduces in. Do not change without "
            "a tracking issue and reporter-side verification.",
        )

    def test_filename_starts_with_zz_so(self):
        """The ``zz-`` prefix keeps the assignment sorted after the driver
        package's ``nvidia.conf``. Last assignment in modprobe.d wins, so
        dropping the prefix would let a package override the option."""
        self.assertTrue(
            PM_CONF.name.startswith("zz-"),
            f"{PM_CONF.name} must start with 'zz-' so it sorts last in "
            "/usr/lib/modprobe.d/. The nvidia driver's own nvidia.conf can "
            "set NVreg_DynamicPowerManagement; a 'zz-' prefix guarantees "
            "this file's assignment is the last one applied.",
        )

    def test_shared_sibling_quirk_survives(self):
        """common#1176's suspend quirk is a sibling, not a replacement.
        A change here must not silently remove the file that pins
        ``UseKernelSuspendNotifiers=1`` -- that one fixes a different
        failure mode (driver vetoes sleep) and the two coexist.

        The file lives in projectbluefin/common, not in this repository.
        It only lands in the Utah image via ``COPY --from=common
        /system_files/shared`` in the Containerfile, so we cannot
        assert it here -- that is common's testsuite's job. What we
        CAN assert is that Utah's own quirk does not regress into the
        overlap region: nothing in this file may set
        ``UseKernelSuspendNotifiers`` or ``TemporaryFilePath`` to a
        different value than common ships, because that would be a
        silent override of a sibling quirk Utah does not own."""
        # Strip comments before scanning for option assignments: the
        # header legitimately names common#1176's options to explain
        # why this file does not also set them, but the assertions are
        # about the *assignment* surface (the `options` lines), not the
        # prose.
        options_lines = "\n".join(
            line
            for line in PM_CONF.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        for forbidden in (
            "UseKernelSuspendNotifiers",
            "TemporaryFilePath",
        ):
            self.assertNotIn(
                forbidden,
                options_lines,
                f"{PM_CONF.relative_to(ROOT)} must not assign "
                f"{forbidden}; that is common#1176's quirk and lives "
                "in system_files/shared/usr/lib/modprobe.d/zz-nvidia-suspend.conf. "
                "Setting it here would silently override common's value.",
            )

    def test_comment_documents_the_issue(self):
        """The header is the runtime contract for whoever next touches
        the file. It has to name the issue, the signature in the kernel
        log, and the trade-off (idle power), so a future change has the
        context to know what it is about to break."""
        content = PM_CONF.read_text()
        self.assertIn(
            "projectbluefin/utah#492",
            content,
            "the file's header must cite #492 so the regression search "
            "lands on this fix rather than re-deriving the workaround",
        )
        self.assertIn(
            "Xid",
            content,
            "the kernel log signature (Xid 1 / Xid 119) is the only "
            "diagnostic a sysadmin gets on a hung black screen; it has "
            "to be in the header for future debugging",
        )
        self.assertIn(
            "NVreg_DynamicPowerManagement=0x01",
            content,
            "the exact option assignment has to be in the header as "
            "well as in the option line, because the header is the "
            "first thing anyone looks at when the value needs a second "
            "opinion",
        )


if __name__ == "__main__":
    unittest.main()
