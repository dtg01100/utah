#!/usr/bin/env python3
"""Write /usr/share/utah/build-manifest.json with the inputs the build consumed.

The image labels carry three of these fields (Containerfile LABEL block), but
reading a label means reaching for the OCI manifest: `podman inspect` against
a registry the post-mortem may not be able to reach, or `skopeo inspect`. The
sidecar is a flat JSON document alongside image-info.json inside the image
itself, so `cat /usr/share/utah/build-manifest.json` on the running host
answers the same question offline -- and it carries `package_image`, which no
label does.

What it records:

- `commit`: the full Utah commit SHA the build was invoked from.
- `package_image`: the package factory reference (without the digest).
- `package_image_sha`: the exact `sha256:` digest the transaction resolved.
  The Containerfile's final stage re-declares `ARG PACKAGE_IMAGE_SHA` bare,
  so it inherits whatever `FROM ${PACKAGE_IMAGE_REF}` consumed and is fed
  here unchanged; no runner step passes it. That is what keeps the sidecar
  from naming a digest the build did not install (#371) -- `sha256:0f04...`
  next to an older `commit` is the mismatch signature.
- `version`: the value baked into `org.opencontainers.image.version`, so the
  manifest and the label can be diff'd in one place.

Three of the four values (`commit`, `package_image_sha`, `version`) are also
OCI LABELs (`org.opencontainers.image.revision`,
`io.projectbluefin.utah.factory-digest`, `org.opencontainers.image.version`),
so a sanity check on the JSON is just a compare to those labels.
The OCI label name is ``factory-digest`` (projectbluefin/utah#374), not
``package_image_sha``; the JSON field keeps ``package_image_sha`` because
that is the sidecar's logical name. ``package_image`` has no LABEL
counterpart. The values come from environment variables the Containerfile
passes through from its ARGs; fallbacks keep the script invokable from a
local build for parity testing without breaking the contract.
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
