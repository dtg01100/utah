#!/usr/bin/env bash
# Decide whether a tesseract transcript of the final desktop screenshot proves
# that fastfetch ran inside the installed session.
#
# Kept separate from luks-e2e.sh so the decision can be exercised against real
# transcripts (tests/test_iso_ci.py) without booting a VM.
#
# Two independent tokens must be present, because either alone lies:
#
#   1. The sentinel the test's .bashrc echoes after fastfetch. Matched as the
#      bare word FASTFETCH rather than the full UTAH-E2E-FASTFETCH or even
#      E2E<sep>FASTFETCH: OCR routinely drops or mangles glyphs around the
#      E2E fragment -- run 35374557822 lost the leading U (TAH-E2E-FASTFETCH),
#      and run 36765312662 read E2E as £26 (uran-£26-FASTFETCH). FASTFETCH is
#      the only all-caps, non-English word in the sentinel and the only piece
#      tesseract has been observed to leave intact across the misreads we have
#      on record, so it is the part the gate anchors on.
#   2. A token only fastfetch's own body produces, so a sentinel left in
#      scrollback cannot pass the gate by itself. Either the "Kernel" field
#      label or the kernel version line it labels: Bluefin's fastfetch config
#      draws its labels as Nerd Font glyphs, which OCR does not read as text at
#      all, so requiring the label alone can never match.
set -euo pipefail

OCR_TEXT="${1:?path to the tesseract transcript is required}"

[[ -s "${OCR_TEXT}" ]] || exit 1

grep -qi 'FASTFETCH' "${OCR_TEXT}" || exit 1
grep -qiE 'kernel|Linux[[:space:]]+[0-9]+\.[0-9]+' "${OCR_TEXT}" || exit 1
