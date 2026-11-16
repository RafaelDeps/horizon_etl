"""Removes personal data from the git history of the published repositories
(spec 029). NOT run by the feature: the maintainer runs it by hand, on a fresh
mirror clone, after reading specs/029-pii-safe-exports/contracts/history-purge.md.

Run it with git-filter-repo's own interpreter (the module is not importable
from the project's):

    PY=~/.local/share/uv/tools/git-filter-repo/bin/python
    "$PY" src/scripts/purge_history_pii.py plan    --repo /path/mirror.git
    "$PY" src/scripts/purge_history_pii.py rewrite --repo /path/mirror.git
    "$PY" src/scripts/purge_history_pii.py verify  --repo /path/mirror.git

It touches only the repository given in ``--repo``. Output holds counts and
group names, never values.

The module is standalone on purpose (it must run under another interpreter);
the detectors below are copies of the ones in
``src/core/logic/pii_anonymizer.py`` and a test keeps them equal. The
replacements are constants, so the rewrite is deterministic and needs no key.
"""

import argparse
import fnmatch
import io
import re
import subprocess
import sys
import zipfile
from typing import Iterable, List, Optional, Tuple

EMAIL_REPLACEMENT = "redacted@anon.lgpd"
PHONE_REPLACEMENT = "LGPD-PHONE-redacted"
CPF_REPLACEMENT = "LGPD-redacted"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@(?!anon\.lgpd)[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"\+55[\s-]?\(?\d{2}\)?[\s-]?\d{4,5}[\s-]?\d{4}"
    r"|\(\d{2,3}\)[\s-]?\d{4,5}[\s-]?\d{4}"
)
CPF_RE = re.compile(r"(?<![\d.\-])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d\-])")

_FIELD_TYPES = {
    **{
        n: "email"
        for n in ("OrientadoEmail", "OrientadorEmail", "email", "contact_email")
    },
    **{n: "cpf" for n in ("OrientadoCpf", "OrientadorCpf", "identification_id")},
    **{
        n: "phone"
        for n in (
            "CelularOrientador",
            "CelularOrientado",
            "telefone",
            "fax",
            "phone",
            "celular",
        )
    },
}
_REPLACEMENTS = {
    "email": EMAIL_REPLACEMENT,
    "cpf": CPF_REPLACEMENT,
    "phone": PHONE_REPLACEMENT,
}
_KNOWN_FIELD_RE = re.compile(
    r'"(' + "|".join(map(re.escape, sorted(_FIELD_TYPES))) + r')"'
    r'(\s*:\s*)("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?)'
)
_HASH_RE = re.compile(r'("(?:payload_hash|value_hash)"\s*:\s*)"[^"]+"')

# Blobs reachable at these paths are the targets (user decision D7).
TARGET_PATTERNS = ("data/exports/*.zip", "cache/*", ".prefect/*")

COUNT_KEYS = ("email", "phone", "cpf", "known_field", "hash", "terms", "unreadable")


def _empty_counts() -> dict:
    return {key: 0 for key in COUNT_KEYS}


def _merge(total: dict, other: dict) -> None:
    for key, value in other.items():
        total[key] = total.get(key, 0) + value


def _is_replacement(field_type: str, value: str) -> bool:
    return value == _REPLACEMENTS[field_type]


def _redact_text(
    text: str, extra_terms: Iterable[str], blank_hashes: bool
) -> Tuple[str, dict]:
    counts = _empty_counts()

    def known(match: "re.Match") -> str:
        field, sep, raw = match.groups()
        field_type = _FIELD_TYPES[field]
        value = raw[1:-1] if raw.startswith('"') else raw
        # A short number is a count, not a document or phone number.
        if not raw.startswith('"') and len(value.lstrip("-")) < 6:
            return match.group(0)
        if not value or _is_replacement(field_type, value):
            return match.group(0)
        counts["known_field"] += 1
        return f'"{field}"{sep}"{_REPLACEMENTS[field_type]}"'

    for term in extra_terms:
        if term and term in text:
            counts["terms"] += text.count(term)
            replacement = EMAIL_REPLACEMENT if "@" in term else CPF_REPLACEMENT
            text = text.replace(term, replacement)
    text = _KNOWN_FIELD_RE.sub(known, text)
    for kind, pattern, replacement in (
        ("email", EMAIL_RE, EMAIL_REPLACEMENT),
        ("phone", PHONE_RE, PHONE_REPLACEMENT),
        ("cpf", CPF_RE, CPF_REPLACEMENT),
    ):
        text, number = pattern.subn(replacement, text)
        counts[kind] += number
    if blank_hashes:
        text, number = _HASH_RE.subn(r'\1""', text)
        counts["hash"] += number
    return text, counts


