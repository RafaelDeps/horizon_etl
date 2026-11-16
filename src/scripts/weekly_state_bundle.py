"""The weekly state travels in one encrypted bundle (spec 029).

``db/horizon.db``, ``data/raw`` and ``cache/`` are packed byte for byte into a
tar.gz and sealed with AES-256-GCM, so the public run artifact holds no
personal data and the next run still restores the exact files the skip hashes
were taken from. Only text files that pass a scan are staged next to the
bundle. Format and states: specs/029-pii-safe-exports/data-model.md.

Nothing here can fail the run: ``seal`` always exits 0 and ends in a state
(``sealed``, ``skipped`` or ``failed``), never uploading plain state.

Usage:
    PYTHONPATH=. python -m src.scripts.weekly_state_bundle seal --out artifact_out
"""

import argparse
import base64
import binascii
import gzip
import io
import json
import os
import posixpath
import shutil
import sys
import tarfile
import tempfile
from typing import Iterable, List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger

from src.adapters.database.sqlite_settings import finalize_sqlite_database
from src.core.logic.pii_anonymizer import scan_text
from src.flows.maintenance.anonymize_backfill import verify_database
from src.scripts.restore_weekly_artifact import RestoreError

KEY_ENV = "HORIZON_STATE_KEY"
BUNDLE_NAME = "weekly_state.bundle"
STAGE_REPORT = "artifact_stage_report.json"
# Folders whose text files may be published beside the bundle, and the
# extensions that can be scanned.
PUBLIC_FOLDERS = (
    os.path.join("data", "reports"),
    os.path.join("data", "exports", "docentes"),
)
PUBLIC_EXTENSIONS = {".json", ".csv", ".md", ".txt", ".html"}

MAGIC = b"HZSTATE1"
NONCE_BYTES = 12
KEY_BYTES = 32
# AES-GCM in one call (cryptography) takes less than 2 GiB.
MAX_PLAINTEXT_BYTES = 2**31 - 2

# The tar roots the bundle may hold; a directory entry for a parent is allowed.
_BUNDLE_ITEMS = ("db/horizon.db", "data/raw", "cache")
_ALLOWED_DIRS = {"db", "data", "data/raw", "cache"}


def parse_key(value: Optional[str]) -> Optional[bytes]:
    """The key as 32 bytes, or None unless the text is exactly 32 bytes in
    base64url. A passphrase never becomes a key."""
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        raw = base64.b64decode(
            text.replace("-", "+").replace("_", "/") + "=" * (-len(text) % 4),
            validate=True,
        )
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == KEY_BYTES else None


def _encrypt_payload(plain: bytes, key: bytes) -> bytes:
    if len(plain) > MAX_PLAINTEXT_BYTES:
        raise RestoreError("state bundle: too large")
    nonce = os.urandom(NONCE_BYTES)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, MAGIC)


