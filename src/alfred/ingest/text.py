"""Text cleanup shared by all parsers."""

import re

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")

# Fewer non-whitespace characters than this means a page has no real content of its own.
MIN_TEXT_CHARS = 20


def clean_text(raw: str) -> str:
    """Normalize line endings and whitespace, without changing any characters.

    Unicode normalization (NFKC) is deliberately not applied: it would turn "x²" into "x2",
    which changes the meaning of formulas.
    """
    # \v is how PowerPoint stores a line break inside a paragraph (Shift+Enter).
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\v", "\n")
    # PDFium marks a hyphen at a line break with the non-character U+FFFE. In real lecture
    # PDFs these were real hyphens ("n-grams", "low-probability"), so keep them as "-".
    text = text.replace("￾", "-")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _EXTRA_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def has_real_text(text: str) -> bool:
    return len("".join(text.split())) >= MIN_TEXT_CHARS
