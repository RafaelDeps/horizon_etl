import pytest

from src.adapters.sources.lattes_parser import LattesParser


@pytest.fixture
def parser():
    return LattesParser()


@pytest.fixture
def sample_data():
    return {
        "projetos_pesquisa": [
            {
                "nome": "Projeto Pesquisa 1",
                "ano_inicio": "2020",
                "ano_conclusao": "Atual",
                "descricao": [
                    "Descrição: Descricao do projeto. Situação: Em andamento; Natureza: Pesquisa."
                ],
                "integrantes": [{"nome": "Pesquisador A", "papel": "Coordenador"}],
            }
        ],
        "projetos_extensao": [
            {
                "nome": "Projeto Extensao 1",
                "ano_inicio": "2021",
                "ano_conclusao": "2022",
                "descricao": [
                    "Descrição: Descricao extensao. Situação: Concluído; Natureza: Extensão."
                ],
                "integrantes": [],
            }
        ],
        "projetos_desenvolvimento": [
            {
                "nome": "Projeto Dev 1",
                "ano_inicio": "2019",
                "ano_conclusao": "2019",
                "descricao": [
                    "Descrição: Descricao dev. Situação: Concluído; Natureza: Desenvolvimento."
                ],
                "integrantes": [],
            }
        ],
        "producao_bibliografica": {
            "artigos_periodicos": [
                {
                    "titulo": "Artigo Periodico 1",
                    "ano": 2022,
                    "autores": "Autor A; Autor B",
                    "revista": "Revista Cientifica",
                    "volume": "10",
                    "paginas": "1-10",
                    "doi": "10.1234/artigo1",
                }
            ],
            "trabalhos_completos_congressos": [
                {
                    "titulo": "Trabalho Congresso 1",
                    "ano": 2023,
                    "autores": "Autor C; Autor D",
                    "evento": "Congresso Internacional",
                    "paginas": "100-110",
                }
            ],
        },
    }


def test_parse_research_projects(parser, sample_data):
    projects = parser.parse_research_projects(sample_data)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == "Projeto Pesquisa 1"
    assert p["start_year"] == 2020
    assert p["end_year"] is None
    assert p["status"] == "Active"
    assert p["initiative_type_name"] == "Research Project"
    assert "Descricao do projeto" in p["description"]


def test_parse_extension_projects(parser, sample_data):
    projects = parser.parse_extension_projects(sample_data)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == "Projeto Extensao 1"
    assert p["start_year"] == 2021
    assert p["end_year"] == 2022
    assert p["status"] == "Concluded"
    assert p["initiative_type_name"] == "Extension Project"


def test_parse_development_projects(parser, sample_data):
    projects = parser.parse_development_projects(sample_data)
    assert len(projects) == 1
    p = projects[0]
    assert p["name"] == "Projeto Dev 1"
    assert p["initiative_type_name"] == "Development Project"


def test_parse_articles(parser, sample_data):
    articles = parser.parse_articles(sample_data)
    assert len(articles) == 1
    a = articles[0]
    assert a["title"] == "Artigo Periodico 1"
    assert a["year"] == 2022
    assert a["journal_conference"] == "Revista Cientifica"
    assert a["doi"] == "10.1234/artigo1"
    assert a["type"] == "Journal"


def test_parse_conference_papers(parser, sample_data):
    papers = parser.parse_conference_papers(sample_data)
    assert len(papers) == 1
    p = papers[0]
    assert p["title"] == "Trabalho Congresso 1"
    assert p["year"] == 2023
    assert p["journal_conference"] == "Congresso Internacional"
    assert p["type"] == "Conference Event"


def test_clean_description(parser):
    raw = "Descrição: Minha descrição aqui. Situação: Em andamento; Natureza: Pesquisa."
    clean = parser._clean_description(raw)
    assert clean == "Minha descrição aqui"

    raw2 = "Descrição: Apenas descrição."
    clean2 = parser._clean_description(raw2)
    assert clean2 == "Apenas descrição"