def seal_bundle(src_root: str, out_path: str, key: Optional[str]) -> dict:
    """Packs the three items of ``src_root`` and writes the encrypted bundle.
    The plain tar.gz exists only in a temporary folder inside ``src_root``,
    removed before returning."""
    raw_key = parse_key(key)
    if raw_key is None:
        raise RestoreError("state bundle: no key")
    work = tempfile.mkdtemp(prefix=".seal-", dir=src_root)
    try:
        tar_path = os.path.join(work, "state.tar.gz")
        members = 0
        with tarfile.open(tar_path, "w:gz") as tar:
            for item in _BUNDLE_ITEMS:
                path = os.path.join(src_root, *item.split("/"))
                if os.path.exists(path):
                    tar.add(path, arcname=item)
                    members += 1
        if os.path.getsize(tar_path) > MAX_PLAINTEXT_BYTES:
            raise RestoreError("state bundle: too large")
        with open(tar_path, "rb") as fh:
            sealed = _encrypt_payload(fh.read(), raw_key)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(sealed)
        return {"bundle_bytes": len(sealed), "items": members}
    except BaseException:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _decrypt(data: bytes, keys: Iterable[Optional[str]]) -> bytes:
    raw_keys = [k for k in (parse_key(v) for v in keys) if k is not None]
    if not raw_keys:
        raise RestoreError("state bundle: no key")
    if len(data) < len(MAGIC) + NONCE_BYTES + 16 or not data.startswith(MAGIC):
        raise RestoreError("state bundle: failed authentication")
    nonce = data[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
    body = data[len(MAGIC) + NONCE_BYTES :]
    for raw_key in raw_keys:
        try:
            return AESGCM(raw_key).decrypt(nonce, body, MAGIC)
        except InvalidTag:
            continue
    raise RestoreError("state bundle: failed authentication")


def _vet_members(tar: tarfile.TarFile) -> None:
    """Refuses links, devices and any path outside the three items."""
    for member in tar.getmembers():
        name = member.name
        if not (member.isfile() or member.isdir()):
            raise RestoreError("state bundle: unsafe member")
        if name.startswith("/") or "\\" in name or ".." in name.split("/"):
            raise RestoreError("state bundle: unsafe member")
        clean = posixpath.normpath(name)
        if clean != name.rstrip("/"):
            raise RestoreError("state bundle: unsafe member")
        inside = (
            clean == "db/horizon.db"
            or clean.startswith("data/raw/")
            or clean.startswith("cache/")
        )
        if not inside and not (member.isdir() and clean in _ALLOWED_DIRS):
            raise RestoreError("state bundle: unsafe member")


def open_bundle(path: str, dest: str, keys: Iterable[Optional[str]]) -> None:
    """Authenticates and decrypts in one call (no plaintext before the tag
    check), vets every member, then extracts. Raises ``RestoreError`` with a
    reason that holds neither key material nor file content."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        plain = _decrypt(data, keys)
        del data
        with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
            _vet_members(tar)
            tar.extractall(dest, filter="data")
    except RestoreError:
        raise
    except (tarfile.TarError, gzip.BadGzipFile, EOFError):
        raise RestoreError("state bundle: unreadable")
    except (OSError, MemoryError) as exc:
        raise RestoreError(f"state bundle: {type(exc).__name__}")


def stage_public(root: str, out_dir: str) -> dict:
    """Copies the report and docentes text files into ``out_dir/public``.
    Each file is scanned (counts only); one with a match is left out, as is
    anything that is not scannable text."""
    staged = 0
    left_out: List[str] = []
    for folder in PUBLIC_FOLDERS:
        base = os.path.join(root, folder)
        for current, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(current, name)
                relative = os.path.relpath(path, root)
                if os.path.splitext(name)[1].lower() not in PUBLIC_EXTENSIONS:
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        _, counts = scan_text(fh.read())
                except (OSError, UnicodeDecodeError):
                    left_out.append(relative.replace(os.sep, "/"))
                    continue
                if any(counts.values()):
                    left_out.append(relative.replace(os.sep, "/"))
                    continue
                target = os.path.join(out_dir, "public", relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(path, target)
                staged += 1
    return {"public_files": staged, "public_left_out": left_out}


def _warn(message: str) -> None:
    """A workflow warning line, and a line in the job summary when in CI."""
    print(f"::warning::{message}")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(f"### Artifact\n{message}\n")
        except OSError:
            pass


def seal(root: str, out_dir: str) -> dict:
    """Steps of contracts/state-bundle.md "Seal"; each is guarded."""
    os.makedirs(out_dir, exist_ok=True)
    database = os.path.join(root, "db", "horizon.db")
    # 1-2. A killed run may have left a log; verify what the database holds.
    try:
        finalize_sqlite_database(f"sqlite:///{os.path.abspath(database)}")
        if os.path.exists(database):
            verify_database(database, os.path.join(root, "data", "reports"))
    except Exception as exc:
        logger.warning("Database finalize/verify skipped: {}", type(exc).__name__)

    # 3-4. The bundle, or the reason there is none.
    bundle_path = os.path.join(out_dir, BUNDLE_NAME)
    state, bundle_bytes = "skipped", 0
    if parse_key(os.environ.get(KEY_ENV)) is None:
        _warn(f"No usable {KEY_ENV}: the state is not saved for the next run.")
    else:
        try:
            bundle_bytes = seal_bundle(root, bundle_path, os.environ[KEY_ENV])[
                "bundle_bytes"
            ]
            state = "sealed"
        except Exception as exc:
            reason = exc.reason if isinstance(exc, RestoreError) else type(exc).__name__
            if os.path.exists(bundle_path):
                os.remove(bundle_path)
            state = "failed"
            _warn(f"The state bundle was not written ({reason}).")

    # 5. Public text files, then the report that describes the staging.
    report = {"state": state, "bundle_bytes": bundle_bytes}
    report.update(stage_public(root, out_dir))
    os.makedirs(os.path.join(out_dir, "public"), exist_ok=True)
    with open(
        os.path.join(out_dir, "public", STAGE_REPORT), "w", encoding="utf-8"
    ) as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    logger.info(
        "Artifact staged: state={} bundle_bytes={} public_files={} left_out={}",
        state,
        bundle_bytes,
        report["public_files"],
        len(report["public_left_out"]),
    )
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seal_parser = sub.add_parser("seal", help="stage the artifact folder")
    seal_parser.add_argument("--out", required=True)
    seal_parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        seal(os.path.abspath(args.root), os.path.abspath(args.out))
    except Exception as exc:  # the run never fails because of the artifact
        _warn(f"Artifact staging failed ({type(exc).__name__}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
