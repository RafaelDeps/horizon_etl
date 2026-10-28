"""Derive candidate horizon_ids from a horizon.db and count collisions per rule.

Read-only. Usage: python -I sim_horizon_ids.py <db>
"""
import hashlib
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict

con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
q = con.execute


def norm(v):
    t = unicodedata.normalize("NFD", str(v or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
    return " ".join(t.lower().split())


def h(*parts):
    return hashlib.sha256("|".join(norm(p) for p in parts).encode()).hexdigest()[:12]


def slug(v):
    return norm(v).replace(" ", "-")


LATTES = re.compile(r"lattes\.cnpq\.br/(\d{16})")
CNPQ = re.compile(r"espelhogrupo/(\w+)")

ids = defaultdict(dict)  # entity_type -> {entity_id: horizon_id}
rule = defaultdict(Counter)  # entity_type -> Counter(rule name)

# --- matches: canonical entity -> list of (source_system, type, record_id)
matches = defaultdict(list)
for et, eid, ss, st, rid in q(
    "select em.canonical_entity_type, em.canonical_entity_id, sr.source_system, "
    "sr.source_entity_type, sr.source_record_id from entity_matches em "
    "join source_records sr on sr.id = em.source_record_id"
):
    matches[(et, eid)].append((ss, st, rid or ""))

# --- persons
lattes_of = {}
for rid, url in q("select id, cnpq_url from researchers"):
    m = LATTES.search(url or "")
    if m:
        lattes_of[rid] = m.group(1)
for (et, eid), ms in matches.items():
    if et == "researcher":
        for ss, st, rid in ms:
            if st == "researcher_profile" and re.fullmatch(r"\d{16}", rid):
                lattes_of.setdefault(eid, rid)
for pid, name in q("select id, name from persons"):
    if pid in lattes_of:
        ids["person"][pid] = f"person:lattes:{lattes_of[pid]}"
        rule["person"]["lattes_id"] += 1
    else:
        ids["person"][pid] = f"person:h:{h(name)}"
        rule["person"]["name"] += 1

# --- research groups (joined inheritance on teams)
for gid, url, name in q(
    "select rg.id, rg.cnpq_url, t.name from research_groups rg join teams t on t.id = rg.id"
):
    m = CNPQ.search(url or "")
    if m:
        ids["group"][gid] = f"group:cnpq:{m.group(1)}"
        rule["group"]["cnpq_id"] += 1
    else:
        ids["group"][gid] = f"group:sigpesq:h:{h(name)}"
        rule["group"]["sigpesq_name"] += 1

# --- initiatives and advisorships
adv = {r[0] for r in q("select id from advisorships")}
for iid, name, tname in q(
    "select i.id, i.name, it.name from initiatives i "
    "left join initiative_types it on it.id = i.initiative_type_id"
):
    et = "advisorship" if iid in adv else "initiative"
    ms = matches.get((et, iid), []) + matches.get(
        ("initiative" if et == "advisorship" else "advisorship", iid), []
    )
    pick = None
    for ss, st, rid in ms:
        if rid.startswith("sigpesq workplan|"):
            pick = ("sigpesq_workplan", f"advisorship:sigpesq-pt:{rid.split('|',1)[1].replace('|','-')}")
            break
        if rid.startswith("sigpesq project|"):
            pick = ("sigpesq_code", f"initiative:sigpesq-pj:{rid.split('|',1)[1]}")
            break
        if rid.startswith("PJ "):
            pick = ("pj_code", f"initiative:sigpesq-pj:{rid[3:]}")
            break
    if not pick:
        for ss, st, rid in ms:
            if rid.startswith("lattes project|") or rid.startswith("lattes advisorship|") or rid.startswith("sigpesq advisorship|"):
                origin = "lattes" if rid.startswith("lattes") else "sigpesq"
                pick = (f"{origin}_identity", f"{et}:{origin}:h:{h(rid)}")
                break
    if not pick:
        pick = ("name_fallback", f"{et}:h:{h(tname, name)}")
    rule[et][pick[0]] += 1
    ids[et][iid] = pick[1]

# --- articles
for aid, title, doi, year, typ, venue, vol, pages in q(
    "select id, title, doi, year, type, journal_conference, volume, pages from articles"
):
    d = (doi or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    if d:
        ids["article"][aid] = f"article:doi:{d}"
        rule["article"]["doi"] += 1
    else:
        ids["article"][aid] = f"article:h:{h(title, year, typ, venue)}"
        rule["article"]["title_year_type_venue"] += 1

for pid, title, year, ptype, pub in q(
    "select id, title, year, production_type_id, publisher from research_productions"
):
    ids["production"][pid] = f"production:h:{h(title, year, ptype)}"
    rule["production"]["title_year_type"] += 1

# --- children of persons
P = ids["person"]
for eid, rid, et, title, sy in q(
    "select id, researcher_id, education_type_id, title, start_year from academic_educations"
):
    ids["education"][eid] = f"{P.get(rid,'?')}/education:h:{h(et, title, sy)}"
    rule["education"]["parent+type+course+start"] += 1
for eid, rid, inst, sy, ey, role, bond in q(
    "select id, researcher_id, institution_name, start_year, end_year, role_function, bond from professional_activities"
):
    ids["professional_activity"][eid] = f"{P.get(rid,'?')}/activity:h:{h(inst, sy, ey, role, bond)}"
    rule["professional_activity"]["parent+inst+years+role+bond"] += 1
for eid, rid, title, year in q("select id, researcher_id, title, year from awards"):
    ids["award"][eid] = f"{P.get(rid,'?')}/award:h:{h(title, year)}"
    rule["award"]["parent+title+year"] += 1
for eid, rid, lang in q(
    "select p.id, p.researcher_id, l.name from proficiencies p left join languages l on l.id=p.language_id"
):
    ids["proficiency"][eid] = f"{P.get(rid,'?')}/proficiency:{slug(lang)}"
    rule["proficiency"]["parent+language"] += 1

# --- teams that are not research groups: child of the initiative they staff
G = set(ids["group"])
team_init = defaultdict(list)
for iid, tid in q("select initiative_id, team_id from initiative_teams"):
    team_init[tid].append(iid)
for tid, name in q("select id, name from teams"):
    if tid in G:
        continue
    inits = sorted(ids["initiative"].get(i) or ids["advisorship"].get(i) or "?" for i in team_init.get(tid, []))
    if inits:
        ids["team"][tid] = f"{inits[0]}/team"
        rule["team"]["initiative"] += 1
    else:
        ids["team"][tid] = f"team:h:{h(name)}"
        rule["team"]["name"] += 1

# --- reference tables
for t, et in [("knowledge_areas", "knowledge-area"), ("organizations", "organization"),
              ("organizational_units", "campus"), ("initiative_types", "initiative-type"),
              ("production_types", "production-type"), ("roles", "role"),
              ("languages", "language"), ("education_types", "education-type")]:
    for rid, name in q(f"select id, name from {t}"):
        ids[et][rid] = f"{et}:{slug(name)}"
        rule[et]["slug"] += 1

# fellowships: same programme name with different values are different fellowships
for rid, name, value in q("select id, name, value from fellowships"):
    v = "" if value is None else ("%g" % value)
    ids["fellowship"][rid] = f"fellowship:{slug(name)}:{v}"
    rule["fellowship"]["slug+value"] += 1

# --- report
allc = Counter()
print(f"{'entity':24} {'rows':>6} {'collisions':>10} {'rows in collisions':>18}  rules / example")
for et, m in ids.items():
    c = Counter(m.values())
    allc.update(c)
    bad = {k: v for k, v in c.items() if v > 1}
    ex = next(iter(bad), "")
    print(f"{et:24} {len(m):6} {len(bad):10} {sum(bad.values()):18}  {dict(rule[et])} {ex[:60]}")
cross = sum(1 for v in allc.values() if v > 1)
unknown_parent = sum(1 for m in ids.values() for v in m.values() if v.startswith("?"))
print("ids shared across types:", cross, "| children without parent id:", unknown_parent)
print("max id length:", max(len(v) for m in ids.values() for v in m.values()))
