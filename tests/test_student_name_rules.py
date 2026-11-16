"""Contract of the student name rule (spec 036, contracts/small-fixes.md, section 1)."""

import pytest

from src.core.logic.student_name_rules import CleanedName, clean_student_name

UNCUT = 'Andre. "ELABORAÇÃO DE ENSAIOS DIDÁTICOS"'
E_HEAD = "Katianni Garcia Suhett e Monique Vargas de Gouvêa. Resíduos sólidos"
COMMA_HEAD = "Carlos Huhn de Paiva Siqueira, Felipe Kuhn. Comparativo entre"
INITIALS_LIST = "Adriana S.N. Marchezi, Izack de P. vieira, Fernando B. Rocha"
SLASH = "Rafael Scopel Paviotti/Sidarta Barroso Veloso"
SEMICOLON = "Daiane Costa; Elizana Faria; Matheus Schulz;"
CO_ADVISOR = "Nina Waszczynskyj Co-orientador: Peter Gaber Kirschnik"

CASES = [
    ("Maria da Silva", "Maria da Silva", ()),
    ("  Maria   da Silva ", "Maria da Silva", ()),
    (None, None, ("empty",)),
    ("", None, ("empty",)),
    ("   ", None, ("empty",)),
    ("Graciela", "Graciela", ()),
    ("Eduarda Q. O. Senra", "Eduarda Q. O. Senra", ()),
    ("Dr. Hamilton Carvalho Tolosa", "Hamilton Carvalho Tolosa", ("title",)),
    (
        "Profª Drª Teresa Cristina Janes Carneiro",
        "Teresa Cristina Janes Carneiro",
        ("title",),
    ),
    (
        "Professor Doutor Frederico Carlos de Sá Costa",
        "Frederico Carlos de Sá Costa",
        ("title",),
    ),
    (
        "Profª Msc: Talita Miranda Teixeira Xavier",
        "Talita Miranda Teixeira Xavier",
        ("title",),
    ),
    ("Dácio Guimarães de Moura ? Dr", "Dácio Guimarães de Moura", ("title",)),
    ("Drago Pereira Lima", "Drago Pereira Lima", ()),
    ("João Mestre Souza", "João Mestre Souza", ()),
    ("Professora Dra", None, ("title", "not_a_name")),
    ("Prof Dr", None, ("title", "not_a_name")),
    ("Profª Ms", None, ("title", "not_a_name")),
    (
        "Silas Gambarine Soaresjavascript:void(0)",
        "Silas Gambarine Soares",
        ("link",),
    ),
    (
        "Paulo Faria Santos Amaral http://lattes",
        "Paulo Faria Santos Amaral",
        ("link",),
    ),
    (
        "Guilherme Lopes de Oliveira. Uso do método OTA (Over-The-Air) (PT 10550)",
        "Guilherme Lopes de Oliveira",
        ("work_title",),
    ),
    ("ANDRÉ LUIS KEREK. USO DO ANIME DR", "ANDRÉ LUIS KEREK", ("work_title",)),
    (
        "Alcione Maria de Andrade. Palicourea marcgravii St. Hil",
        "Alcione Maria de Andrade",
        ("work_title",),
    ),
    (
        "Lucas Basseti. BIOMASSA E ESTRUTURAÇÃO VEGETATIVA",
        "Lucas Basseti",
        ("work_title",),
    ),
    (UNCUT, UNCUT, ("uncut",)),
    (E_HEAD, E_HEAD, ("several",)),
    (COMMA_HEAD, COMMA_HEAD, ("several",)),
    (INITIALS_LIST, INITIALS_LIST, ("several",)),
    (SLASH, SLASH, ("several",)),
    (SEMICOLON, SEMICOLON, ("several",)),
    (CO_ADVISOR, CO_ADVISOR, ("several",)),
    ("Roseanne Gomes Gonçalves2", "Roseanne Gomes Gonçalves", ("footnote",)),
    ("Acadêmicos do 6 periodo", None, ("not_a_name",)),
    ('Turma "C" do 1º ano EBTT', None, ("not_a_name",)),
    ("1", None, ("not_a_name",)),
    ("-", None, ("not_a_name",)),
    ("D", None, ("not_a_name",)),
    ("Ph", None, ("not_a_name",)),
]


@pytest.mark.parametrize("raw, name, kinds", CASES)
def test_the_contract_table(raw, name, kinds):
    assert clean_student_name(raw) == CleanedName(name, kinds)


@pytest.mark.parametrize("raw, name, kinds", CASES)
def test_the_same_text_always_gives_the_same_result(raw, name, kinds):
    assert clean_student_name(raw) == clean_student_name(raw)


@pytest.mark.parametrize(
    "raw",
    [
        raw
        for raw, name, kinds in CASES
        if name and "several" not in kinds and "uncut" not in kinds
    ],
)
def test_a_clean_name_is_left_alone(raw):
    cleaned = clean_student_name(raw)
    assert clean_student_name(cleaned.name) == CleanedName(cleaned.name, ())


def test_several_people_keep_their_text_apart_from_a_link():
    cleaned = clean_student_name("Ana Costa/Bia Lima http://lattes")
    assert cleaned == CleanedName("Ana Costa/Bia Lima", ("link", "several"))
