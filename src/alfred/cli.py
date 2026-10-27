"""Command-line interface for running and inspecting the pipeline locally."""

import argparse
import sys
from pathlib import Path

from alfred.evals import ingestion as ingestion_eval
from alfred.evals import questions as question_labels
from alfred.ingest import Document, Engine, IngestError, docling_parser, ingest
from alfred.ingest.vision import VisionReader
from alfred.llm import Usage, default_cache
from alfred.questions import MultipleChoice, QuestionSet
from alfred.questions.generate import GenerationError, Generator

LABELS = Path("evals/questions/labels.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alfred")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = commands.add_parser("ingest", help="parse a file and show what was extracted")
    ingest_cmd.add_argument("file", type=Path)
    ingest_cmd.add_argument("--page", type=int, help="show only this page/slide/section")
    ingest_cmd.add_argument("--json", action="store_true", help="print the Document as JSON")
    ingest_cmd.add_argument(
        "--engine", type=Engine, choices=list(Engine), default=Engine.BASELINE, help="parser to use"
    )
    ingest_cmd.set_defaults(handler=_ingest)

    generate_cmd = commands.add_parser("generate", help="write practice questions from a file")
    generate_cmd.add_argument("file", type=Path)
    generate_cmd.add_argument("--count", type=int, default=10, help="questions to ask for")
    generate_cmd.add_argument(
        "--engine",
        type=Engine,
        choices=list(Engine),
        default=Engine.VISION,
        help="parser to use (default: vision, so diagrams and formulas are included)",
    )
    generate_cmd.add_argument("--out", type=Path, help="also write the question set as JSON")
    generate_cmd.set_defaults(handler=_generate)

    label_cmd = commands.add_parser("label", help="judge generated questions by the rubric")
    label_cmd.add_argument("questions", type=Path, help="a question set from generate --out")
    label_cmd.add_argument("--labels", type=Path, default=LABELS)
    label_cmd.set_defaults(handler=_label)

    eval_cmd = commands.add_parser("eval", help="run an evaluation")
    evals = eval_cmd.add_subparsers(dest="evaluation", required=True)
    bench = evals.add_parser("ingestion", help="score ingestion engines against labeled facts")
    bench.add_argument(
        "--engine",
        type=Engine,
        choices=list(Engine),
        action="append",
        help="engine to run (repeatable; default: all installed engines except paid vision)",
    )
    bench.add_argument("--data", type=Path, default=Path("data/private"))
    bench.add_argument("--labels", type=Path, default=Path("evals/ingestion/labels.toml"))
    bench.add_argument("--out", type=Path, help="also write the full report as JSON")
    bench.add_argument(
        "--no-cache", action="store_true", help="call the vision model even for pages read before"
    )
    bench.set_defaults(handler=_eval_ingestion)
    summary = evals.add_parser("questions", help="summarize the hand labels of questions")
    summary.add_argument("--labels", type=Path, default=LABELS)
    summary.set_defaults(handler=_eval_questions)

    args = parser.parse_args(argv)
    return args.handler(parser, args)


