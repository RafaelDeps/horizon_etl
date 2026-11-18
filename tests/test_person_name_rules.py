"""Contract of the person name rules (spec 041, contracts/dashboard-fixes.md,
sections 1 and 2)."""

import pytest

from src.core.logic.person_name_rules import advisor_name, is_name_fragment

FRAGMENTS = [
    None,
    "",
    "  ",
    "..",
    "Dr",
    "Dr.",
    "Dra",
    "Drª",
    "Prof",
    "PROF",
    "Profa",
    "Profª",
    "Pro",
    "Ph",
    "PhD",
    "MSc",
    "M",
    "D",
    "DSc",
    "Me",
    "Ma",
    "J",
    "H",
    "1",
    "2",
    "-",
    "xxx",
    "Licenciatura",
    "Esp",
    "Eng",
    "Ing",
]

NAMES = [
    "Graciela",
    "Alan",
    "Adélia",
    "Rhian",
    "Elson",
    "José Antônio da Silva",
    "C. Silva",
]


@pytest.mark.parametrize("text", FRAGMENTS)
def test_fragments(text):
    assert is_name_fragment(text) is True


@pytest.mark.parametrize("text", NAMES)
def test_names_are_not_fragments(text):
    assert is_name_fragment(text) is False


ADVISORS = [
    (
        "Orientador: Prof. Dr. José Antônio da Silva. Bolsista do(a): Fundação "
        "de Amparo à Pesquisa do Estado de Minas Gerais.",
        "José Antônio da Silva",
        None,
    ),
    (
        "Orientador: Dr. José Rafael Cápua Proveti. Coorientador: Dr. Wanderley "
        "Cardoso Celeste. Bolsista do(a): Coordenação de Aperfeiçoamento.",
        "José Rafael Cápua Proveti",
        "Wanderley Cardoso Celeste",
    ),
    (
        "Orientador: Ph.D. Alberto Ferreira de Souza, Ph.D. Hansjorg Schneebeli.",
        "Alberto Ferreira de Souza",
        None,
    ),
    (
        "Orientador: M.Sc. Rostan Piccoli, D.Sc. Sergio Antônio Andrade de Freita.",
        "Rostan Piccoli",
        None,
    ),
    (
        "Orientador: Profa. DSc. Luciana Rodrigues Cardoso Trigueiro.",
        "Luciana Rodrigues Cardoso Trigueiro",
        None,
    ),
    (
        "Orientador: Profa. Michèle Schubert Pfeil. Coorientador: Prof. Ronaldo "
        "C. Battista e Prof. Romildo D. Toledo Filho.",
        "Michèle Schubert Pfeil",
        "Ronaldo C. Battista",
    ),
    (
        "Orientador: PROF. DR. CREDINE SILVA DE MENEZES. Grande área: Engenharias",
        "CREDINE SILVA DE MENEZES",
        None,
    ),
    (
        "Orientador: Profª. Drª. Isabel Ferin Cunha). Título: A modalização",
        "Isabel Ferin Cunha",
        None,
    ),
    (
        "Orientador: 1.Zilma Rodrigues da Silva. 2.Margarida M. A. de Vasconcelos.",
        "Zilma Rodrigues da Silva",
        None,
    ),
    (
        "Orientador: Pro. Dr. Jorge Luiz Viesenteiner. Coorientador: Não Definido. "
        "Palavras-chave: Affordances; Emoções.",
        "Jorge Luiz Viesenteiner",
        None,
    ),
    ("Orientador: Edson Terra.", "Edson Terra", None),
    ("Orientador: -.", None, None),
    ("Orientador: ..", None, None),
    ("Orientador: xxx.", None, None),
    ("Orientador: Licenciatura.", None, None),
    ("Orientador: Alan.", "Alan", None),
    ("Coorientador: Maria Souza. Orientador: João Lima.", "João Lima", "Maria Souza"),
    ("Título: Um estudo, Ano de obtenção: 2010.", None, None),
    # Found on the curricula of 2026-11-17 (branch 041, T014).
    (
        "Orientador: Msc: Talita Miranda Teixeira Xavier.",
        "Talita Miranda Teixeira Xavier",
        None,
    ),
    (
        "Orientador: Paulo Faria Santos Amaral http://lattes.cnpq.br/9805377939.",
        "Paulo Faria Santos Amaral",
        None,
    ),
    ("Orientador: Esp. Ana Maria Souza.", "Ana Maria Souza", None),
    ("Orientador: Ing. Fulano de Tal.", "Fulano de Tal", None),
    ("Orientador: . Ano de interrupção: 2005.", None, None),
    ("Orientador: Engracia Souza Lima.", "Engracia Souza Lima", None),
    ("", None, None),
    (None, None, None),
]


@pytest.mark.parametrize("description, advisor, co_advisor", ADVISORS)
def test_advisor_name(description, advisor, co_advisor):
    assert advisor_name(description) == advisor
    assert advisor_name(description, co=True) == co_advisor


@pytest.mark.parametrize("description, advisor, co_advisor", ADVISORS)
def test_an_advisor_is_never_a_fragment(description, advisor, co_advisor):
    for name in (advisor_name(description), advisor_name(description, co=True)):
        assert name is None or not is_name_fragment(name)
