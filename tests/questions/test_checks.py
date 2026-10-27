from alfred.ingest import Block, BlockKind, Document, Page, SourceFormat, Unit
from alfred.questions import Bloom, MultipleChoice, Source, TrueFalse
from alfred.questions.checks import check_question, check_set

PAGE_2 = "Cosine similarity compares the directions of two vectors, not their lengths."
TOPICS = {"cosine-similarity"}


def document() -> Document:
    pages = [
        Page(number=1, blocks=(Block(kind=BlockKind.TEXT, text="Week 3: word embeddings"),)),
        Page(number=2, blocks=(Block(kind=BlockKind.TEXT, text=PAGE_2),)),
    ]
    return Document(
        source_name="lecture.pdf",
        source_sha256="0" * 64,
        format=SourceFormat.PDF,
        unit=Unit.PAGE,
        parser="test",
        pages=tuple(pages),
    )


def mc(**changes: object) -> MultipleChoice:
    question = MultipleChoice(
        question="What does cosine similarity compare?",
        options=("Directions", "Lengths", "Sums", "Counts"),
        answer=0,
        explanation="It compares directions, not lengths.",
        bloom=Bloom.REMEMBER,
        topic_ids=("cosine-similarity",),
        source=Source(page=2, quote="compares the directions of two vectors"),
    )
    return question.model_copy(update=changes)


def tf(answer: bool, text: str = "Cosine similarity depends on vector length.") -> TrueFalse:
    return TrueFalse(
        question=text,
        answer=answer,
        explanation="It compares directions only.",
        bloom=Bloom.UNDERSTAND_APPLY,
        topic_ids=("cosine-similarity",),
        source=Source(page=2, quote="not their lengths. "),
    )


def test_a_well_formed_question_passes() -> None:
    assert check_question(mc(), document(), TOPICS) == []


def test_quotes_match_despite_case_whitespace_and_typographic_quotes() -> None:
    quote = Source(page=2, quote="COMPARES  the directions\nof two vectors")

    assert check_question(mc(source=quote), document(), TOPICS) == []


def test_a_quote_must_be_on_the_cited_page() -> None:
    wrong_page = mc(source=Source(page=1, quote="compares the directions of two vectors"))
    missing_page = mc(source=Source(page=9, quote="compares the directions of two vectors"))
    too_short = mc(source=Source(page=2, quote="vectors"))

    assert check_question(wrong_page, document(), TOPICS) == ["quote not found on page 1"]
    assert check_question(missing_page, document(), TOPICS) == ["cites page 9, which doesn't exist"]
    assert "quote is too short to locate" in check_question(too_short, document(), TOPICS)[0]


def test_multiple_choice_options_must_be_well_formed() -> None:
    def problems(**changes: object) -> list[str]:
        return check_question(mc(**changes), document(), TOPICS)

    assert problems(options=("A", "B", "C")) == ["has 3 options, not 4"]
    assert problems(options=("Directions", "directions ", "Sums", "Counts")) == ["options repeat"]
    assert problems(answer=-1) == ["answer is not one of the options"]
    assert problems(options=("Directions", "Lengths", "Sums", "None of the above")) == [
        'uses "all/none of the above"'
    ]


def test_topics_must_come_from_the_topic_map() -> None:
    assert check_question(mc(topic_ids=()), document(), TOPICS) == ["no topic"]
    assert check_question(mc(topic_ids=("vectors",)), document(), TOPICS) == [
        "unknown topic(s): vectors"
    ]


def test_check_set_rejects_duplicates_and_warns_about_lopsided_true_false() -> None:
    questions = [mc(), mc(), *(tf(True, f"Statement {i} about vectors.") for i in range(4))]

    passed, rejected, warnings = check_set(questions, document(), TOPICS)

    assert len(passed) == 5
    assert [r.problems for r in rejected] == [("duplicates an earlier question",)]
    assert warnings == ["4 of 4 true/false answers are true; aim for about half"]


def test_balanced_true_false_gives_no_warning() -> None:
    questions = [tf(i % 2 == 0, f"Statement {i} about vectors.") for i in range(4)]

    assert check_set(questions, document(), TOPICS)[2] == []
