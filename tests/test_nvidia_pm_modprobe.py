"""The NVIDIA GSP-firmware suspend quirk must survive every Utah build.

On the 595.x open kernel modules Utah builds from NVIDIA's `.run` installer
(``scripts/install-nvidia.sh``), the GSP firmware's default deep idle
configuration crashes during the suspend unload phase. The kernel log
sequence is:

    NVRM: nvAssertFailedNoLog: ... @ kern_bus_vbar2.c:346
    NVRM: kgspHealthCheck_TU102: * GSP-CrashCat Report *
    NVRM: Xid (PCI:0000:01:00): 1, GSP task exception: load access fault
    NVRM: gpuPowerManagementEnter: GSP unload failed at suspend: 0x65
    NVRM: gpuPowerManagementResume: cannot init libOS PMU logging structures
    NVRM: Xid (PCI:0000:01:00): 119, Timeout after Ns of waiting for RPC ...
    BUG: unable to handle page fault for address: 00000000000026b0
    Oops: 0000 in nvEvoDisableVblankSemControl

-- see projectbluefin/utah#492 and NVIDIA/open-gpu-kernel-modules#1271.

The fix is a single modprobe option, ``NVreg_DynamicPowerManagement=0x01``,
in ``system_files/shared/usr/lib/modprobe.d/zz-nvidia-pm.conf``. The file
lives in the shared layer because the option is inert on systems without
the nvidia module (the kernel ignores options for absent modules), so
shipping it on every flavor is safe. The ``zz-`` prefix sorts the file
after common#1176's ``zz-nvidia-suspend.conf``, which pins
``UseKernelSuspendNotifiers=1`` and ``TemporaryFilePath=/var/tmp`` -- a
different failure mode (the driver vetoes suspend), but a sibling quirk
that also has to keep working.

These tests guard three independent regressions:

- the file disappears from the source tree (CI never builds an image with
  the option set),
- the option is removed or mutated to the default ``0x02`` value (silent
  drift back to the crashing behaviour, no kernel-level audit trail),
- the option is left in place but the sort order breaks -- the driver
  package's ``nvidia.conf`` ships at ``/usr/lib/modprobe.d/nvidia.conf``;
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
        """The 0x01 value is the workaround. 0x02 (the default that
        crashes) and 0x03 (uncommitted / vendor experiment) must both be
        rejected on sight."""
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
            "NVreg_DynamicPowerManagement must be 0x01 (the workaround). "
            "0x02 is the driver default that crashes on suspend (#492); "
            "0x03 is uncommitted. Do not change without a tracking issue.",
        )

    def test_filename_starts_with_zz_so(self):
        """The ``zz-`` prefix keeps the assignment sorted after the driver
        package's ``nvidia.conf`` and after common#1176's
        ``zz-nvidia-suspend.conf``. Last assignment in modprobe.d wins, so
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
        content = PM_CONF.read_text()
        for forbidden in (
            "UseKernelSuspendNotifiers",
            "TemporaryFilePath",
        ):
            self.assertNotIn(
                forbidden,
                content,
                f"{PM_CONF.relative_to(ROOT)} must not touch "
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