def _ingest(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.file.is_file():
        parser.error(f"no such file: {args.file}")
    try:
        vision = (
            VisionReader(cache=default_cache("vision")) if args.engine is Engine.VISION else None
        )
        document = ingest(args.file, engine=args.engine, vision=vision)
        if args.page is not None:
            document.page(args.page)  # fail early on a page number that doesn't exist
    except (IngestError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(document.model_dump_json(indent=2) if args.json else render(document, args.page))
    return 0


def _generate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.file.is_file():
        parser.error(f"no such file: {args.file}")
    if args.count < 1:
        parser.error("--count must be at least 1")
    vision = VisionReader(cache=default_cache("vision")) if args.engine is Engine.VISION else None
    generator = Generator(topic_cache=default_cache("topics"))
    try:
        document = ingest(args.file, engine=args.engine, vision=vision)
        questions = generator.generate(document, count=args.count)
    except (IngestError, GenerationError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        usage = [("vision", vision.usage)] if vision else []
        print(render_usage([*usage, ("generation", generator.usage)]), file=sys.stderr)

    print(render_questions(questions))
    if args.out:
        # The question set quotes the course material: keep it out of git (e.g. data/private).
        args.out.write_text(questions.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


def _label(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.questions.is_file():
        parser.error(f"no such file: {args.questions}")
    try:
        questions = question_labels.load_question_set(args.questions)
        question_labels.label_set(questions, args.labels, out=sys.stdout)
        labels = question_labels.load_labels(args.labels)
    except question_labels.LabelError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n" + question_labels.summarize(labels.values()))
    return 0


def _eval_questions(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        labels = question_labels.load_labels(args.labels)
    except question_labels.LabelError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(question_labels.summarize(labels.values()))
    return 0


def _eval_ingestion(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engines = args.engine or [
        e
        for e in Engine
        if e is Engine.BASELINE or (e is not Engine.VISION and docling_parser.is_installed())
    ]
    try:
        labels = ingestion_eval.load_labels(args.labels)
        cache = None if args.no_cache else default_cache("vision")
        report = ingestion_eval.run(labels, args.data, engines, cache)
    except ingestion_eval.BenchmarkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(ingestion_eval.render(report))
    if args.out:
        args.out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


def render(document: Document, page: int | None = None) -> str:
    """Human-readable view: a summary line, the issues, then each page's blocks."""
    flagged = [p for p in document.pages if p.issues]
    lines = [
        f"{document.source_name} · {document.format.upper()} · "
        f"{len(document.pages)} {document.unit}s · {document.parser}",
        f"{len(flagged)} {document.unit}(s) with issues",
    ]
    lines += [f"  {document.unit} {p.number}: {'; '.join(p.issues)}" for p in flagged]

    pages = [document.page(page)] if page is not None else document.pages
    for p in pages:
        lines += ["", f"── {document.unit} {p.number} ──"]
        lines += [f"[{block.kind}] {block.text}" for block in p.blocks] or ["(no text)"]
    return "\n".join(lines)


def render_questions(questions: QuestionSet) -> str:
    """Human-readable view: each question with its answer, explanation and source."""
    unit = questions.unit
    lines = [
        f"{questions.source_name} · {len(questions.questions)} questions · "
        f"{len(questions.rejected)} rejected · {questions.model}",
        "topics: " + ", ".join(t.id for t in questions.topics.topics),
    ]
    for n, q in enumerate(questions.questions, start=1):
        kind = "multiple choice" if isinstance(q, MultipleChoice) else "true/false"
        lines += ["", f"{n}. [{kind} · {q.bloom} · {', '.join(q.topic_ids)}]", f"   {q.question}"]
        if isinstance(q, MultipleChoice):
            for i, option in enumerate(q.options):
                mark = "*" if i == q.answer else " "
                lines.append(f"  {mark} {'abcdefgh'[i]}) {option}")
        else:
            lines.append(f"   answer: {'true' if q.answer else 'false'}")
        lines += [
            f"   why: {q.explanation}",
            f'   source: {unit} {q.source.page}, "{q.source.quote}"',
        ]
    if questions.rejected:
        lines += ["", "rejected:"]
        lines += [
            f"  - {r.question.question} ({'; '.join(r.problems)})" for r in questions.rejected
        ]
    lines += [f"warning: {w}" for w in questions.warnings]
    return "\n".join(lines)


def render_usage(usages: list[tuple[str, Usage]]) -> str:
    parts = []
    for name, usage in usages:
        if not (usage.calls or usage.cached):
            continue
        cost = "unknown cost" if usage.cost_usd is None else f"${usage.cost_usd:.2f}"
        cached = f", {usage.cached} from cache" if usage.cached else ""
        parts.append(f"{name}: {usage.calls} calls, {cost}{cached}")
    return "cost: " + ("; ".join(parts) if parts else "no model calls")


if __name__ == "__main__":
    sys.exit(main())
