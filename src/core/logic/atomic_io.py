"""Atomic file-write helpers.

Writers in this project must never leave a truncated/corrupt file behind:
exports overwrite the previous good version in place, so a crash mid-write
would destroy data. All JSON/artifact writes go through these helpers, which
write to a temporary file in the same directory, fsync it, and atomically
rename it onto the final path.
"""

import json
import os
import tempfile
from typing import Any


def atomic_write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    """Write text to `path` atomically (temp file + fsync + os.replace)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".tmp-", suffix=os.path.basename(path)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str, data: Any, *, indent: int = 4, ensure_ascii: bool = False
) -> None:
    """Serialize `data` as strict JSON and write it to `path` atomically.

    ``allow_nan=False`` turns Python's non-standard ``NaN``/``Infinity`` tokens
    into a ValueError instead of emitting JSON that strict consumers (JS) choke
    on.
    """
    atomic_write_text(
        path,
        json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, allow_nan=False),
    )
