"""Page issue messages shared by parsers. They are shown to the user as warnings."""

MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"  # Office Math (PPTX, DOCX)


def visual_issue(count: int) -> str:
    return f"{count} image(s) or diagram(s) not extracted"


def equation_issue(count: int) -> str:
    return f"{count} equation(s) not extracted"
