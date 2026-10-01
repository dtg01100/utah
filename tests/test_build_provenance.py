"""Containerfile pins the provenance labels and ARGs #371 depends on.

The Containerfile must declare the build args, write them as LABELs, and
invoke utah-write-build-manifest at the right RUN step. Each of these
is enforced by a literal-string scan: if any one is missing, the
in-image manifest and the OCI labels drift from the inputs the build
recorded, and the very mismatch the labels are meant to surface comes
back through the back door.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINERFILE = ROOT / "Containerfile"


class BuildProvenanceContainerfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = CONTAINERFILE.read_text()

    def test_contains_build_commit_arg(self):
        # The full Utah commit SHA arrives via this ARG. Falling back to
        # `unknown` keeps a hand-run `podman build` from breaking, but
        # nothing about the field is optional.
        self.assertIsNotNone(
            re.search(r"^ARG BUILD_COMMIT=unknown\s*$", self.text, re.MULTILINE),
            "Containerfile is missing ARG BUILD_COMMIT=unknown",
        )

    def test_package_image_sha_arg_is_redeclared_bare(self):
        # Bare (no default) re-declaration in the final stage is what makes
        # the label inherit the global pin on any build, including a plain
        # `podman build` that passes no build-args. A default here would
        # ship `unknown` next to a manifest carrying the real digest.
        self.assertIsNotNone(
            re.search(
                r"^ARG PACKAGE_IMAGE_SHA\s*$",
                self.text,
                re.MULTILINE,
            ),
            "Containerfile is missing the bare ARG PACKAGE_IMAGE_SHA "
            "re-declaration in the final stage",
        )

    def test_revision_label_uses_build_commit(self):
        # org.opencontainers.image.revision is the label post-mortems read
        # first. Pinning it to BUILD_COMMIT (not SHA_HEAD_SHORT) gives the
        # full SHA, which is what the runner captures in GITHUB_SHA.
        self.assertIn(
            'LABEL org.opencontainers.image.revision="${BUILD_COMMIT}"',
            self.text,
        )

    def test_factory_digest_label(self):
        # The factory digest label names the package set a shipped image
        # installed from, without diffing installed RPM versions. It reads
        # the same ARG the sidecar is fed, so the two cannot skew.
        # The label name ``factory-digest`` matches main
        # (projectbluefin/utah#374); keeping one canonical name across
        # the label and the sidecar JSON field is a deliberate split --
        # the JSON field is the sidecar's logical name and stays
        # ``package_image_sha``; the OCI label is the canonical name and
        # matches main.
        self.assertIn(
            'LABEL io.projectbluefin.utah.factory-digest="'
            '${PACKAGE_IMAGE_SHA}"',
            self.text,
        )

    def test_invokes_write_build_manifest(self):
        # The sidecar JSON is what the running image ships; the LABEL is
        # what the OCI manifest ships. Both come from the same env vars,
        # so a single RUN that invokes utah-write-build-manifest with them
        # is enough to keep them in lockstep.
        self.assertIn("/usr/local/libexec/utah-write-build-manifest", self.text)
        self.assertIn('BUILD_COMMIT="${BUILD_COMMIT}"', self.text)
        self.assertIn('PACKAGE_IMAGE_SHA="${PACKAGE_IMAGE_SHA}"', self.text)


if __name__ == "__main__":
    unittest.main()
