"""Gate for the committed export archive (spec 029).

Refuses an archive that has no manifest, was not built by the official
workflow, is over the size limit, or was anonymized with another key than the
archive already at ``--ref``. Without ``--warn-only`` a refusal exits 1 (CI and
the pre-commit hook). With it (the weekly's commit step) a refusal prints a
workflow warning, puts the archive from the index back and exits 0, so the run
does not fail and nothing is published.

    python -m src.scripts.check_publishable_archive PATH [--ref HEAD] [--warn-only]

Output holds no archive content.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import zipfile
from typing import List, Optional

MANIFEST_NAME = "export_manifest.json"
# The archive is committed to git: same limit as the build (spec 029).
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def _manifest_of(archive: zipfile.ZipFile) -> Optional[dict]:
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME))
    except (KeyError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _archive_at_ref(path: str, ref: str) -> Optional[bytes]:
    """The archive as committed at ``ref``, or None when there is none."""
    result = subprocess.run(
        ["git", "show", f"{ref}:./{os.path.relpath(path)}"], capture_output=True
    )
    return result.stdout if result.returncode == 0 else None


def refusals(path: str, ref: Optional[str]) -> List[str]:
    """Why the archive cannot be published; empty when it can."""
    if not os.path.isfile(path):
        return [f"{path} does not exist"]
    reasons = []
    size = os.path.getsize(path)
    if size > MAX_ARCHIVE_BYTES:
        reasons.append(
            f"the archive is {size} bytes, over the {MAX_ARCHIVE_BYTES} limit"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _manifest_of(archive)
    except zipfile.BadZipFile:
        return [*reasons, "the file is not a zip archive"]
    if manifest is None:
        return [*reasons, f"the archive has no {MANIFEST_NAME}"]
    if manifest.get("official") is not True:
        reasons.append("the archive was not built by the official workflow")
    if ref:
        committed = _archive_at_ref(path, ref)
        if committed is not None:
            try:
                with zipfile.ZipFile(io.BytesIO(committed)) as old:
                    previous = _manifest_of(old)
            except zipfile.BadZipFile:
                previous = None
            if previous and previous.get("key_fingerprint") != manifest.get(
                "key_fingerprint"
            ):
                reasons.append(
                    f"the anonymization key differs from the archive at {ref}"
                )
    return reasons


def _restore(path: str) -> None:
    """Puts the archive from the index back; a new file is removed."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path], capture_output=True
    )
    if tracked.returncode == 0:
        subprocess.run(["git", "checkout", "--", path], capture_output=True)
    elif os.path.exists(path):
        os.remove(path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path")
    parser.add_argument("--ref", default=None, help="compare with the archive here")
    parser.add_argument("--warn-only", action="store_true")
    args = parser.parse_args(argv)

    reasons = refusals(args.path, args.ref)
    if not reasons:
        print(f"{args.path}: publishable")
        return 0
    if args.warn_only:
        for reason in reasons:
            print(f"::warning::{args.path} not published: {reason}")
        _restore(args.path)
        return 0
    for reason in reasons:
        print(f"{args.path} refused: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
