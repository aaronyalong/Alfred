"""Command-line interface for running and inspecting the pipeline locally."""

import argparse
import sys
from pathlib import Path

from alfred.evals import ingestion as ingestion_eval
from alfred.ingest import Document, Engine, IngestError, docling_parser, ingest


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

    eval_cmd = commands.add_parser("eval", help="run an evaluation")
    evals = eval_cmd.add_subparsers(dest="evaluation", required=True)
    bench = evals.add_parser("ingestion", help="score ingestion engines against labeled facts")
    bench.add_argument(
        "--engine",
        type=Engine,
        choices=list(Engine),
        action="append",
        help="engine to run (repeatable; default: every installed engine)",
    )
    bench.add_argument("--data", type=Path, default=Path("data/private"))
    bench.add_argument("--labels", type=Path, default=Path("evals/ingestion/labels.toml"))
    bench.add_argument("--out", type=Path, help="also write the full report as JSON")
    bench.set_defaults(handler=_eval_ingestion)

    args = parser.parse_args(argv)
    return args.handler(parser, args)


def _ingest(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.file.is_file():
        parser.error(f"no such file: {args.file}")
    try:
        document = ingest(args.file, engine=args.engine)
        if args.page is not None:
            document.page(args.page)  # fail early on a page number that doesn't exist
    except (IngestError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(document.model_dump_json(indent=2) if args.json else render(document, args.page))
    return 0


def _eval_ingestion(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    engines = args.engine or [
        e for e in Engine if e is Engine.BASELINE or docling_parser.is_installed()
    ]
    try:
        report = ingestion_eval.run(ingestion_eval.load_labels(args.labels), args.data, engines)
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


if __name__ == "__main__":
    sys.exit(main())
