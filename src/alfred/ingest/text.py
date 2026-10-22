"""Text cleanup shared by all parsers."""

import re

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(raw: str) -> str:
    """Normalize line endings and whitespace, without changing any characters.

    Unicode normalization (NFKC) is deliberately not applied: it would turn "x²" into "x2",
    which changes the meaning of formulas.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _EXTRA_BLANK_LINES.sub("\n\n", text)
    return text.strip()
