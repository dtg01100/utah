#!/usr/bin/env python3
"""Write /usr/share/utah/build-manifest.json with the inputs the build consumed.

The image labels carry the same fields (Containerfile LABEL block), but labels
are easy to miss in post-mortems and tooling has to read them off the OCI
manifest. A flat JSON document alongside image-info.json is the next-best
thing to having the data in the package set itself: `bootc status --json` and
`podman inspect` both surface it, and a `cat` from the running image is enough
when the registry is unreachable.

What it records:

- `commit`: the full Utah commit SHA the build was dispatched against.
- `package_image`: the package factory reference (without the digest).
- `package_image_sha`: the exact `sha256:` digest the transaction resolved.
  The runner reads the pinned `PACKAGE_IMAGE_SHA` from the checked-out
  Containerfile so this matches the labels even on a stale-checkout build
  (#371). `sha256:0f04...` plus an older `BUILD_COMMIT` is the mismatch
  signature; nothing in CI used to catch it.
- `version`: the value baked into `org.opencontainers.image.version`, so the
  manifest and the label can be diff'd in one place.

Three of the four values (`commit`, `package_image_sha`, `version`) are
also OCI LABELs, so a sanity check on the JSON is just a compare to those
labels. `package_image` has no LABEL counterpart. The values come from
environment variables set by build-ghcr in the Justfile; fallbacks keep
the script invokable from a local build for parity testing without
breaking the contract.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# UTAH_MANIFEST_OUT lets the host test suite redirect the sidecar to a
# scratch directory; the default is the image's real /usr/share/utah. The
# override is a test-only path; nothing in CI sets it.
OUT = Path(os.environ.get("UTAH_MANIFEST_OUT", "/usr/share/utah/build-manifest.json"))


def main() -> int:
    manifest = {
        "commit": os.environ.get("BUILD_COMMIT", "unknown"),
        "package_image": os.environ.get(
            "PACKAGE_IMAGE", "ghcr.io/projectbluefin/utah-packages"
        ),
        "package_image_sha": os.environ.get("PACKAGE_IMAGE_SHA", "unknown"),
        "version": os.environ.get("VERSION", "unknown"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())