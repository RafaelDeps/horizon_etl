"""Testes do gerador da planilha PNP (src/scripts/export_pnp_xlsx.py).

Cobre só a lógica pura (normalização de texto, datas, situação e escrita da
aba). Não toca em banco, Prefect nem nos JSON de data/exports: o volume real
das 9 abas é conferido na geração (`make pnp-xlsx`).
"""

from __future__ import annotations

import openpyxl
import pytest

from src.scripts import export_pnp_xlsx as pnp


class TestNormKey:
    @pytest.mark.parametrize(
        "left,right",
        [
            ("Classificador de Briquetes.", "classificador de briquetes"),
            ("Robótica – Robotech 4.0", "robotica robotech 4 0"),
            ("Ação  Ação", "Ação Ação"),
        ],
    )
    def test_variacoes_de_grafia_casam(self, left: str, right: str) -> None:
        assert pnp._norm_key(left) == pnp._norm_key(right)

    def test_none_e_vazio(self) -> None:
        assert pnp._norm_key(None) == ""
        assert pnp._norm_key("   ") == ""


class TestDate:
    def test_sigpesq_dd_mm_aa(self) -> None:
        assert pnp._date("01-08-22") == "2022-08-01"
        assert pnp._date("31-12-26") == "2026-12-31"

    def test_iso_datetime(self) -> None:
        assert pnp._date("2022-08-01T00:00:00") == "2022-08-01"
        assert pnp._date("2015-01-01 00:00:00.000000") == "2015-01-01"

    @pytest.mark.parametrize("value", [None, "", "   ", "31/12/2026"])
    def test_valores_sem_data_ficam_nulos(self, value: object) -> None:
        assert pnp._date(value) is None


class TestYearDerived:
    def test_reconhece_aaaa_01_01_do_lattes(self) -> None:
        assert pnp._is_year_derived("2024-01-01")
        assert not pnp._is_year_derived("2024-08-01")
        assert not pnp._is_year_derived(None)


class TestSituacaoPnp:
    initiative = {"start_date": "2020-01-01T00:00:00", "end_date": None}

    def test_encerra_quando_o_fim_ja_passou(self) -> None:
        record = {
            "start_date": "2020-01-01T00:00:00",
            "end_date": "2021-12-31T00:00:00",
        }
        assert pnp._situacao_pnp(record, None) == "Encerrado"

    def test_em_andamento_quando_a_fim_esta_no_futuro(self) -> None:
        record = {
            "start_date": "2020-01-01T00:00:00",
            "end_date": "2099-12-31T00:00:00",
        }
        assert pnp._situacao_pnp(record, None) == "Em andamento"

    def test_planejado_quando_ainda_nao_comecou(self) -> None:
        record = {"start_date": "2099-01-01T00:00:00", "end_date": None}
        assert pnp._situacao_pnp(record, None) == "Planejado"

    def test_sem_iniciativa_fica_nulo(self) -> None:
        assert pnp._situacao_pnp(None, "Aprovado") is None

    def test_sem_datas_usa_o_parecer(self) -> None:
        record = {"start_date": None, "end_date": None}
        assert pnp._situacao_pnp(record, "Aprovado") == "Em andamento"
        assert pnp._situacao_pnp(record, "Recusado") is None


class TestCelulaNula:
    def test_vazios_viram_nulo(self) -> None:
        assert pnp._cell(None, None) is None
        assert pnp._cell("   ", None) is None
        assert pnp._cell([], None) is None

    def test_null_text_substitui_o_nulo(self) -> None:
        assert pnp._cell(None, "null") == "null"
        assert pnp._cell("  ", "null") == "null"

    def test_valor_preenchido_e_preservado(self) -> None:
        assert pnp._cell(" Serra ", None) == "Serra"
        assert pnp._cell(0, None) == 0
        assert pnp._cell(["a", "b"], None) == "a; b"


class TestWriteSheet:
    def test_grava_cabecalho_e_linhas_com_filtro(self) -> None:
        workbook = openpyxl.Workbook()
        columns = ("estrutura", "titulo", "campus_nome")
        rows = [[None, "Projeto A", "Serra"], [None, "Projeto B", None]]

        written = pnp.write_sheet(workbook, "teste", columns, rows, None)

        assert written == 2
        sheet = workbook["teste"]
        assert [cell.value for cell in sheet[1]] == list(columns)
        assert sheet.cell(2, 1).value is None  # estrutura = nulo de verdade
        assert sheet.cell(2, 2).value == "Projeto A"
        assert sheet.cell(3, 3).value is None
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == "A1:C3"

    def test_aba_vazia_mantem_cabecalho(self) -> None:
        workbook = openpyxl.Workbook()
        assert pnp.write_sheet(workbook, "vazia", ("a", "b"), [], None) == 0
        assert workbook["vazia"].max_row == 1


class TestColunasPorAba:
    def test_uma_coluna_por_nome_e_sem_repeticao(self) -> None:
        tabelas = [
            pnp.COLS_PROJETOS_PESQUISA,
            pnp.COLS_PROJETOS_ACAO,
            pnp.COLS_PESSOAS_PROJETO,
            pnp.COLS_PROJETOS_ENSINO,
            pnp.COLS_PRODUCAO,
            pnp.COLS_PESSOAS_ACAO,
            pnp.COLS_PESSOAS_ATENDIDAS,
            pnp.COLS_PROGRAMA,
        ]
        for colunas in tabelas:
            assert len(colunas) == len(set(colunas)), colunas
            assert all(nome == nome.strip() for nome in colunas)

    def test_campos_pnp_sem_fonte_sao_nulos_em_todas_as_abas_de_projeto(self) -> None:
        """Coluna de estrutura existe e é sempre gravada como nulo."""
        for colunas in (pnp.COLS_PROJETOS_PESQUISA, pnp.COLS_PROJETOS_ACAO):
            assert "estrutura" in colunas
            assert "valor_investimento" in colunas


class TestBuildWorkbook:
    def test_abas_nas_ordem_do_relatorio(self, tmp_path, monkeypatch) -> None:
        """Com fontes vazias, o workbook sai com as 9 abas, na ordem do PNP."""
        nome_arquivo = tmp_path / "x.json"
        nome_arquivo.write_text("[]", encoding="utf-8")
        exports = tmp_path / "exports"
        exports.mkdir()
        for nome in (
            "initiatives_canonical",
            "source_records_canonical",
            "researchers_canonical",
            "advisorships_canonical",
            "production_authors_canonical",
            "articles_canonical",
            "research_productions_canonical",
            "production_types_canonical",
            "initiative_types_canonical",
        ):
            (exports / f"{nome}.json").write_text("[]", encoding="utf-8")

        workbook, counts = pnp.build_workbook(
            pnp.Sources(exports), null_text=None, empty_template_row=False
        )

        assert workbook.sheetnames == list(pnp.SHEET_TITLES)
        assert counts == {titulo: 0 for titulo in pnp.SHEET_TITLES}

    def test_main_recusa_exports_incompletos(self, tmp_path) -> None:
        exports = tmp_path / "exports"
        exports.mkdir()
        with pytest.raises(SystemExit):
            pnp.main(
                [
                    "--exports-dir",
                    str(exports),
                    "--out",
                    str(tmp_path / "saida.xlsx"),
                ]
            )
