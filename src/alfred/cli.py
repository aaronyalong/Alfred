"""Command-line interface for running and inspecting the pipeline locally."""

import argparse
import sys
from pathlib import Path

from alfred.ingest import Document, Engine, IngestError, ingest


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

    args = parser.parse_args(argv)
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