# --- awards / languages / professional activities / technical productions ---


@pytest.fixture
def extras_data():
    return {
        "premios_titulos": [
            {"descricao": "1o Lugar Innova 2014", "ano": 2014},
            {"descricao": "", "ano": 2020},  # sem titulo -> ignorado
            "nao-dict",  # ignorado
        ],
        "idiomas": [
            {
                "nome": "Inglês",
                "compreende": "Bem",
                "fala": "Bem",
                "le": "Bem",
                "escreve": "Bem",
            },
            {"nome": "", "compreende": "Pouco"},  # sem nome -> ignorado
        ],
        "atuacao_profissional": [
            {
                "instituicao": "IFES, Brasil.",
                "instituicao_sigla": "IFES",
                "periodo": "2014 - Atual",
                "ano_inicio": "2014",
                "ano_fim": "Atual",
                "vinculo": "Servidor",
                "tipo": "Atuação profissional",
            },
            {"instituicao": "UFES", "ano_inicio": "2010", "ano_fim": "2013"},
            {"instituicao": ""},  # sem instituicao -> ignorado
        ],
        "producao_tecnica": {
            "softwares_sem_patente": [
                {"titulo": "Sincap", "ano": 2015, "autores": "FULANO, F."},
                {"titulo": ""},  # ignorado
            ],
            "entrevistas": "nao-lista",  # ignorado
        },
        "patentes_registros": {
            "patentes": [{"titulo": "Patente X", "ano": 2018}],
        },
    }


def test_parse_awards(parser, extras_data):
    r = parser.parse_awards(extras_data)
    assert len(r) == 1
    assert r[0] == {"title": "1o Lugar Innova 2014", "year": 2014}


def test_parse_languages(parser, extras_data):
    r = parser.parse_languages(extras_data)
    assert len(r) == 1
    assert r[0]["language"] == "Inglês"
    assert r[0]["comprehension"] == "Bem" and r[0]["writing"] == "Bem"


def test_parse_professional_activities_current_and_closed(parser, extras_data):
    r = parser.parse_professional_activities(extras_data)
    assert len(r) == 2
    current, closed = r[0], r[1]
    assert current["current"] is True and current["end_year"] is None
    assert current["start_year"] == 2014
    assert closed["current"] is False and closed["end_year"] == 2013


def test_parse_technical_productions_includes_patents(parser, extras_data):
    r = parser.parse_technical_productions(extras_data)
    titles = {x["title"] for x in r}
    assert titles == {"Sincap", "Patente X"}
    by_title = {x["title"]: x for x in r}
    assert by_title["Sincap"]["production_type"] == "softwares_sem_patente"
    assert by_title["Patente X"]["production_type"] == "patentes"


def test_parse_extras_empty_when_sections_absent(parser):
    assert parser.parse_awards({}) == []
    assert parser.parse_languages({}) == []
    assert parser.parse_professional_activities({}) == []
    assert parser.parse_technical_productions({}) == []


def test_project_status_inference(parser):
    from datetime import date

    current_year = date.today().year
    data = {
        "projetos_pesquisa": [
            {
                "nome": "Projeto Ano Corrente",
                "ano_inicio": str(current_year - 1),
                "ano_conclusao": str(current_year),
            },
            {
                "nome": "Projeto Futuro",
                "ano_inicio": str(current_year),
                "ano_conclusao": str(current_year + 1),
            },
            {
                "nome": "Projeto Passado",
                "ano_inicio": str(current_year - 3),
                "ano_conclusao": str(current_year - 1),
            },
        ]
    }
    projects = parser.parse_research_projects(data)
    by_name = {p["name"]: p for p in projects}

    assert by_name["Projeto Ano Corrente"]["status"] == "Active"
    assert by_name["Projeto Futuro"]["status"] == "Active"
    assert by_name["Projeto Passado"]["status"] == "Concluded"

