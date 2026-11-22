"""Where uploaded files wait until the worker has parsed them.

Each upload gets its own folder, named by the document's id, so a file name chosen by the
uploader can never collide with or overwrite another file.
"""

import shutil
import uuid
from pathlib import Path

_FALLBACK_NAME = "upload"


def safe_name(filename: str | None) -> str:
    """The upload's file name with any folders removed, so it can't point outside its folder."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable()).strip()
    return name[:255] if name not in ("", ".", "..") else _FALLBACK_NAME


def upload_path(upload_dir: Path, document_id: uuid.UUID, name: str) -> Path:
    return upload_dir / str(document_id) / name


def discard(upload_dir: Path, document_id: uuid.UUID) -> None:
    shutil.rmtree(upload_dir / str(document_id), ignore_errors=True)
