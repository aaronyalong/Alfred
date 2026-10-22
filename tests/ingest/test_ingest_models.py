import pytest
from pydantic import ValidationError

from alfred.ingest import Block, BlockKind, Document, Page, SourceFormat, Unit


def make_document(page_numbers: list[int]) -> Document:
    return Document(
        source_name="lecture.pdf",
        source_sha256="abc",
        format=SourceFormat.PDF,
        unit=Unit.PAGE,
        parser="test",
        pages=tuple(Page(number=n) for n in page_numbers),
    )


def test_page_text_joins_blocks_with_blank_lines() -> None:
    page = Page(
        number=1,
        blocks=(
            Block(kind=BlockKind.TITLE, text="Attention"),
            Block(kind=BlockKind.TEXT, text="Queries, keys and values."),
        ),
    )

    assert page.text == "Attention\n\nQueries, keys and values."


def test_pages_must_be_numbered_from_one_in_order() -> None:
    make_document([1, 2, 3])  # valid

    for bad in ([0, 1], [1, 3], [2, 1]):
        with pytest.raises(ValidationError):
            make_document(bad)


def test_page_lookup_uses_one_based_numbers() -> None:
    document = make_document([1, 2])

    assert document.page(2).number == 2
    with pytest.raises(KeyError):
        document.page(0)
    with pytest.raises(KeyError):
        document.page(3)


def test_documents_are_immutable() -> None:
    document = make_document([1])

    with pytest.raises(ValidationError):
        document.source_name = "other.pdf"  # type: ignore[misc]
