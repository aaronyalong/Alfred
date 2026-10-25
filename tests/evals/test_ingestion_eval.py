import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from alfred.cli import main
from alfred.evals.ingestion import (
    BenchmarkError,
    EngineResult,
    LabeledPage,
    Labels,
    Report,
    load_labels,
    normalize,
    render,
    run,
)
from alfred.ingest import Engine

MakePdf = Callable[[list[str]], Path]  # the make_pdf fixture from conftest.py


@pytest.mark.parametrize(
    ("latex", "unicode"),
    [
        (r"P(w_{k}|w_{k-1})", "P(wk|wk−1)"),  # noqa: RUF001
        (r"\mathrm{softmax}(u/\tau)", "softmax(u/τ)"),
        (r"| a | | b | \cos \theta", "|a||b| cos θ"),
        (r"\log ( p _ { 1 } \times p _ { 2 } )", "log(p1 × p2)"),  # noqa: RUF001
        (r"q _ { 2 } \cdot k _ { 2 }", "q2·k2"),
        (r"\left( x \right)", "(x)"),
        (r"w _ { 1 \colon k - 1 }", "w_{1:k-1}"),
        (r"P(a \mid b)", "P(a|b)"),
    ],
)
def test_normalize_treats_latex_and_unicode_spellings_as_equal(latex: str, unicode: str) -> None:
    assert normalize(latex) == normalize(unicode)


def test_normalize_keeps_differences_that_change_meaning() -> None:
    assert normalize("P(w_k|w_{k-1})") != normalize("P(w_k|w_{k+1})")
    assert normalize("cosine(v, w)") != normalize("cos(v, w)")


def test_a_fact_matches_any_of_its_spellings() -> None:
    page = LabeledPage(file="f.pdf", page=1, kind="diagram", facts=[["N x d_k", "N × d_k"]])  # noqa: RUF001

    assert page.found_in("the matrix is N × d_k") == [True]  # noqa: RUF001
    assert page.found_in("the matrix is N by d_k") == [False]


def test_labels_reject_empty_facts_and_unknown_files() -> None:
    with pytest.raises(ValidationError):
        LabeledPage(file="f.pdf", page=1, kind="text", facts=[[" "]])
    with pytest.raises(ValidationError, match="unknown file"):
        Labels(files=[], pages=[LabeledPage(file="f.pdf", page=1, kind="text", facts=[["a"]])])


def write_labels(tmp_path: Path, pdf: Path, sha256: str) -> Path:
    labels = tmp_path / "labels.toml"
    labels.write_text(
        f'[[files]]\nname = "{pdf.name}"\nsha256 = "{sha256}"\n\n'
        f'[[pages]]\nfile = "{pdf.name}"\npage = 2\nkind = "text"\n'
        'facts = [["learning rate"], ["momentum"]]\n',
        encoding="utf-8",
    )
    return labels


def test_run_scores_facts_only_on_the_labeled_page(make_pdf: MakePdf, tmp_path: Path) -> None:
    # "momentum" exists in the document, but on page 1, not the labeled page 2.
    pdf = make_pdf(["SGD with momentum.", "The learning rate sets the step size."])
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    labels = load_labels(write_labels(tmp_path, pdf, sha))

    report = run(labels, pdf.parent, [Engine.BASELINE])

    result = report.engines[0]
    assert result.pages[0].found == [True, False]
    assert result.recall() == (1, 2)
    assert result.recall("text") == (1, 2)
    assert result.recall("formula") == (0, 0)
    assert result.pages_parsed == 2


def test_run_refuses_a_file_that_changed_since_labeling(make_pdf: MakePdf, tmp_path: Path) -> None:
    pdf = make_pdf(["one", "two"])
    labels = load_labels(write_labels(tmp_path, pdf, "0" * 64))

    with pytest.raises(BenchmarkError, match="has changed"):
        run(labels, pdf.parent, [Engine.BASELINE])


def test_cli_prints_table_and_writes_json(
    make_pdf: MakePdf, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = make_pdf(["SGD with momentum.", "The learning rate sets the step size."])
    labels = write_labels(tmp_path, pdf, hashlib.sha256(pdf.read_bytes()).hexdigest())
    out = tmp_path / "results.json"

    code = main(
        ["eval", "ingestion", "--engine", "baseline", "--data", str(pdf.parent),
         "--labels", str(labels), "--out", str(out)]
    )  # fmt: skip

    assert code == 0
    assert "1/2 50%" in capsys.readouterr().out
    assert json.loads(out.read_text())["engines"][0]["engine"] == "baseline"


def test_render_reports_api_calls_and_cost_for_paid_engines() -> None:
    def result(engine: Engine, api_calls: int, cost_usd: float | None) -> EngineResult:
        return EngineResult(
            engine=engine, parsers=[], seconds=1.0, pages_parsed=10, pages=[], errors=[],
            api_calls=api_calls, cost_usd=cost_usd,
        )  # fmt: skip

    report = Report(
        run_at=datetime(2026, 10, 24, tzinfo=UTC),
        engines=[result(Engine.BASELINE, 0, None), result(Engine.VISION, 4, 0.10)],
    )

    text = render(report)

    assert "vision: 4 API calls, $0.10, $0.025 per call" in text
    assert "baseline:" not in text
