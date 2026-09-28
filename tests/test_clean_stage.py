"""scripts/clean-stage.sh must strip build residue without taking the keepers.

The script runs in the final Containerfile layer, and everything it deletes is
deleted from the image every flavor ships. Until now nothing executed it: the
only test that named it at all was the `bash -n` syntax gate, which proves the
file parses and nothing about what it removes. A wrong `-name` filter or a
dropped `\\!` would still parse, and the symptom would be either a `bootc
container lint --fatal-warnings` failure at the end of a full build or, worse,
an image that silently lost /var/cache/rpm-ostree.

The script already carries the seam these tests need: every path it touches is
prefixed with `CLEAN_ROOT`, documented in the script as being there "so the
script can be exercised against a temporary directory rather than the live
filesystem". These tests take it up on that -- they build a scratch tree that
mimics the offenders seen on real builds, run the real script against it, and
assert on the tree that survives.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clean-stage.sh"
SOURCE_DATE_EPOCH = 1704067200  # 2024-01-01T00:00:00Z, the epoch clean-stage pins to


def build_tree(root: Path) -> None:
    """A scratch image tree holding one of each thing the script reasons about.

    The directory names are the ones quoted in the script's own header as the
    lint offenders it exists to remove: /var/log with dnf5 logs, the
    /var/cache/libdnf5 keyring tree the NVIDIA flavors regrew, /run/cockpit and
    the unpacked /utah-cache build input.
    """
    for directory in ("var/log", "var/lib", "var/tmp"):
        (root / directory).mkdir(parents=True)
    (root / "var/log/dnf5.log").write_text("install transaction\n")
    (root / "var/lib/systemd").mkdir()

    # /var/cache survives, but only rpm-ostree survives inside it.
    (root / "var/cache/rpm-ostree").mkdir(parents=True)
    (root / "var/cache/rpm-ostree/repomd.xml").write_text("keep me\n")
    (root / "var/cache/libdnf5/nvidia-container-toolkit-abc123/pubring").mkdir(parents=True)
    (root / "var/cache/libdnf5/nvidia-container-toolkit-abc123/pubring/"
            "DDCAE044F796ECB0.pub").write_text("gpg key\n")
    (root / "var/cache/ibus").mkdir()

    for directory in ("run/cockpit", "run/dnf", "tmp/build-scratch"):
        (root / directory).mkdir(parents=True)
    (root / "run/cockpit/socket").write_text("residue\n")
    (root / "tmp/stray.tmp").write_text("residue\n")

    (root / "utah-cache/kernel-rpms").mkdir(parents=True)
    (root / "utah-cache/kernel-rpms/kernel-7.1.8-ogc1.rpm").write_bytes(b"1.5 GB, pretend\n")
    # The reproducible-build surface: /usr and /etc with files whose mtimes are
    # deliberately far in the future, plus the dnf5 transaction history the
    # script must drop. The mtime test asserts clean-stage pins the former to
    # SOURCE_DATE_EPOCH and removes the latter (utah#313).
    for directory in ("usr/bin", "usr/share/doc", "etc/systemd/system"):
        (root / directory).mkdir(parents=True)
    (root / "usr/bin/tool").write_text("binary\n")
    (root / "usr/share/doc/readme").write_text("doc\n")
    (root / "etc/systemd/system/foo.service").write_text("[Unit]\n")
    # Year 2036 -- well after the epoch the script pins to -- so a failure to
    # normalise is unmistakable rather than a coincidence with the target.
    future = 2085840000
    for path in (root / "usr/bin/tool", root / "usr/share/doc/readme",
                 root / "etc/systemd/system/foo.service"):
        os.utime(path, (future, future))
    # dnf5's per-transaction SQLite database under the sysroot.
    txn = root / "usr/lib/sysimage/libdnf5"
    txn.mkdir(parents=True)
    (txn / "transaction_history.sqlite").write_bytes(b"sqlite\n")
    (txn / "transaction_history.sqlite-shm").write_bytes(b"shm\n")
    (txn / "transaction_history.sqlite-wal").write_bytes(b"wal\n")
    # Symlinks whose target is not in the image. Real builds are full of them:
    # /usr/lib/bootc/storage, /usr/share/licenses/malcontent/COPYING and the
    # 32-bit libstdc++.a stubs all dangle in the committed tree.
    (root / "usr/share/licenses/malcontent").mkdir(parents=True)
    (root / "usr/share/licenses/malcontent/COPYING").symlink_to(
        "../../doc/malcontent/COPYING")
    (root / "usr/lib/bootc").mkdir(parents=True)
    (root / "usr/lib/bootc/storage").symlink_to("/sysroot/ostree/bootc/storage")


def clean(root: Path) -> subprocess.CompletedProcess:
    """Run the real script with CLEAN_ROOT pointed at `root`."""
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={"PATH": "/usr/bin:/bin", "CLEAN_ROOT": str(root)},
        capture_output=True,
        text=True,
    )


class CleanStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        build_tree(self.root)
        self.result = clean(self.root)

    def assertCleanSucceeded(self):
        self.assertEqual(
            self.result.returncode, 0,
            f"clean-stage.sh failed:\n{self.result.stderr}")

    def test_exits_zero_on_a_representative_tree(self):
        self.assertCleanSucceeded()

    def test_var_keeps_only_cache(self):
        """Every directory directly under /var goes except `cache` itself."""
        self.assertCleanSucceeded()
        survivors = sorted(p.name for p in (self.root / "var").iterdir())
        self.assertEqual(survivors, ["cache"])

    def test_var_cache_keeps_only_rpm_ostree(self):
        """rpm-ostree is the one cache bootc expects to find after the build."""
        self.assertCleanSucceeded()
        survivors = sorted(p.name for p in (self.root / "var/cache").iterdir())
        self.assertEqual(survivors, ["rpm-ostree"])
        self.assertEqual(
            (self.root / "var/cache/rpm-ostree/repomd.xml").read_text(),
            "keep me\n",
            "the surviving cache must keep its contents, not just its directory")

    def test_libdnf5_keyring_tree_is_removed(self):
        """The regression that put var-tmpfiles back on the NVIDIA flavors.

        `dnf clean all` drops the metadata and leaves the imported GPG keyring,
        so lint rejected both the untracked directories and the key inside
        them. Asserted on its own because it is the specific tree the script's
        second `find` was widened to cover.
        """
        self.assertCleanSucceeded()
        self.assertFalse((self.root / "var/cache/libdnf5").exists())

    def test_run_and_tmp_are_emptied_but_kept(self):
        """/run and /tmp are cleared in place; deleting them breaks the build.

        The container runtime bind-mounts /run/.containerenv, so `rm -rf /run`
        fails with EBUSY and takes the build with it.
        """
        self.assertCleanSucceeded()
        for directory in ("run", "tmp"):
            path = self.root / directory
            self.assertTrue(path.is_dir(), f"/{directory} must survive as a directory")
            self.assertEqual(
                list(path.iterdir()), [],
                f"/{directory} must be left empty")

    def test_unpacked_build_input_cache_is_removed(self):
        """/utah-cache is build input; shipping it costs roughly 1.5 GB."""
        self.assertCleanSucceeded()
        self.assertFalse((self.root / "utah-cache").exists())

    def test_absent_run_and_tmp_are_not_an_error(self):
        """`main` never grows some of these; a missing directory is not a failure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_tree(root)
            for directory in ("run", "tmp", "utah-cache"):
                subprocess.run(["rm", "-rf", str(root / directory)], check=True)
            result = clean(root)
            self.assertEqual(
                result.returncode, 0,
                f"clean-stage.sh must tolerate absent /run, /tmp and /utah-cache:\n"
                f"{result.stderr}")

    def test_files_are_not_mistaken_for_directories_under_var(self):
        """The `-type d` filter is deliberate: a plain file under /var is not a tree.

        Pinned because dropping `-type d` would look like a harmless
        simplification while changing what the final layer contains.
        """
        self.assertCleanSucceeded()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_tree(root)
            (root / "var/marker").write_text("plain file\n")
            result = clean(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "var/marker").is_file())


    def test_mtimes_under_usr_and_etc_are_pinned(self):
        """A rebuild that changes nothing must commit identical layer digests.
        dnf, meson and the extension build leave wall-clock mtimes under /usr
        and /etc, and chunkah splits those directories across layers, so a
        changed mtime in any tar header changes that layer's digest. clean-stage
        pins every file and directory under /usr and /etc to SOURCE_DATE_EPOCH,
        so a layer's digest is a function of its content alone (utah#313)."""
        self.assertCleanSucceeded()
        for path in (
            self.root / "usr/bin/tool",
            self.root / "usr/share/doc/readme",
            self.root / "etc/systemd/system/foo.service",
        ):
            mtime = int(path.stat().st_mtime)
            self.assertEqual(
                mtime,
                SOURCE_DATE_EPOCH,
                f"{path} was not pinned to SOURCE_DATE_EPOCH",
            )

    def test_transaction_history_is_dropped(self):
        """dnf5 records every transaction in usr/lib/sysimage/libdnf5/
        transaction_history.sqlite (with its -shm and -wal companions). It is
        build-time metadata -- nothing at runtime reads it -- and it carries a
        wall-clock mtime plus an in-memory page cache, so it both wastes space
        and churns the layer that carries it. clean-stage drops all three."""
        self.assertCleanSucceeded()
        base = self.root / "usr/lib/sysimage/libdnf5"
        for name in (
            "transaction_history.sqlite",
            "transaction_history.sqlite-shm",
            "transaction_history.sqlite-wal",
        ):
            self.assertFalse(
                (base / name).exists(),
                f"{name} should have been removed",
            )

    def test_dangling_symlinks_do_not_fail_the_build(self):
        """A committed tree contains symlinks whose target is not in the image
        -- /usr/lib/bootc/storage, the malcontent COPYING links, the 32-bit
        libstdc++.a stubs. `touch` follows symlinks by default, so it reported
        "No such file or directory" for each one and exited non-zero, which
        under `set -e` failed the final Containerfile layer for every flavor.
        clean-stage passes -h, stamping the link itself (utah#313)."""
        self.assertCleanSucceeded()
        for link in (
            self.root / "usr/share/licenses/malcontent/COPYING",
            self.root / "usr/lib/bootc/storage",
        ):
            self.assertTrue(link.is_symlink(), f"{link} should still be a symlink")
            self.assertFalse(link.exists(), f"{link} should still dangle")
            mtime = int(os.lstat(link).st_mtime)
            self.assertEqual(
                mtime,
                SOURCE_DATE_EPOCH,
                f"{link} was not pinned to SOURCE_DATE_EPOCH",
            )

    def test_absent_usr_and_etc_are_not_an_error(self):
        """A tree without /usr or /etc must still exit zero: the normalisation
        is scoped to the directories that exist, mirroring the /run and /tmp
        guard the other absence test relies on."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_tree(root)
            for directory in ("usr", "etc"):
                subprocess.run(["rm", "-rf", str(root / directory)], check=True)
            result = clean(root)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
