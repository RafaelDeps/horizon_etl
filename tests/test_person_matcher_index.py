"""PersonMatcher name index (spec 016): same answers as the pre-016 matcher.

The reference is OraclePersonMatcher, a verbatim copy of the class before spec
016 (tests/_name_matching_oracle.py). Both matchers run the same call sequence
against identical fake controllers and must return the same person every time.
"""

import os
import random
import subprocess
import sys
from types import SimpleNamespace

from _name_matching_oracle import OraclePersonMatcher, oracle_normalize_name
from loguru import logger

from src.core.logic.person_matcher import PersonMatcher

FIRST = [
    "José",
    "Jose",
    "Maria",
    "Ana",
    "João",
    "Joao",
    "Paulo",
    "Pedro",
    "Lucas",
    "Mateus",
    "Rafael",
    "Gabriel",
    "Júlia",
    "Julia",
    "Beatriz",
    "Camila",
    "Renato",
    "Sérgio",
    "Sergio",
    "Antônio",
    "Antonio",
    "Luíza",
    "Luiza",
    "Fernanda",
    "Rodrigo",
    "Daniel",
    "Thiago",
    "Bruno",
    "Carla",
    "Débora",
]
MIDDLE = [
    "Carlos",
    "Eduardo",
    "Henrique",
    "Cristina",
    "Aparecida",
    "Luiz",
    "Augusto",
    "Helena",
    "Vitória",
    "Gonçalves",
    "Batista",
    "Rosa",
    "",
]
SURNAME = [
    "Silva",
    "Santos",
    "Oliveira",
    "Souza",
    "Pereira",
    "Lima",
    "Carvalho",
    "Ferreira",
    "Rodrigues",
    "Almeida",
    "Costa",
    "Gomes",
    "Martins",
    "Araújo",
    "Araujo",
    "Barbosa",
    "Ribeiro",
    "Alves",
    "Cardoso",
    "Rocha",
    "Dias",
    "Nascimento",
    "Andrade",
    "Moreira",
    "Nunes",
    "Marques",
    "Machado",
    "Mendes",
    "Freitas",
    "Cavalcanti",
    "Teixeira",
    "Pinto",
    "Monteiro",
    "Vieira",
]
PARTICLE = ["da", "de", "do", "dos", "das", "e", ""]
SUFFIX = ["", "", "", "", "Júnior", "Junior", "Jr.", "Filho", "Neto"]


def _make_name(rnd):
    parts = [rnd.choice(FIRST)]
    middle = rnd.choice(MIDDLE)
    if middle:
        parts.append(middle)
    particle = rnd.choice(PARTICLE)
    if particle:
        parts.append(particle)
    parts.append(rnd.choice(SURNAME))
    if rnd.random() < 0.5:
        parts.append(rnd.choice(SURNAME))
    suffix = rnd.choice(SUFFIX)
    if suffix:
        parts.append(suffix)
    return " ".join(parts)


def _variant(rnd, name):
    """Spellings that collide on one or more keys: case, punctuation, spacing."""
    r = rnd.random()
    if r < 0.3:
        return name.upper()
    if r < 0.5:
        return name.lower()
    if r < 0.7:
        return name.replace(" ", "  ")
    if r < 0.85:
        return name.replace(" ", "-", 1)
    return name + "."


def _perturb(rnd, name):
    tokens = name.split()
    r = rnd.random()
    if r < 0.25 and len(tokens) > 2:
        tokens.pop(rnd.randrange(1, len(tokens)))
    elif r < 0.5:
        i = rnd.randrange(len(tokens))
        word = tokens[i]
        if len(word) > 3:
            j = rnd.randrange(len(word))
            tokens[i] = word[:j] + word[j + 1 :]
    elif r < 0.7:
        rnd.shuffle(tokens)
    elif r < 0.8:
        return "".join(rnd.choice("xyzqwk ") for _ in range(12))
    elif r < 0.85:
        return "!!! ---"
    return " ".join(tokens)


class FakePersonController:
    """Identical controllers for both matchers: same ids, same records."""

    def __init__(self, names):
        self.next_id = 1
        self.persons = [self._person(n, []) for n in names]

    def _person(self, name, emails):
        person = SimpleNamespace(
            id=self.next_id,
            name=name,
            emails=[SimpleNamespace(email=e) for e in emails],
            identification_id=None,
            resume=None,
            citation_names=None,
            cnpq_url=None,
        )
        self.next_id += 1
        return person

    def get_all(self):
        return list(self.persons)

    def create_person(self, name, emails):
        person = self._person(name, emails)
        self.persons.append(person)
        return person


def _cache(rnd, size):
    names = []
    while len(names) < size:
        base = _make_name(rnd)
        names.append(base)
        if rnd.random() < 0.25:
            names.append(_variant(rnd, base))
    return names


