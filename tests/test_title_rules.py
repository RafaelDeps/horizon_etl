"""Contract of the title rules (spec 041, contracts/dashboard-fixes.md,
section 4)."""

from datetime import date

import pytest

from src.adapters.sources.lattes_parser import LattesParser
from src.core.logic.initiative_identity import normalize_text
from src.core.logic.title_rules import fix_lost_dash, plausible_year

DASHES = [
    (
        "Implantação de um Laboratório de Análise de Solos no Ifes ? Campus Ibatiba",
        "Implantação de um Laboratório de Análise de Solos no Ifes – Campus Ibatiba",
    ),
    (
        '"Fomento pesqueiro e aquícola do litoral de Piúma ? IFES ? Campus Piúma"',
        '"Fomento pesqueiro e aquícola do litoral de Piúma – IFES – Campus Piúma"',
    ),
    (
        "PRODUTORES ORGÂNICOS DE NOVA VENÉCIA ? ES",
        "PRODUTORES ORGÂNICOS DE NOVA VENÉCIA – ES",
    ),
    ("O que é ? Um estudo", "O que é – Um estudo"),
    ("Edição 2019 ? 2020", "Edição 2019 – 2020"),
]

UNCHANGED = [
    "Ifes Portas Abertas: por qual delas entrar?",
    "ANALISE DA ?FESTA DOS PESCADORES?.",
    "EFEITO DA ADUBAÃ?Ã?O FOLIAR",
    "O ?tempo integral? na educação infantil",
    "Por que? Uma análise",
    "Termina com espaço ?",
    "? começa com interrogação",
    "",
    None,
]

REAL_QUESTIONS = [
    "Ifes Portas Abertas: Por qual delas entrar?",
    "Quem são os egressos do Ifes?",
    "Educação ambiental: para quê?",
    "O que os alunos pensam?",
    "Existe vida após o TCC?",
    "Por que ensinar ciências?",
    "Como avaliar? Um estudo de caso",
    "Qual o papel da escola?",
    "Robôs na sala de aula?",
    "Matemática é difícil?",
    "Onde estão as mulheres na ciência?",
    "É possível ensinar física sem laboratório?",
    "Quanto custa um aluno?",
    "A pesquisa vale a pena?",
    "O que é inovação?",
    "Para onde vai o lixo?",
    "Quem cuida do rio?",
    "Por que reprovar?",
    "O ensino remoto funcionou?",
    "Há espaço para a arte?",
]


@pytest.mark.parametrize("raw, fixed", DASHES)
def test_a_lost_dash_becomes_an_en_dash(raw, fixed):
    assert fix_lost_dash(raw) == fixed


@pytest.mark.parametrize("raw", UNCHANGED + REAL_QUESTIONS)
def test_every_other_question_mark_is_kept(raw):
    assert fix_lost_dash(raw) == raw


@pytest.mark.parametrize(
    "raw", [r for r, _ in DASHES] + [u for u in UNCHANGED if u] + REAL_QUESTIONS
)
def test_keys_do_not_change(raw):
    parser = LattesParser()
    assert normalize_text(fix_lost_dash(raw)) == normalize_text(raw)
    assert parser.normalize_title(fix_lost_dash(raw)) == parser.normalize_title(raw)


THIS_YEAR = date.today().year


@pytest.mark.parametrize(
    "value, year",
    [
        (2015, 2015),
        ("2015", 2015),
        (1950, 1950),
        (THIS_YEAR + 1, THIS_YEAR + 1),
        (0, None),
        ("0", None),
        (1949, None),
        (THIS_YEAR + 2, None),
        ("abc", None),
        (None, None),
        ("", None),
    ],
)
def test_plausible_year(value, year):
    assert plausible_year(value) == year
