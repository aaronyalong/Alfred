import io
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from alfred.cli import main
from alfred.evals.questions import (
    Label,
    LabelError,
    label_set,
    load_labels,
    question_id,
    render_question,
    summarize,
)
from alfred.ingest import Unit
from alfred.questions import Bloom, QuestionSet, Topic, TopicMap
from tests.questions.test_checks import mc, tf

SHA = "0" * 64


def question_set() -> QuestionSet:
    return QuestionSet(
        source_name="lecture.pdf",
        document_sha256=SHA,
        unit=Unit.PAGE,
        model="claude-opus-5-5",
        topics=TopicMap(
            document_sha256=SHA,
            topics=(Topic(id="cosine-similarity", name="Cosine similarity", pages=(2,)),),
        ),
        questions=(mc(), tf(False)),
    )


def label(questions: QuestionSet, path: Path, *answers: str) -> tuple[int, str]:
    """Run a session on scripted answers; like input(), it raises EOFError when they run out."""
    script = iter(answers)

    def ask(_: str) -> str:
        try:
            return next(script)
        except StopIteration:
            raise EOFError from None

    out = io.StringIO()
    count = label_set(questions, path, ask=ask, out=out)
    return count, out.getvalue()


# One multiple-choice label that passes everything, then a true/false one that fails a check.
GOOD_MC = ("y", "y", "y", "y", "y", "1", "", "")
WEAK_TF = ("y", "y", "n", "yes", "3", "too-easy, ", "", "true except on page 3")


def test_question_ids_are_stable_and_depend_on_the_document() -> None:
    assert question_id(SHA, mc()) == question_id(SHA, mc())
    assert question_id(SHA, mc()) != question_id("1" * 64, mc())
    assert question_id(SHA, mc()) != question_id(SHA, mc(options=("A", "B", "C", "D")))


def test_a_session_labels_every_question_and_saves_each_one(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"

    count, _ = label(question_set(), path, *GOOD_MC, *WEAK_TF)

    labels = list(load_labels(path).values())
    assert count == 2
    assert [label.verdict for label in labels] == ["good", "weak"]
    assert labels[0].distractors is True
    assert labels[1].distractors is None  # not asked for true/false
    assert labels[1].tags == ("too-easy",)
    assert labels[1].note == "true except on page 3"  # an empty note was asked again
    assert labels[0].model_bloom == Bloom.REMEMBER


def test_quitting_keeps_earlier_labels_and_resuming_skips_them(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"

    count, out = label(question_set(), path, *GOOD_MC, "q")
    assert count == 1
    assert "stopped" in out

    count, out = label(question_set(), path, *WEAK_TF)
    assert count == 1
    assert "1 of 2 questions to label" in out
    assert len(load_labels(path)) == 2


def test_skipping_and_invalid_answers(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"

    # "maybe" and "4" are asked again; s skips the true/false question.
    answers = ("maybe", "y", "y", "y", "y", "y", "4", "1", "", "", "s")
    count, _ = label(question_set(), path, *answers)

    assert count == 1


def test_running_out_of_input_stops_cleanly(tmp_path: Path) -> None:
    count, out = label(question_set(), tmp_path / "labels.jsonl", "y")

    assert count == 0
    assert "stopped" in out


def test_the_model_bloom_band_is_hidden_from_the_labeler() -> None:
    shown = render_question(mc(bloom=Bloom.ANALYZE_EVALUATE), Unit.PAGE)

    assert "analyze" not in shown
    assert "* a) Directions" in shown


def test_labels_must_be_consistent() -> None:
    fields: dict[str, Any] = {
        "id": "x",
        "document_sha256": SHA,
        "model": "m",
        "correct": True,
        "supported": True,
        "unambiguous": True,
        "worth_studying": True,
        "bloom": Bloom.REMEMBER,
        "model_bloom": Bloom.REMEMBER,
    }
    with pytest.raises(ValidationError, match="distractors"):
        Label(type="true_false", distractors=True, **fields)
    with pytest.raises(ValidationError, match="note"):
        Label(type="multiple_choice", distractors=False, **fields)

    wrong_key: dict[str, Any] = {**fields, "correct": False}
    bad = Label(type="true_false", distractors=None, note="wrong key", **wrong_key)
    assert bad.verdict == "bad"


def test_summary_counts_verdicts_criteria_and_tags(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    label(question_set(), path, *GOOD_MC, *WEAK_TF)

    summary = summarize(load_labels(path).values())

    assert summary.splitlines()[0] == "2 questions from 1 document(s): 1 good, 1 weak, 0 bad"
    assert "unambiguous: 1/2" in summary
    assert "distractors: 1/1" in summary
    assert "bloom agrees with the model: 1/2" in summary
    assert "too-easy 1" in summary
    assert summarize([]) == "no labels yet"


def test_a_broken_labels_file_names_the_line(tmp_path: Path) -> None:
    path = tmp_path / "labels.jsonl"
    path.write_text("\n{not json}\n")

    with pytest.raises(LabelError, match="line 2"):
        load_labels(path)


def test_eval_questions_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "labels.jsonl"
    label(question_set(), path, *GOOD_MC)

    assert main(["eval", "questions", "--labels", str(path)]) == 0
    assert "1 questions from 1 document(s): 1 good" in capsys.readouterr().out


def test_label_command_rejects_a_file_that_is_not_a_question_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other.json"
    other.write_text('{"pages": []}')

    assert main(["label", str(other), "--labels", str(tmp_path / "labels.jsonl")]) == 1
    assert "not a question set" in capsys.readouterr().err
