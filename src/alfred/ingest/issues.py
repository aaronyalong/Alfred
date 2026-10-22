"""Page issue messages shared by parsers. They are shown to the user as warnings."""

MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"  # Office Math (PPTX, DOCX)

# Images and charts covering at least this share of the page are treated as content
# (diagrams, plots, screenshots), not decoration. Measured on a real cloud deck: every
# diagram covered 27-60% of its slide, while icons and logos stay well below 10%.
MIN_VISUAL_SHARE = 0.10


def visual_issue(count: int) -> str:
    return f"{count} image(s) or diagram(s) not extracted"


def equation_issue(count: int) -> str:
    return f"{count} equation(s) not extracted"
