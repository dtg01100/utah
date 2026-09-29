"""`20-home-labels.sh` must stamp completion only after its body succeeds.

`projectbluefin/common#1196` splits `version-script` into a read-only check and
a commit: the legacy helper records the version *before* the body runs, so a
hook that fails on first boot is skipped forever after.  `20-home-labels.sh`
was the last Utah hook still written against the legacy contract, so it gets
its own assertions rather than a tree-wide rule -- the remaining hooks are
covered by #259.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = (
    ROOT
    / "system_files/shared/usr/share/ublue-os/privileged-setup.hooks.d"
    / "20-home-labels.sh"
)


class HomeLabelsHookContractTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            line.strip()
            for line in HOOK.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_hook_exists(self):
        self.assertTrue(HOOK.is_file())

    def test_does_not_use_the_legacy_burn_before_body_gate(self):
        self.assertNotIn(
            "version-script home-labels privileged 1",
            self.lines,
            "the legacy helper stamps completion before the body runs",
        )

    def test_checks_before_it_acts(self):
        check = "version-script-check home-labels privileged 1 || exit 0"
        self.assertIn(check, self.lines)
        self.assertLess(
            self.lines.index(check), self.lines.index("restorecon -RF /var/home")
        )

    def test_commits_after_the_body(self):
        self.assertIn("version-script-commit home-labels privileged 1", self.lines)
        self.assertLess(
            self.lines.index("restorecon -RF /var/home"),
            self.lines.index("version-script-commit home-labels privileged 1"),
        )

    def test_body_failure_aborts_before_the_commit(self):
        # `set -e` is what makes a failing restorecon stop the hook instead of
        # running on to record a completion that never happened.
        self.assertIn("set -xeuo pipefail", self.lines)
        self.assertLess(
            self.lines.index("set -xeuo pipefail"),
            self.lines.index("restorecon -RF /var/home"),
        )

    def test_compat_shim_covers_pre_1196_libsetup(self):
        # The pinned COMMON_IMAGE_SHA has no version-script-check/-commit yet,
        # so the shim keeps the hook working under both contracts in either
        # merge order.
        body = HOOK.read_text()
        self.assertIn("if ! declare -F version-script-check >/dev/null; then", body)
        self.assertIn("version-script-commit() { :; }", body)


if __name__ == "__main__":
    unittest.main()
