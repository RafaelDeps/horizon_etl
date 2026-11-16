"""Simulate stable tracking keys over source_records and count collisions.

A collision is one key that maps to more than one distinct (canonical) payload
hash inside a single fresh run: with a persistent database those rows would
overwrite each other every week. Read-only.

Usage: python -I sim_tracking_keys.py <db>
"""
import hashlib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)


def norm(v):
    if v is None:
        return ""
    t = unicodedata.normalize("NFD", str(v))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
    return " ".join(t.lower().split())


def canon(v):
    """Type-stable form: NaN/'nan'/'' -> None, numbers and strings -> trimmed text."""
    if isinstance(v, dict):
        return {k: canon(x) for k, x in v.items()}
    if isinstance(v, list):
        return [canon(x) for x in v]
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return None if s in ("", "nan", "NaN", "None") else s


def chash(p):
    return hashlib.sha256(
        json.dumps(canon(p), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def raw_hash(p):
    return json.dumps(p, sort_keys=True)


def lattes_id(f):
    m = re.search(r"_(\d{16})\.json$", f or "")
    return m.group(1) if m else "?"


def cnpq_id(f):
    m = re.search(r"espelhogrupo/(\w+)", f or "")
    return m.group(1) if m else "?"


def j(*parts):
    return "|".join(parts)


K = {
    ("cnpq_sync", "cnpq_group_payload"): lambda r, p: cnpq_id(r["file"]),
    ("cnpq_sync", "cnpq_group_member"): lambda r, p: j(
        cnpq_id(r["file"]), norm(p.get("name")), norm(p.get("role")),
        norm(p.get("data_inicio")), norm(p.get("data_fim"))),
    ("cnpq_sync", "cnpq_research_line"): lambda r, p: j(
        cnpq_id(r["file"]), r["rid"].split("|", 1)[1]),
    ("lattes_projects", "academic_education"): lambda r, p: j(
        lattes_id(r["file"]), norm(p.get("course_name")), norm(p.get("degree")),
        norm(p.get("start_year")), norm(p.get("end_year")),
        norm(p.get("institution") or p.get("description"))),
    ("lattes_projects", "researcher_profile"): lambda r, p: r["rid"],
    ("lattes_projects", "article"): lambda r, p: j(
        lattes_id(r["file"]), r["rid"], norm(p.get("type")),
        norm(p.get("journal_conference")), norm(p.get("volume")), norm(p.get("pages"))),
    ("lattes_projects", "initiative"): lambda r, p: j(lattes_id(r["file"]), r["rid"]),
    ("lattes_advisorships", "advisorship"): lambda r, p: j(
        lattes_id(r["file"]), r["rid"], norm(p.get("type")), norm(p.get("institution"))),
    ("sigpesq_advisorships", "advisorship"): lambda r, p: r["rid"],
    ("sigpesq_research_group", "research_group"): lambda r, p: r["rid"],
    ("sigpesq_research_projects", "initiative"): lambda r, p: r["rid"],
    ("sigpesq_project_files", "initiative"): lambda r, p: r["rid"],
}

run_max = con.execute(
    "select max(id) from ingestion_runs where id <= 7"
).fetchone()[0]
groups = defaultdict(list)
for s, t, rid, f, pj in con.execute(
    "select source_system, source_entity_type, source_record_id, source_file, "
    "raw_payload_json from source_records where ingestion_run_id <= ?",
    (run_max,),
):
    groups[(s, t)].append(
        {"rid": rid or "", "file": f or "", "p": json.loads(pj) if pj else {}}
    )


def collisions(rs, keyf, hashf):
    d = defaultdict(set)
    for r in rs:
        d[keyf(r)].add(hashf(r))
    bad = [k for k, v in d.items() if len(v) > 1]
    return len(bad), bad[:1]


print(f"{'source / type':45} {'rows':>6} {'today':>6} {'new':>6}  example of what remains")
tot_old = tot_new = 0
for (s, t), rs in sorted(groups.items()):
    old_n, _ = collisions(rs, lambda r: r["rid"], lambda r: raw_hash(r["p"]))
    kf = K[(s, t)]
    new_n, ex = collisions(rs, lambda r: kf(r, r["p"]), lambda r: chash(r["p"]))
    tot_old += old_n
    tot_new += new_n
    print(f"{s + ' / ' + t:45} {len(rs):6} {old_n:6} {new_n:6}  {repr(ex[0])[:60] if ex else ''}")
print(f"{'total':45} {'':6} {tot_old:6} {tot_new:6}")
