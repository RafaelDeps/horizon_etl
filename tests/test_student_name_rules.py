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
    (SLASH, "Rafael Scopel Paviotti", ("split",)),
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
    assert cleaned == CleanedName("Ana Costa", ("link", "split"))
    assert cleaned.names == ("Ana Costa", "Bia Lima")


# --- Spec 041: several students split on "/", citations cut ------------------
# contracts/dashboard-fixes.md, section 3.

SPLITS = [
    (
        "Gladston Campos/Niase Borjaille",
        ("Gladston Campos", "Niase Borjaille"),
        ("split",),
    ),
    (
        "Carlos José Rocha Silva / Renato Barros Vasconcelos",
        ("Carlos José Rocha Silva", "Renato Barros Vasconcelos"),
        ("split",),
    ),
    (
        "Eliane N. Oliveira / Laiane C. Vettorazzi / Lidyan Procópio",
        ("Eliane N. Oliveira", "Laiane C. Vettorazzi", "Lidyan Procópio"),
        ("split",),
    ),
    (
        "Ederson de Souza. Nitretação a plasma em ferro fundido branco classe III "
        "A ASTM A 532 (orientador: Prof. MSc. Orlando Preti; coorientador: Prof. Dr",
        ("Ederson de Souza",),
        ("citation", "work_title"),
    ),
    (
        "Vitor de Sá Nunes. Desenvolvimento de um sistema de monitoramento remoto "
        "- Um sistema hardware/software de alerta para transbordamentos (PT00005990)",
        ("Vitor de Sá Nunes",),
        ("work_title",),
    ),
    (
        "Juliana Guzzo Pignaton Schneider / Rafael Cardinot Araújo. Fatores "
        "Influenciadores Da Evasão No Ensino Superior",
        ("Juliana Guzzo Pignaton Schneider", "Rafael Cardinot Araújo"),
        ("work_title", "split"),
    ),
    (
        "Bruno Giacomin/Glício Baptista/Ilvécio Luis Rosi/Rodrigo Mai. Vantagens "
        "da Implantação do Processo de R&S na Empresa",
        ("Bruno Giacomin", "Glício Baptista", "Ilvécio Luis Rosi", "Rodrigo Mai"),
        ("work_title", "split"),
    ),
    (
        "Emanuela V. Souza / Rhamila O. Dassié / Edivaldo Antonio",
        ("Emanuela V. Souza", "Rhamila O. Dassié", "Edivaldo Antonio"),
        ("split",),
    ),
    ("Maria Silva / Xavier", ("Maria Silva / Xavier",), ("several",)),
    ("Ana Lima", ("Ana Lima",), ()),
    ("Acadêmicos do 6 periodo", (), ("not_a_name",)),
]


@pytest.mark.parametrize("raw, names, kinds", SPLITS)
def test_split_and_citation_table(raw, names, kinds):
    cleaned = clean_student_name(raw)
    assert cleaned.names == names
    assert cleaned.kinds == kinds
    assert cleaned.name == (names[0] if names else None)


@pytest.mark.parametrize(
    "raw", [raw for raw, _, _ in CASES] + [raw for raw, _, _ in SPLITS]
)
def test_names_follow_name(raw):
    cleaned = clean_student_name(raw)
    if cleaned.name is None:
        assert cleaned.names == ()
    else:
        assert cleaned.names[0] == cleaned.name


@pytest.mark.parametrize("raw, names, kinds", SPLITS)
def test_a_split_name_is_left_alone(raw, names, kinds):
    if "split" in kinds:
        for name in names:
            assert clean_student_name(name).names == (name,)