def _run_equivalence(cache_size, n_queries, seed):
    """Returns (mismatches, fuzzy_hits). Mismatch = different person id or cache order."""
    rnd = random.Random(seed)
    names = _cache(rnd, cache_size)
    old = OraclePersonMatcher(FakePersonController(names))
    new = PersonMatcher(FakePersonController(names))
    old.preload_cache()
    new.preload_cache()

    known = list(names)
    mismatches = 0
    for _ in range(n_queries):
        r = rnd.random()
        if r < 0.15:
            query = rnd.choice(known)
        elif r < 0.35:
            query = _variant(rnd, rnd.choice(known))
        elif r < 0.75:
            query = _perturb(rnd, rnd.choice(known))
        else:
            query = _make_name(rnd)
        email = f"p{rnd.randrange(400)}@ex.org" if rnd.random() < 0.1 else None
        strict = rnd.random() < 0.3
        a = old.match_or_create(query, email=email, strict_match=strict)
        b = new.match_or_create(query, email=email, strict_match=strict)
        if getattr(a, "id", None) != getattr(b, "id", None):
            mismatches += 1
        known.append(query)
    if list(old._persons_cache) != list(new._persons_cache):
        mismatches += 1
    if {k: v.id for k, v in old._persons_cache.items()} != {
        k: v.id for k, v in new._persons_cache.items()
    }:
        mismatches += 1
    return mismatches, new._stats["fuzzy"]


def _capture_info(fn):
    lines = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        fn()
    finally:
        logger.remove(sink)
    return lines


def test_matches_pre016_matcher_on_mixed_sequence():
    mismatches, fuzzy_hits = _run_equivalence(cache_size=800, n_queries=1000, seed=16)
    assert mismatches == 0
    assert fuzzy_hits > 0  # the fuzzy path was actually exercised


def test_matches_pre016_matcher_with_pure_python_rapidfuzz():
    # RAPIDFUZZ_IMPLEMENTATION is read at import time: run in a fresh process.
    code = (
        "import sys; sys.path.insert(0, 'tests'); "
        "import test_person_matcher_index as t; "
        "print(t._run_equivalence(cache_size=400, n_queries=300, seed=7)[0])"
    )
    env = dict(os.environ, RAPIDFUZZ_IMPLEMENTATION="python")
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert out.stdout.strip().splitlines()[-1] == "0"


def test_normalised_hit_returns_first_raw_name_without_renormalising(monkeypatch):
    names = ["José da Silva", "JOSE DA SILVA", "Maria Souza"] + [
        f"Pessoa Numero {i}" for i in range(500)
    ]
    matcher = PersonMatcher(FakePersonController(names))
    matcher.preload_cache()
    first = matcher._persons_cache["José da Silva"]

    calls = []
    original = PersonMatcher.normalize_name
    monkeypatch.setattr(
        PersonMatcher,
        "normalize_name",
        lambda self, n: calls.append(n) or original(self, n),
    )

    person = matcher.match_or_create("jose  da   silva")

    assert person is first
    assert len(calls) <= 2  # the input (+ the new raw spelling), never the cache


def test_reassigned_raw_name_keeps_order_and_returns_current_person():
    names = ["Ana Lima", "ANA LIMA"]
    old = OraclePersonMatcher(FakePersonController(names))
    new = PersonMatcher(FakePersonController(names))
    old.preload_cache()
    new.preload_cache()
    for m in (old, new):
        replacement = SimpleNamespace(id=99, name="Ana Lima", emails=[])
        m._persons_cache["Ana Lima"] = replacement  # in-place re-assignment
    # new matcher must reach the same answer through its index
    assert new.match_or_create("ana   lima").id == old.match_or_create("ana   lima").id


def test_created_and_registered_names_are_found_later():
    new = PersonMatcher(FakePersonController(["Bruno Alves"]))
    new.preload_cache()

    created = new.match_or_create("Carla Mendes Freitas")
    assert new.match_or_create("CARLA MENDES FREITAS") is created

    registered = new.match_or_create("bruno  alves")  # normalised hit registers it
    assert new.match_or_create("bruno  alves") is registered


def test_fuzzy_view_reproduces_dict_comprehension_order_and_last_mapping():
    names = ["Pedro Rocha", "Lucas Dias", "PEDRO ROCHA", "pedro rocha", "Lucas  Dias"]
    matcher = PersonMatcher(FakePersonController(names))
    matcher.preload_cache()

    expected = {oracle_normalize_name(n): n for n in matcher._persons_cache}
    assert matcher._fuzzy_keys == list(expected)
    assert matcher._last_by_norm == expected


def test_preload_rebuilds_every_index():
    controller = FakePersonController(["Rita Nunes"])
    matcher = PersonMatcher(controller)
    matcher.preload_cache()
    matcher.match_or_create("Outra Pessoa Qualquer")
    controller.persons = controller.persons[:1]

    matcher.preload_cache()

    assert list(matcher._persons_cache) == ["Rita Nunes"]
    assert matcher._fuzzy_keys == [oracle_normalize_name("Rita Nunes")]
    assert set(matcher._first_by_norm.values()) == {"Rita Nunes"}


def test_log_match_summary_reports_counters():
    matcher = PersonMatcher(FakePersonController(["Daniel Costa Pinto"]))
    matcher.preload_cache()
    matcher.match_or_create("Daniel Costa Pinto")  # canonical hit
    matcher.match_or_create("Daniel Costa Pnto")  # fuzzy hit
    matcher.match_or_create("Zuleica Bernardes Quintanilha")  # created

    lines = _capture_info(lambda: matcher.log_match_summary("x"))

    assert lines == [
        "Person matching [x]: email=0 canonical=1 exact=0 normalised=0 "
        "invariant=0 fuzzy=1 strict_rejected=0 created=1 create_failed=0"
    ]
