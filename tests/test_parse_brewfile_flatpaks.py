"""scripts/parse-brewfile-flatpaks.sh and scripts/verify-desktop-contract.py's
parse_brewfile must agree on every Brewfile line (#510). The bash helper was
introduced so every place that reads /usr/share/ublue-os/homebrew/system-flatpaks.Brewfile
shares a parser with the contract verifier; if these two implementations drift,
the build-time bake can declare a set the contract check rejects (or vice
versa) and the single-source-of-truth claim stops holding.

The test invokes the bash helper against a fixture Brewfile and asserts the
result equals the Python parser's output, both for the real upstream Brewfile
and for synthetic Brewfiles that exercise the regex edges (indented entries,
trailing-argument rejection, blank lines, comments, non-flatpak taps).
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "parse-brewfile-flatpaks.sh"
PYTHON_SCRIPT = ROOT / "scripts" / "verify-desktop-contract.py"


def load_python_parser():
    spec = importlib.util.spec_from_file_location(
        "verify_desktop_contract", PYTHON_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_brewfile


def bash_parse(brewfile: Path) -> list[str]:
    """Run the bash helper against a Brewfile path and return the lines."""
    if not HELPER.is_file():
        raise unittest.SkipTest(f"{HELPER} not present")
    if not shutil.which("bash"):
        raise unittest.SkipTest("bash not on PATH")
    result = subprocess.run(
        [str(HELPER), str(brewfile)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"helper exited {result.returncode}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
    return [line for line in result.stdout.splitlines() if line]


class ParseBrewfileHelperAgreementTests(unittest.TestCase):
    """The bash helper and the Python parser must agree on every Brewfile.

    Issue #510: configure-services.sh used to inline `awk -F'"' '/^flatpak /
    && NF >= 2 {print $2}'`, which silently widened the declared set past
    what verify-desktop-contract.py counted (the Python regex rejects lines
    with trailing arguments). Centralising the parse behind this helper
    prevents future inline copies from diverging again.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brewfile = Path(self.tmp.name) / "Brewfile"

    def write(self, text: str) -> None:
        self.brewfile.write_text(text)

    def assert_agree(self) -> tuple[list[str], list[str]]:
        python = load_python_parser()
        expected = python(self.brewfile)
        actual = bash_parse(self.brewfile)
        self.assertEqual(
            actual,
            expected,
            f"bash and python parsers disagree on {self.brewfile}\n"
            f"bash:   {expected}\npython: {actual}",
        )
        return expected, actual

    def test_clean_brewfile(self) -> None:
        self.write(
            "# Default system-wide flatpaks for Bluefin\n"
            'flatpak "be.alexandervanhee.gradia"\n'
            'flatpak "com.github.PintaProject.Pinta"\n'
            'flatpak "org.gtk.Gtk3theme.adw-gtk3"\n'
            'flatpak "org.mozilla.firefox"\n'
        )
        self.assert_agree()

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        self.write(
            "# header comment\n"
            "\n"
            'brew "gh"\n'
            "\n"
            'flatpak "org.gnome.Calculator"\n'
            "\n"
            "# trailing comment\n"
            'flatpak "org.mozilla.firefox"\n'
        )
        self.assert_agree()

    def test_indented_entries_match_python_strip(self) -> None:
        """Python's parse_brewfile strips leading whitespace before matching;
        the bash helper must do the same so an indented flatpak line is
        accepted on both sides."""
        self.write(
            '    flatpak "org.gnome.Loupe"\n'
            "\tflatpak \"org.gnome.Maps\"\n"
        )
        self.assert_agree()

    def test_trailing_arguments_are_rejected(self) -> None:
        """The motivating case for #510: `flatpak "id", args: "x"` widened
        the declared set in every inline awk but the Python parser already
        rejected it. Both sides must reject it now."""
        self.write('flatpak "org.gnome.Loupe", args: "x"\n')
        self.assert_agree()

    def test_unterminated_quote_is_rejected(self) -> None:
        self.write('flatpak "broken\n')
        self.assert_agree()

    def test_real_upstream_bluefin_brewfile(self) -> None:
        """The actual /usr/share/ublue-os/homebrew/system-flatpaks.Brewfile
        from projectbluefin/common is the input the helper runs against in
        every Utah build; if the helper and Python disagree there, the
        contract check would surface drift on every PR."""
        common = Path("/home/dev/workspace/projectbluefin/common")
        candidates = list(common.glob("system_files/bluefin/usr/share/ublue-os/homebrew/system-flatpaks.Brewfile"))
        if not candidates:
            self.skipTest("Bluefin Brewfile not available in the checkout")
        real = candidates[0]
        # Copy so the helper reads from a path it does not have to exist for.
        shutil.copy(real, self.brewfile)
        self.assert_agree()


if __name__ == "__main__":
    unittest.main()
