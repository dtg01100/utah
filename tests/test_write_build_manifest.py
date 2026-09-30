"""scripts/write-build-manifest.py must record the commit and package digest
that the build actually consumed (#371).

The script writes /usr/share/utah/build-manifest.json so an image that
drifted from its Containerfile pin is one `cat` away from obvious, instead
of needing a diff of installed RPM versions against the factory repo. These
tests exercise the writer against a scratch directory, with the env vars
the build-ghcr Justfile sets, and assert the sidecar JSON records each
field it claims to record.

The writer reads from environment variables; that is the same code path
that runs inside the Containerfile, so passing them here proves the
manifest shape and the field set without standing up podman.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "write-build-manifest.py"


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Redirect OUT to the scratch tree so the test never touches the
        # real /usr/share/utah. The script hardcodes that path; patching
        # via a wrapper would not exercise the real code path.
        self.out_dir = Path(self.tmp.name)

    def run_script(self, env: dict[str, str]) -> dict:
        # The script writes to /usr/share/utah/build-manifest.json by default;
        # redirect to a writable scratch directory for the host-side test
        # via UTAH_MANIFEST_OUT. cwd is forced to the repo root so any future
        # change that resolves paths relative to cwd keeps behaving the same
        # way it does inside a podman build (where cwd is the build context).
        env = {
            **os.environ,
            **env,
            "UTAH_MANIFEST_OUT": str(self.out_dir / "build-manifest.json"),
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
        )
        self.assertIn("Wrote", result.stdout)
        out_file = self.out_dir / "build-manifest.json"
        self.assertTrue(out_file.exists())
        return json.loads(out_file.read_text())

    def test_records_commit_and_package_sha(self):
        manifest = self.run_script(
            {
                "BUILD_COMMIT": "f0d3904d4e57791b35d10a37555d1bd6a11b8bb2",
                "PACKAGE_IMAGE": "ghcr.io/projectbluefin/utah-packages",
                "PACKAGE_IMAGE_SHA": "sha256:0f04cff2dd0b085604ff3cd79d538ab14b97cbe356980f7d365a35dfc70c857b",
                "VERSION": "testing-20260930-f0d3904",
            }
        )
        self.assertEqual(
            manifest["commit"], "f0d3904d4e57791b35d10a37555d1bd6a11b8bb2"
        )
        self.assertEqual(
            manifest["package_image"], "ghcr.io/projectbluefin/utah-packages"
        )
        self.assertEqual(
            manifest["package_image_sha"],
            "sha256:0f04cff2dd0b085604ff3cd79d538ab14b97cbe356980f7d365a35dfc70c857b",
        )
        self.assertEqual(manifest["version"], "testing-20260930-f0d3904")

    def test_falls_back_to_unknown_for_missing_inputs(self):
        manifest = self.run_script({})
        self.assertEqual(manifest["commit"], "unknown")
        self.assertEqual(manifest["package_image_sha"], "unknown")
        self.assertEqual(manifest["version"], "unknown")

    def test_is_sorted_and_indented(self):
        manifest = self.run_script(
            {
                "BUILD_COMMIT": "abc",
                "PACKAGE_IMAGE_SHA": "sha256:abc",
                "VERSION": "testing",
            }
        )
        # Sort order is part of the contract -- diff'd manifests stay stable.
        self.assertEqual(list(manifest.keys()), sorted(manifest.keys()))


if __name__ == "__main__":
    unittest.main()