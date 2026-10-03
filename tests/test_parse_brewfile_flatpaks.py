"""Exercise the shared Brewfile CLI's declaration grammar and error boundaries."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/parse-brewfile-flatpaks.sh"
SOURCE_VERIFIER = ROOT / "scripts/verify-desktop-contract.py"
INSTALLED_NAME = "utah-parse-brewfile-flatpaks"
INSTALLED_VERIFIER = "utah-verify-desktop-contract"


class ParseBrewfileFlatpaksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="brewfile-parser-")
        self.addCleanup(temporary.cleanup)
        self.brewfile = Path(temporary.name) / "Brewfile with spaces"

    def parse(self, text):
        self.brewfile.write_text(text)
        result = subprocess.run([str(HELPER), str(self.brewfile)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_order_and_repeated_declarations_are_preserved(self):
        self.assertEqual(self.parse(
            'flatpak "org.mozilla.firefox"\n'
            'flatpak "org.gnome.Loupe"\n'
            'flatpak "org.mozilla.firefox"\n'),
            ["org.mozilla.firefox", "org.gnome.Loupe", "org.mozilla.firefox"])

    def test_comments_blank_lines_and_other_package_types_are_ignored(self):
        self.assertEqual(self.parse(
            '# flatpak "commented.id"\n\nbrew "gh"\n'
            'flatpak "org.gnome.Calculator"\n\n'),
            ["org.gnome.Calculator"])

    def test_indented_unicode_whitespace_and_crlf_match_the_contract_grammar(self):
        self.assertEqual(self.parse(
            '    flatpak "org.gnome.Loupe"\r\n'
            '\u00a0flatpak\u2003"org.gnome.Maps"\u00a0\r\n'),
            ["org.gnome.Loupe", "org.gnome.Maps"])

    def test_trailing_arguments_and_unterminated_or_empty_quotes_are_rejected(self):
        self.assertEqual(self.parse(
            'flatpak "invalid.args", args: "x"\n'
            'flatpak "unterminated\nflatpak ""\n'
            'flatpak "org.mozilla.firefox"\n'), ["org.mozilla.firefox"])

    def test_stdin_filters_declarations_without_requiring_a_contract(self):
        result = subprocess.run([str(HELPER)],
                                input='flatpak "invalid", args: "x"\nflatpak "org.gnome.Maps"\n',
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["org.gnome.Maps"])

    def test_missing_file_is_not_reported_as_an_empty_successful_brewfile(self):
        result = subprocess.run([str(HELPER), str(self.brewfile)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_extra_file_arguments_are_rejected(self):
        self.brewfile.write_text('flatpak "org.gnome.Maps"\n')
        result = subprocess.run([str(HELPER), str(self.brewfile), str(self.brewfile)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_installed_name_branch_executes_the_installed_verifier(self):
        # The branch production actually runs is the one where
        # BASH_SOURCE[0] is "utah-parse-brewfile-flatpaks"; that case
        # exec()s the installed utah-verify-desktop-contract helper, not
        # the source name. We exercise it by copying both scripts into a
        # tempdir under their installed names and running the helper
        # from there. A test that runs the source name would only cover
        # the local-dev branch and miss the production selector entirely.
        if not SOURCE_VERIFIER.exists():
            self.skipTest(f"missing source verifier: {SOURCE_VERIFIER}")
        with tempfile.TemporaryDirectory(prefix="brewfile-installed-") as tmp:
            tmp_path = Path(tmp)
            helper_dest = tmp_path / INSTALLED_NAME
            verifier_dest = tmp_path / INSTALLED_VERIFIER
            shutil.copy2(HELPER, helper_dest)
            shutil.copy2(SOURCE_VERIFIER, verifier_dest)
            helper_dest.chmod(0o755)
            verifier_dest.chmod(0o755)

            brewfile = tmp_path / "Brewfile"
            brewfile.write_text('flatpak "org.gnome.Maps"\n')
            result = subprocess.run([str(helper_dest), str(brewfile)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["org.gnome.Maps"])


if __name__ == "__main__":
    unittest.main()
