"""Exercise Utah's custom recipes without network, uploads or MOK writes."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "system_files/shared/usr/share/ublue-os/just/60-custom.just"


@unittest.skipUnless(shutil.which("just") and shutil.which("jq"), "requires just and jq")
class UjustOverridesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("cat", "mktemp", "rm", "jq", "grep", "sh"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.just = shutil.which("just")
        self.log = self.root / "calls"
        self.env = dict(os.environ, PATH=str(self.bin), TMPDIR=str(self.root),
                        CALLS=str(self.log))
        info = self.root / "image-info.json"
        info.write_text(json.dumps({"image-tag": "testing", "image-name": "utah"}))
        self.env["IMAGE_INFO_FILE"] = str(info)
        self.mock("repo-helper", 'echo "repo $*" >> "$CALLS"; echo projectbluefin/utah')
        self.env["UBLUE_IMAGE_REPO_BIN"] = str(self.bin / "repo-helper")
        for name in ("bootc", "flatpak", "uname", "lscpu", "lsblk", "free"):
            self.mock(name, f'echo "{name} diagnostic"')
        for name in ("sudo", "mokutil"):
            self.mock(name, f'echo "{name}" >> "$CALLS"; exit 99')
        self.mock("curl", 'echo "curl $*" >> "$CALLS"; echo \'{"body":"# Release notes"}\'')
        # Common imports defaults before custom recipes at the same depth.
        # Utah wraps that entry point to make its override import shallower.
        original = self.root / "default.just"
        original.write_text("device-info:\n    exit 99\nchangelogs:\n    exit 99\n"
                            "enroll-secure-boot-key:\n    exit 99\n")
        common = self.root / "00-common.just"
        common.write_text('set allow-duplicate-recipes\n_default:\n    @echo common-default\n'
                          'unrelated:\n    @echo common-unrelated\n'
                          f'import "{original}"\n'
                          f'import "{RECIPES}"\n')
        self.entry = self.root / "entry.just"
        entry = (RECIPES.parent / "00-entry.just").read_text()
        self.entry.write_text(entry.replace("/usr/share/ublue-os/just/00-common.just", str(common))
                              .replace("/usr/share/ublue-os/just/60-custom.just", str(RECIPES)))

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_recipe(self, name):
        return subprocess.run([self.just, "--justfile", str(self.entry), name],
                              env=self.env, text=True, capture_output=True)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_common_default_and_unrelated_recipes_survive(self):
        result = subprocess.run([self.just, "--justfile", str(self.entry)],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "common-default\n")
        result = self.run_recipe("unrelated")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "common-unrelated\n")

    def test_device_info_without_fpaste_is_local_and_cleans_report(self):
        result = self.run_recipe("device-info")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("bootc", "flatpak", "uname", "lscpu", "lsblk", "free"):
            self.assertIn(f"{name} diagnostic", result.stdout)
        self.assertIn("fpaste is unavailable", result.stderr)
        self.assertEqual(self.calls(), "")
        self.assertEqual(list(self.root.glob("utah-device-info.*")), [])

    def setup_fpaste(self, consent):
        self.mock("gum", f'echo confirm >> "$CALLS"; exit {0 if consent else 1}')
        self.mock("fpaste", 'if [[ "$*" == "--sysinfo --printonly" ]]; then\n'
                  'echo sysinfo\nelse\necho upload >> "$CALLS"; cat\nfi')

    def test_device_upload_requires_confirmation(self):
        self.setup_fpaste(False)
        result = self.run_recipe("device-info")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sysinfo", result.stdout)
        self.assertEqual(self.calls(), "confirm\n")

    def test_device_upload_after_confirmation(self):
        self.setup_fpaste(True)
        result = self.run_recipe("device-info")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), "confirm\nupload\n")
        self.assertEqual(list(self.root.glob("utah-device-info.*")), [])

    def test_device_failure_cleans_report_and_does_not_upload(self):
        self.setup_fpaste(True)
        self.mock("bootc", "exit 7")
        result = self.run_recipe("device-info")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), "")
        self.assertEqual(list(self.root.glob("utah-device-info.*")), [])

    def test_changelogs_without_glow_prints_release(self):
        result = self.run_recipe("changelogs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "# Release notes\n")
        self.assertIn("repo --default projectbluefin/bluefin utah testing", self.calls())
        self.assertIn("https://api.github.com/repos/projectbluefin/utah/releases/latest", self.calls())

    def test_changelogs_with_glow(self):
        self.mock("glow", 'echo "glow $*" >> "$CALLS"; cat')
        result = self.run_recipe("changelogs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "# Release notes\n")
        self.assertIn("glow -p", self.calls())

    def test_changelogs_preserves_specific_release_selection(self):
        Path(self.env["IMAGE_INFO_FILE"]).write_text(json.dumps(
            {"image-tag": "stable", "image-name": "utah"}))
        (self.bin / "grep").unlink()
        self.mock("grep", "echo 20261001")
        self.mock("curl", 'echo "curl $*" >> "$CALLS"; '
                  'echo \'[{"tag_name":"stable-20261001","body":"Specific release"}]\'')
        result = self.run_recipe("changelogs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Specific release\n")
        self.assertNotIn("releases/latest", self.calls())

    def test_changelogs_propagates_http_failure(self):
        self.mock("curl", "exit 22")
        result = self.run_recipe("changelogs")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_changelogs_rejects_missing_release_body(self):
        self.mock("curl", "echo '{}'")
        result = self.run_recipe("changelogs")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_enrollment_explains_missing_support_without_privileged_calls(self):
        result = self.run_recipe("enroll-secure-boot-key")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not yet ship", result.stderr)
        self.assertIn("https://github.com/projectbluefin/utah/issues/395", result.stderr)
        self.assertEqual(self.calls(), "")

    def test_report_override_runs_bonedigger_with_utah_image_repo(self):
        # projectbluefin/utah#446: ujust report on Utah was falling through
        # common's routing grammar and landing in projectbluefin/common.
        # Utah overrides `report` in 60-custom.just so bonedigger-report
        # routes through the local utah-image-repo shim. The fixture below
        # wires a fake bonedigger-report into the same import graph the image
        # ships, then runs `just --show report` to verify the override is the
        # version `just` resolves at the entry point (the shallower import
        # depth wins on just >= 1.56).
        self.mock("bonedigger-report", 'echo "bonedigger $*" >> "$CALLS"; '
                  'echo "${UBLUE_IMAGE_REPO_BIN:-unset}" >> "$CALLS"')
        result = subprocess.run([self.just, "--justfile", str(self.entry),
                                 "--show", "report"],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Override body must set the UBLUE_IMAGE_REPO_BIN env to the shim path
        # and call bonedigger-report through the recipe.
        self.assertIn("bonedigger-report", result.stdout)
        self.assertIn("/usr/local/libexec/utah-image-repo", result.stdout)
        # And the dynamic routing behaviour must surface the shim path at
        # runtime, not the default ublue-image-repo from common.
        self.assertNotIn("/usr/libexec/ublue-image-repo", result.stdout)
        text = RECIPES.read_text()
        match = re.search(
            r"report \*args:\s*\n"
            r"(?P<body>(?:[ \t].*\n|\s*\\\s*\n)+)",
            text,
        )
        self.assertIsNotNone(
            match,
            "ujust report recipe must exist with a multi-line body",
        )
        body = match.group("body")
        self.assertIn(
            'UBLUE_IMAGE_REPO_BIN="/usr/local/libexec/utah-image-repo"',
            body,
            "ujust report must set UBLUE_IMAGE_REPO_BIN to the Utah shim",
        )
        self.assertIn(
            "/usr/libexec/bonedigger-report",
            body,
            "ujust report must still call bonedigger-report",
        )

if __name__ == "__main__":
    unittest.main()