def redact_bytes(
    data: bytes, extra_terms: Iterable[str] = (), blank_hashes: bool = False
) -> Tuple[bytes, dict]:
    """Redacts a text blob. Returns the same bytes object when nothing
    changed; a blob that is not UTF-8 text is reported (``unreadable``) and
    left as it is."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        counts = _empty_counts()
        counts["unreadable"] = 1
        return data, counts
    new_text, counts = _redact_text(text, list(extra_terms), blank_hashes)
    if new_text == text:
        return data, counts
    return new_text.encode("utf-8"), counts


def redact_zip(
    data: bytes, extra_terms: Iterable[str] = (), blank_hashes: bool = True
) -> Tuple[bytes, dict]:
    """Redacts the members of a zip given as bytes. A member without hits is
    copied with its own date and compression; the blob is replaced only when
    something changed. Nested zips are handled the same way."""
    counts = _empty_counts()
    terms = list(extra_terms)
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        counts["unreadable"] = 1
        return data, counts
    members = []
    changed = False
    with source:
        for info in source.infolist():
            content = source.read(info)
            if info.is_dir():
                new_content = content
            elif content[:4] == b"PK\x03\x04":
                new_content, inner = redact_zip(content, terms, blank_hashes)
                _merge(counts, inner)
            else:
                new_content, inner = redact_bytes(content, terms, blank_hashes)
                _merge(counts, inner)
            if new_content is not content:
                changed = True
            members.append((info, new_content))
    if not changed:
        return data, counts
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for info, content in members:
            out.writestr(info, content, compress_type=info.compress_type)
    return buffer.getvalue(), counts


# ----------------------------------------------------------------------------
# Repository access. Every git command runs with ``-C <repo>`` on the path
# given in --repo; nothing else is ever touched.
# ----------------------------------------------------------------------------


def _git(repo: str, *args: str, data: Optional[bytes] = None, check: bool = True):
    result = subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {args[0]} failed: {result.stderr.decode().strip()}")
    return result


def _group_of(path: str) -> Optional[str]:
    for pattern in TARGET_PATTERNS:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def find_targets(repo: str, revisions: Iterable[str]) -> dict:
    """Blob id -> (group, path) for every blob reachable at a target path.
    Computed first, from rev-list, because paths are not available in a blob
    callback."""
    listing = _git(repo, "rev-list", "--objects", *revisions).stdout.decode(
        "utf-8", "replace"
    )
    candidates = {}
    for line in listing.splitlines():
        sha, _, path = line.partition(" ")
        group = _group_of(path) if path else None
        if group and sha not in candidates:
            candidates[sha] = (group, path)
    if not candidates:
        return {}
    kinds = _git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        data=("\n".join(candidates) + "\n").encode(),
    ).stdout.decode()
    blobs = {line.split()[0] for line in kinds.splitlines() if line.endswith(" blob")}
    return {sha: info for sha, info in candidates.items() if sha in blobs}


def _read_blob(repo: str, sha: str) -> bytes:
    return _git(repo, "cat-file", "blob", sha).stdout


def _redact_target(
    path: str, data: bytes, terms: List[str], blank_hashes: bool
) -> Tuple[bytes, dict]:
    if path.lower().endswith(".zip"):
        return redact_zip(data, terms, blank_hashes)
    return redact_bytes(data, terms, blank_hashes)


def _read_terms(path: Optional[str]) -> List[str]:
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh if line.strip()]


def _refs(repo: str) -> List[str]:
    out = _git(repo, "for-each-ref", "--format=%(refname)").stdout.decode()
    return out.split()


def _scan(repo: str, targets: dict, terms: List[str], blank_hashes: bool) -> dict:
    """Per group: blobs, blobs that would change, and the summed counts."""
    groups = {}
    for sha, (group, path) in targets.items():
        entry = groups.setdefault(
            group, {"blobs": 0, "changed": 0, "counts": _empty_counts()}
        )
        data = _read_blob(repo, sha)
        new, counts = _redact_target(path, data, terms, blank_hashes)
        entry["blobs"] += 1
        entry["changed"] += 1 if new is not data else 0
        _merge(entry["counts"], counts)
    return groups


def _print_groups(groups: dict) -> None:
    for group in sorted(groups):
        entry = groups[group]
        shown = " ".join(f"{k}={v}" for k, v in entry["counts"].items() if v)
        print(
            f"group {group}: blobs={entry['blobs']} to_change={entry['changed']}"
            + (f" {shown}" if shown else "")
        )


def command_plan(args: argparse.Namespace) -> int:
    repo = args.repo
    refs = _refs(repo)
    print(f"refs: {len(refs)}")
    for ref in refs:
        print(f"ref {ref}")
    terms = _read_terms(args.extra_terms_file)
    targets = find_targets(repo, ["--all"])
    _print_groups(_scan(repo, targets, terms, not args.no_redact_hashes))
    return 0


def _refuse_unless_bare(repo: str) -> None:
    bare = _git(repo, "rev-parse", "--is-bare-repository").stdout.decode().strip()
    if bare != "true":
        raise SystemExit("refused: the repository is not bare")


def _refuse_unless_fresh_mirror(repo: str) -> None:
    mirror = _git(repo, "config", "--get", "remote.origin.mirror", check=False)
    if mirror.stdout.decode().strip() != "true":
        raise SystemExit("refused: not a fresh mirror clone (git clone --mirror)")
    remotes = _git(repo, "remote").stdout.decode().split()
    if remotes != ["origin"]:
        raise SystemExit("refused: the repository has remotes other than origin")
    push = _git(repo, "config", "--get-regexp", r"^remote\..*\.push", check=False)
    if push.stdout.strip():
        raise SystemExit("refused: a remote is configured for push")


def command_rewrite(args: argparse.Namespace) -> int:
    repo = args.repo
    _refuse_unless_bare(repo)
    terms = _read_terms(args.extra_terms_file)
    blank_hashes = not args.no_redact_hashes

    # A repository that is already clean (a second pass) needs nothing, and
    # filter-repo has removed its origin remote by then: read-only check first.
    pulls = [r for r in _refs(repo) if r.startswith("refs/pull/")]
    first = _scan(repo, find_targets(repo, ["--all"]), terms, blank_hashes)
    if not pulls and not any(entry["changed"] for entry in first.values()):
        _print_groups(first)
        print("nothing to rewrite")
        return 0

    _refuse_unless_fresh_mirror(repo)

    # Pull request refs cannot be pushed; remove them before the rewrite.
    for ref in pulls:
        _git(repo, "update-ref", "-d", ref)
    print(f"removed {len(pulls)} pull request ref(s)")

    targets = find_targets(repo, ["--all"])
    groups = _scan(repo, targets, terms, blank_hashes)
    _print_groups(groups)
    if not any(entry["changed"] for entry in groups.values()):
        print("nothing to rewrite")
        return 0

    # Lazy: only this mode needs git-filter-repo.
    import os

    import git_filter_repo as fr

    ids = {sha.encode("ascii"): info[1] for sha, info in targets.items()}

    def blob_callback(blob, _metadata) -> None:
        path = ids.get(blob.original_id)
        if path is None:
            return
        new, _counts = _redact_target(path, blob.data, terms, blank_hashes)
        if new is not blob.data:
            blob.data = new

    os.chdir(repo)
    options = fr.FilteringOptions.parse_args(["--quiet"])
    fr.RepoFilter(options, blob_callback=blob_callback).run()
    return 0


def command_verify(args: argparse.Namespace) -> int:
    repo = args.repo
    terms = _read_terms(args.terms_file)
    revisions = ["--branches", "--tags"]
    failed = False

    # Detectors over the target blobs, zip members included.
    targets = find_targets(repo, revisions)
    for group in TARGET_PATTERNS:
        blobs = hits = unreadable = 0
        for sha, (found, path) in targets.items():
            if found != group:
                continue
            data = _read_blob(repo, sha)
            _, counts = _redact_target(path, data, [], False)
            blobs += 1
            hits += sum(counts[k] for k in ("email", "phone", "cpf", "known_field"))
            if counts["unreadable"]:
                unreadable += 1
        # A zip that cannot be opened cannot be shown clean.
        bad = hits + (unreadable if group.endswith(".zip") else 0)
        print(f"group {group}: blobs={blobs} hits={hits} unreadable={unreadable}")
        failed = failed or bad > 0

    # The listed terms are searched in every blob and in commit messages.
    if terms:
        listing = _git(repo, "rev-list", "--objects", *revisions).stdout.decode(
            "utf-8", "replace"
        )
        shas = sorted({line.split(" ")[0] for line in listing.splitlines()})
        kinds = _git(
            repo,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
            data=("\n".join(shas) + "\n").encode(),
        ).stdout.decode()
        term_hits = 0
        for line in kinds.splitlines():
            sha, _, kind = line.partition(" ")
            if kind != "blob":
                continue
            data = _read_blob(repo, sha)
            if data[:4] == b"PK\x03\x04":
                _, counts = redact_zip(data, terms, False)
                term_hits += counts["terms"]
            else:
                term_hits += sum(data.count(t.encode("utf-8")) for t in terms)
        messages = _git(repo, "log", *revisions, "--format=%B").stdout.decode(
            "utf-8", "replace"
        )
        term_hits += sum(messages.count(t) for t in terms)
        print(f"terms: hits={term_hits}")
        failed = failed or term_hits > 0

    print("verify: " + ("FAILED" if failed else "clean"))
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "rewrite", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True, help="path of the mirror clone")
        if name != "verify":
            p.add_argument("--extra-terms-file", help="literal terms, one per line")
            p.add_argument("--no-redact-hashes", action="store_true")
        else:
            p.add_argument("--terms-file", help="literal terms, one per line")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return {"plan": command_plan, "rewrite": command_rewrite, "verify": command_verify}[
        args.command
    ](args)


if __name__ == "__main__":
    sys.exit(main())
