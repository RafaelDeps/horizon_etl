"""
Análise de veículos de publicação dos docentes do IFES Campus Serra.

A partir dos currículos Lattes (data/lattes_json), inventaria as REVISTAS
(artigos em periódicos) e os CONGRESSOS onde os docentes publicaram e cruza
cada revista com duas métricas de impacto:

  * SJR — SCImago Journal Rank (métrica internacional): quartil Q1–Q4,
    índice SJR e H-index do periódico. Casado por ISSN.
  * Qualis CAPES/CNPq: estrato (A1–A4, B1–B4, C). Casado por ISSN, a partir
    de uma tabela de referência local (CAPES não tem API pública estável).

Fontes de referência (opcionais, casadas por ISSN):
  - SCImago: baixa de https://www.scimagojr.com/journalrank.php?out=xls
    (cacheado em data/reference/scimago.csv). Use --download-scimago.
  - Qualis: forneça um CSV em data/reference/qualis.csv com colunas
    contendo ISSN e o estrato (ex.: "ISSN","Estrato"). Use --qualis <arquivo>.

Sem as referências, o script ainda entrega o inventário de veículos (contagens,
ISSN, anos, autores) — só não classifica impacto.

Uso:
  python -m src.scripts.analyze_venues --download-scimago
  python -m src.scripts.analyze_venues --qualis data/reference/qualis.csv
  python -m src.scripts.analyze_venues --top 30
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
from src.scripts.didatica import MOBILE_CSS, bloco_metrica  # noqa: E402

LATTES_DIR = BASE / "data" / "lattes_json"
REF_DIR = BASE / "data" / "reference"
OUT_DIR = BASE / "data" / "exports" / "docentes"
DEFAULT_OUT = OUT_DIR / "venues_analysis.json"
SCIMAGO_CSV = REF_DIR / "scimago.csv"
SCIMAGO_URL = "https://www.scimagojr.com/journalrank.php?out=xls"
QUALIS_CONF_FILE = (
    REF_DIR / "qualis_conferencias.json"
)  # Qualis Eventos CC (UFMT, 2016)
OPENALEX_FILE = OUT_DIR / "openalex_citacoes.json"  # citações por DOI (OpenAlex)


def load_openalex(path: Path = OPENALEX_FILE) -> list[dict]:
    """Lista de docentes com citações/h-index do OpenAlex (casado por DOI). [] se ausente."""
    if not Path(path).exists():
        return []
    return json.loads(Path(path).read_text()).get("docentes", [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def norm_issn(s: str) -> str:
    """Normaliza ISSN para 8 caracteres alfanuméricos (sem hífen, maiúsculo)."""
    if not s:
        return ""
    s = re.sub(r"[^0-9xX]", "", s).upper()
    return s if len(s) == 8 else ""


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def normalize_conf(name: str) -> str:
    """Normaliza nome de congresso removendo ano e número de edição.

    Funde edições do mesmo evento. Ex.:
      '2023 15th IEEE International Conference on Industry Applications' e
      '2025 16th IEEE ... Industry Applications'  ->  'IEEE ... Industry Applications'
      'XLIV Congresso Brasileiro de Educação em Engenharia' -> 'Congresso ...'
      'II Seminário de Pesquisa em Administração'           -> 'Seminário ...'
    """
    s = (name or "").strip()
    # ordinais em inglês: 15th, 1st, 2nd, 3rd (com possível ano antes)
    s = re.sub(r"\b\d{1,3}(st|nd|rd|th)\b", " ", s, flags=re.I)
    # ordinais em português: 15ª, 44º, 1o, 2a
    s = re.sub(r"\b\d{1,3}\s*[ºªoa°]\b", " ", s)
    # anos isolados (19xx/20xx) em qualquer posição
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    # numeral romano de edição no INÍCIO (ex.: 'XLIV ', 'VI ') seguido de palavra
    s = re.sub(r"^\s*[IVXLCDM]{1,7}\b\.?\s+(?=[A-Za-zÀ-ÿ])", " ", s)
    # 'ed.'/'edição' residual
    s = re.sub(r"\b(edi[çc][aã]o|ed\.)\b", " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,.;:-–—()")
    return s


def conf_key(clean: str) -> str:
    """Chave de agrupamento de congressos: ascii minúsculo, só alfanumérico.

    Ignora o conteúdo entre parênteses (acrônimo) p/ não fragmentar o mesmo
    evento — ex.: "Congresso Brasileiro de Automática" e "… (CBA)" agrupam juntos.
    """
    s = re.sub(r"\([^)]*\)?", " ", clean or "")  # parêntese pode estar sem fechar
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


# Peso por estrato Qualis (A1 = topo) — usado no ranking de docentes por impacto.
QUALIS_WEIGHT = {
    "A1": 100,
    "A2": 85,
    "A3": 70,
    "A4": 55,
    "B1": 40,
    "B2": 30,
    "B3": 20,
    "B4": 10,
    "B5": 5,
    "C": 3,
}
_A_STRATA = ("A1", "A2", "A3", "A4")
# Thresholds padronizados (D): nº mínimo de artigos no OpenAlex p/ usar FWCI.
FWCI_MIN = 5  # destaque de docente individual (rankings, líderes por área)
FWCI_MIN_SUB = 3  # granularidade de sub-área (menos docentes por grupo)

# Mapeia áreas do SCImago (Scopus) -> grande área CNPq, p/ inferir a grande área
# de docentes que não a declararam no Lattes (substring, minúsculo).
_SCIMAGO_TO_GRANDE = [
    ("engineering", "Engenharias"),
    ("energy", "Engenharias"),
    ("materials", "Engenharias"),
    ("aerospace", "Engenharias"),
    ("computer", "Ciências Exatas e da Terra"),
    ("mathemat", "Ciências Exatas e da Terra"),
    ("physic", "Ciências Exatas e da Terra"),
    ("chemistr", "Ciências Exatas e da Terra"),
    ("statist", "Ciências Exatas e da Terra"),
    ("medicine", "Ciências da Saúde"),
    ("health", "Ciências da Saúde"),
    ("nursing", "Ciências da Saúde"),
    ("pharma", "Ciências da Saúde"),
    ("biochem", "Ciências Biológicas"),
    ("immunolog", "Ciências Biológicas"),
    ("neuroscience", "Ciências Biológicas"),
    ("agar", "Ciências Agrárias"),
    ("agricultur", "Ciências Agrárias"),
    ("veterinar", "Ciências Agrárias"),
    ("business", "Ciências Sociais Aplicadas"),
    ("management", "Ciências Sociais Aplicadas"),
    ("econom", "Ciências Sociais Aplicadas"),
    ("account", "Ciências Sociais Aplicadas"),
    ("decision", "Ciências Sociais Aplicadas"),
    ("social", "Ciências Sociais Aplicadas"),
    ("arts", "Ciências Humanas"),
    ("humanities", "Ciências Humanas"),
    ("psycholog", "Ciências Humanas"),
]


def _grande_from_scimago_area(area_text: str) -> str | None:
    a = (area_text or "").lower()
    for kw, grande in _SCIMAGO_TO_GRANDE:
        if kw in a:
            return grande
    return None


def _docente_area(cv: dict, field: str = "grande_area") -> str:
    """Área predominante do docente. field: 'grande_area' ou 'area' (sub-área)."""
    c = Counter()
    for a in cv.get("areas_de_atuacao") or []:
        v = (a.get(field) or "").strip()
        if v:
            c[v] += 1
    return c.most_common(1)[0][0] if c else "—"


def rank_docentes(
    roster: dict[str, str],
    qualis: dict,
    scimago: dict,
    conf_acro: dict | None = None,
    conf_name: dict | None = None,
) -> list[dict]:
    """Pontua cada docente pelo Qualis dos periódicos (e, se houver, congressos CC)."""
    conf_acro = conf_acro or {}
    conf_name = conf_name or {}
    by_id = {}
    for f in glob.glob(str(LATTES_DIR / "*.json")):
        m = re.search(r"_(\d{16})\.json$", f)
        if m:
            by_id[m.group(1)] = f

    # mapa sub-área (campo 'area') -> grande área, a partir de quem declara ambos.
    # Usado p/ inferir a grande área de docentes que não a declararam no Lattes.
    sub2grande: dict[str, Counter] = defaultdict(Counter)
    for lid in roster.values():
        f = by_id.get(lid)
        if not f:
            continue
        for a in json.loads(Path(f).read_text()).get("areas_de_atuacao") or []:
            ga = (a.get("grande_area") or "").strip()
            ar = (a.get("area") or "").strip()
            if ga and ar:
                sub2grande[ar][ga] += 1

    rows = []
    for nome, lid in roster.items():
        f = by_id.get(lid)
        if not f:
            continue
        cv = json.loads(Path(f).read_text())
        pb = cv.get("producao_bibliografica", {}) or {}
        arts = pb.get("artigos_periodicos", []) or []
        strata = Counter()
        score = q1q2 = 0
        sci_grande = Counter()  # grande área inferida dos periódicos (Scimago)
        for a in arts:
            issn = norm_issn(a.get("issn", ""))
            est = qualis.get(issn)
            if est:
                strata[est] += 1
                score += QUALIS_WEIGHT.get(est, 0)
            sm = scimago.get(issn, {})
            if sm.get("quartil", "") in ("Q1", "Q2"):
                q1q2 += 1
            g = _grande_from_scimago_area(sm.get("area", ""))
            if g:
                sci_grande[g] += 1
        # congressos: Qualis CC
        congs = pb.get("trabalhos_completos_congressos", []) or []
        conf_strata = Counter()
        score_conf = 0
        for c in congs:
            cl = normalize_conf(c.get("evento") or "")
            est = match_conf_qualis(cl, conf_acro, conf_name) if cl else None
            if est:
                conf_strata[est] += 1
                score_conf += QUALIS_WEIGHT.get(est, 0)
        conf_a = sum(conf_strata[s] for s in _A_STRATA)
        conf_q = sum(conf_strata.values())

        n_a = sum(strata[s] for s in _A_STRATA)
        n_q = sum(strata.values())  # artigos com Qualis
        subarea = _docente_area(cv, "area")
        grande = _docente_area(cv)
        if grande == "—" and subarea != "—" and sub2grande.get(subarea):
            grande = sub2grande[subarea].most_common(1)[0][0]  # inferida da sub-área
        if grande == "—" and sci_grande:
            grande = sci_grande.most_common(1)[0][
                0
            ]  # inferida dos periódicos (Scimago)
        rows.append(
            {
                "nome": nome,
                "area": grande,
                "subarea": subarea,
                "score": score,
                "estrato_A": n_a,
                "artigos": len(arts),
                "artigos_qualis": n_q,
                "qualidade": round(score / n_q, 1) if n_q else 0.0,
                "pct_A": round(n_a / n_q * 100) if n_q else 0,
                "A1": strata["A1"],
                "A2": strata["A2"],
                "A3": strata["A3"],
                "A4": strata["A4"],
                "sjr_q1q2": q1q2,
                "congressos": len(congs),
                "score_conf": score_conf,
                "conf_qualis": conf_q,
                "conf_A": conf_a,
                "score_total": score + score_conf,
            }
        )
    rows.sort(key=lambda r: (-r["score"], -r["estrato_A"], -r["artigos"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def ascension(
    roster: dict[str, str],
    qualis: dict,
    early=(2016, 2020),
    recent=(2021, 2025),
    min_each=2,
) -> list[dict]:
    """Heurística de ascensão: variação da qualidade média (peso Qualis) dos
    artigos entre a janela antiga e a recente do último decênio.

    delta > 0 = pesquisador publicando em estratos mais altos com o tempo.
    Considera só quem tem >= min_each artigos com Qualis em CADA janela.
    """
    by_id = {}
    for f in glob.glob(str(LATTES_DIR / "*.json")):
        m = re.search(r"_(\d{16})\.json$", f)
        if m:
            by_id[m.group(1)] = f

    out = []
    for nome, lid in roster.items():
        f = by_id.get(lid)
        if not f:
            continue
        cv = json.loads(Path(f).read_text())
        old_w, new_w = [], []
        for a in (cv.get("producao_bibliografica", {}) or {}).get(
            "artigos_periodicos", []
        ) or []:
            est = qualis.get(norm_issn(a.get("issn", "")))
            if not est:
                continue
            try:
                ano = int(a.get("ano") or 0)
            except (ValueError, TypeError):
                continue
            w = QUALIS_WEIGHT.get(est, 0)
            if early[0] <= ano <= early[1]:
                old_w.append(w)
            elif recent[0] <= ano <= recent[1]:
                new_w.append(w)
        if len(old_w) < min_each or len(new_w) < min_each:
            continue
        ma = sum(old_w) / len(old_w)
        mr = sum(new_w) / len(new_w)
        out.append(
            {
                "nome": nome,
                "media_antiga": round(ma, 1),
                "media_recente": round(mr, 1),
                "delta": round(mr - ma, 1),
                "n_antigo": len(old_w),
                "n_recente": len(new_w),
                "subarea": _docente_area(cv, "area"),
            }
        )
    out.sort(key=lambda x: -x["delta"])
    return out


def _roster() -> dict[str, str]:
    from src.scripts.generate_docentes_executive import ROSTER_IDS

    return ROSTER_IDS


# ---------------------------------------------------------------------------
# Referências de impacto
# ---------------------------------------------------------------------------


def download_scimago() -> bool:
    REF_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Baixando SCImago de {SCIMAGO_URL} ...")
    try:
        req = Request(SCIMAGO_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=120) as r:
            data = r.read()
        SCIMAGO_CSV.write_bytes(data)
        print(f"  salvo em {SCIMAGO_CSV} ({len(data)//1024} KB)")
        return True
    except Exception as exc:
        print(f"  FALHOU: {exc}", file=sys.stderr)
        return False


def load_scimago() -> dict[str, dict]:
    """ISSN -> {sjr, quartil, h_index, titulo, area}. Vazio se ausente."""
    if not SCIMAGO_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    raw = SCIMAGO_CSV.read_text(encoding="utf-8", errors="ignore")
    reader = csv.DictReader(raw.splitlines(), delimiter=";")
    for row in reader:
        rec = {
            "titulo": (row.get("Title") or "").strip(),
            "sjr": (row.get("SJR") or "").replace(",", ".").strip(),
            "quartil": (row.get("SJR Best Quartile") or "").strip(),
            "h_index": (row.get("H index") or "").strip(),
            "area": (row.get("Categories") or row.get("Areas") or "").strip(),
        }
        for issn in re.split(r"[,\s]+", row.get("Issn", "") or ""):
            k = norm_issn(issn)
            if k:
                out[k] = rec
    return out


def load_qualis(path: Path | None, area: str | None = None) -> dict[str, str]:
    """ISSN -> estrato Qualis. CSV com colunas contendo ISSN e estrato.

    Se `area` for fornecida (ex.: 'Engenharias IV'), classifica SÓ pelo estrato
    daquela área de avaliação CAPES. Sem `area`, usa o melhor estrato entre todas
    as áreas (A1 é o topo).
    """
    if not path or not Path(path).exists():
        return {}
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    delim = ";" if raw.count(";") > raw.count(",") else ","
    reader = csv.DictReader(raw.splitlines(), delimiter=delim)
    issn_col = estr_col = area_col = None
    for c in reader.fieldnames or []:
        cl = norm_name(c)
        if issn_col is None and "issn" in cl:
            issn_col = c
        if estr_col is None and (
            "estrato" in cl or "qualis" in cl or "classific" in cl
        ):
            estr_col = c
        if area_col is None and "area" in cl:
            area_col = c
    if not issn_col or not estr_col:
        print(
            f"  AVISO: não achei colunas ISSN/estrato no Qualis ({reader.fieldnames})",
            file=sys.stderr,
        )
        return {}
    area_norm = norm_name(area) if area else None
    if area_norm and not area_col:
        print(
            f"  AVISO: --qualis-area '{area}' pedida mas não achei coluna de área "
            f"({reader.fieldnames}); usando melhor estrato entre áreas",
            file=sys.stderr,
        )
        area_norm = None
    # Melhor estrato entre áreas: se o mesmo ISSN tiver vários estratos,
    # mantém o melhor (A1 é o topo). Com `area`, filtra para uma só área.
    rank = {
        e: i
        for i, e in enumerate(
            ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "B5", "C"]
        )
    }
    out: dict[str, str] = {}
    for row in reader:
        if area_norm and norm_name(row.get(area_col, "")) != area_norm:
            continue
        k = norm_issn(row.get(issn_col, ""))
        e = (row.get(estr_col) or "").strip().upper()
        if not k or e not in rank:
            continue
        if k not in out or rank[e] < rank[out[k]]:
            out[k] = e
    return out


def _ckey(s: str) -> str:
    s = (
        unicodedata.normalize("NFKD", s or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def load_qualis_conf(path: Path = QUALIS_CONF_FILE) -> tuple[dict, dict]:
    """Qualis de conferências CC. Retorna (acronimo->estrato, nome_norm->estrato)."""
    if not Path(path).exists():
        return {}, {}
    data = json.loads(Path(path).read_text()).get("data", [])
    acro, name = {}, {}
    for row in data:
        if len(row) < 3:
            continue
        ac, full, est = row[0].strip(), row[1].strip(), row[2].strip().upper()
        if ac:
            acro[ac.upper()] = est
        nm = re.sub(r"^\s*" + re.escape(ac) + r"\s*[-:]\s*", "", full)
        k = _ckey(nm)
        if len(k) > 6:
            name[k] = est
    return acro, name


# Siglas de organizações/editoras (não são acrônimos de evento) — evitam falso match.
_CONF_ACRO_STOP = {
    "IEEE",
    "ACM",
    "IFIP",
    "IADIS",
    "IARIA",
    "SPIE",
    "SBC",
    "IET",
    "AAAI",
}
_CONF_FUZZY_MIN = 0.90  # similaridade mínima p/ casar por nome (determinístico)


def match_conf_qualis(evento_clean: str, acro: dict, name: dict) -> str | None:
    """Casa um congresso (nome normalizado) ao Qualis CC.

    Ordem (mais confiável → menos): acrônimo entre parênteses; nome exato;
    melhor match fuzzy de nome (≥ limiar, determinístico); acrônimo isolado
    (≥3 letras, fora da stoplist de organizações).
    """
    if not acro and not name:
        return None
    # 1) acrônimo entre parênteses — sinal explícito do autor
    for cand in re.findall(r"\(([A-Za-z][A-Za-z0-9\-]{1,})\)", evento_clean):
        cu = cand.upper()
        if cu in acro and cu not in _CONF_ACRO_STOP:
            return acro[cu]
    # 2) nome exato (sem o que está entre parênteses)
    k = _ckey(re.sub(r"\([^)]*\)", "", evento_clean))
    if not k:
        return None
    if k in name:
        return name[k]
    # 3) melhor match fuzzy de nome (determinístico: maior ratio acima do limiar)
    best_est, best_r = None, 0.0
    for nmk, est in name.items():
        if abs(len(nmk) - len(k)) > 12:
            continue
        r = SequenceMatcher(None, k, nmk).ratio()
        if r > best_r:
            best_r, best_est = r, est
    if best_r >= _CONF_FUZZY_MIN:
        return best_est
    # 4) acrônimo isolado (≥3 letras), fora da stoplist
    for cand in re.findall(r"\b([A-Z]{3,6})\b", evento_clean):
        if cand not in _CONF_ACRO_STOP and cand in acro:
            return acro[cand]
    return None


# ---------------------------------------------------------------------------
# Extração dos veículos a partir do Lattes
# ---------------------------------------------------------------------------


def collect_venues(roster: dict[str, str]) -> tuple[dict, dict, dict]:
    by_id = {}
    for f in glob.glob(str(LATTES_DIR / "*.json")):
        m = re.search(r"_(\d{16})\.json$", f)
        if m:
            by_id[m.group(1)] = f

    journals: dict[str, dict] = {}  # chave = issn normalizado (fallback nome)
    confs: dict[str, dict] = {}  # chave = nome normalizado do evento
    # artigos-fonte: cada artigo de periódico (deduplicado por veículo+título),
    # base das métricas SJR/Qualis. Coautores do roster são creditados juntos.
    artigos: dict[tuple, dict] = {}

    for nome, lid in roster.items():
        f = by_id.get(lid)
        if not f:
            continue
        d = json.loads(Path(f).read_text())
        pb = d.get("producao_bibliografica", {}) or {}

        for a in pb.get("artigos_periodicos", []) or []:
            issn = norm_issn(a.get("issn", ""))
            rev = (a.get("revista") or "").strip()
            key = issn or ("name:" + norm_name(rev))
            if not rev and not issn:
                continue
            j = journals.setdefault(
                key,
                {
                    "revista": rev,
                    "issn": a.get("issn", "").strip(),
                    "issn_norm": issn,
                    "n": 0,
                    "docentes": set(),
                    "anos": [],
                    "_works": set(),
                },
            )
            # dedup co-autoria: mesma obra (título) no mesmo veículo conta 1 vez,
            # mas todos os docentes coautores são creditados em "docentes".
            wk = norm_name(a.get("titulo", ""))
            if wk and wk in j["_works"]:
                j["docentes"].add(nome)
            else:
                if wk:
                    j["_works"].add(wk)
                j["n"] += 1
                j["docentes"].add(nome)
                if a.get("ano"):
                    j["anos"].append(a["ano"])
            if not j["revista"] and rev:
                j["revista"] = rev
            # artigo-fonte (só com título; dedup por veículo+título, créditos somados)
            titulo = (a.get("titulo") or "").strip()
            if titulo:
                ak = (key, wk)
                ar = artigos.setdefault(
                    ak,
                    {
                        "titulo": titulo,
                        "ano": a.get("ano"),
                        "revista": rev,
                        "issn_norm": issn,
                        "doi": (a.get("doi") or "").strip(),
                        "docentes": set(),
                    },
                )
                ar["docentes"].add(nome)
                if not ar["revista"] and rev:
                    ar["revista"] = rev
                if not ar["doi"] and (a.get("doi") or "").strip():
                    ar["doi"] = (a.get("doi") or "").strip()

        for c in pb.get("trabalhos_completos_congressos", []) or []:
            ev = (c.get("evento") or "").strip()
            if not ev:
                continue
            clean = normalize_conf(ev) or ev
            key = conf_key(clean) or norm_name(ev)
            e = confs.setdefault(
                key,
                {
                    "evento": clean,
                    "n": 0,
                    "docentes": set(),
                    "anos": [],
                    "_names": Counter(),
                    "_works": set(),
                },
            )
            wk = norm_name(c.get("titulo", ""))
            if wk and wk in e["_works"]:
                e["docentes"].add(nome)
            else:
                if wk:
                    e["_works"].add(wk)
                e["n"] += 1
                e["docentes"].add(nome)
                e["_names"][clean] += 1
                if c.get("ano"):
                    e["anos"].append(c["ano"])

    # nome de exibição = variante normalizada mais frequente (desempate: mais curta)
    for e in confs.values():
        e["evento"] = max(e["_names"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        del e["_names"], e["_works"]
    for j in journals.values():
        del j["_works"]

    return journals, confs, artigos


def enrich_and_summarize(
    journals: dict,
    confs: dict,
    scimago: dict,
    qualis: dict,
    top: int,
    conf_acro: dict | None = None,
    conf_name: dict | None = None,
    artigos: dict | None = None,
) -> dict:
    conf_acro = conf_acro or {}
    conf_name = conf_name or {}
    artigos = artigos or {}
    # enriquece revistas
    jrows = []
    q_dist = defaultdict(int)  # quartil SJR
    qualis_dist = defaultdict(int)  # estrato Qualis
    artigos_total = 0
    for j in journals.values():
        artigos_total += j["n"]
        sm = scimago.get(j["issn_norm"], {})
        quartil = sm.get("quartil", "") or "—"
        qcap = qualis.get(j["issn_norm"], "") or "—"
        q_dist[quartil if quartil != "" else "—"] += j["n"]
        qualis_dist[qcap if qcap != "" else "—"] += j["n"]
        jrows.append(
            {
                "revista": j["revista"],
                "issn": j["issn"],
                "publicacoes": j["n"],
                "n_docentes": len(j["docentes"]),
                "ano_min": min(j["anos"]) if j["anos"] else None,
                "ano_max": max(j["anos"]) if j["anos"] else None,
                "sjr": sm.get("sjr", ""),
                "sjr_quartil": quartil,
                "sjr_h_index": sm.get("h_index", ""),
                "sjr_titulo": sm.get("titulo", ""),
                "qualis": qcap,
            }
        )
    jrows.sort(key=lambda r: -r["publicacoes"])

    conf_dist = defaultdict(int)  # estrato Qualis CC por trabalho
    crows = []
    for c in confs.values():
        est = match_conf_qualis(c["evento"], conf_acro, conf_name) or "—"
        conf_dist[est] += c["n"]
        crows.append(
            {
                "evento": c["evento"],
                "publicacoes": c["n"],
                "n_docentes": len(c["docentes"]),
                "ano_min": min(c["anos"]) if c["anos"] else None,
                "ano_max": max(c["anos"]) if c["anos"] else None,
                "qualis": est,
            }
        )
    crows.sort(key=lambda r: -r["publicacoes"])
    congressos_total = sum(c["publicacoes"] for c in crows)

    matched_sjr = sum(1 for r in jrows if r["sjr_quartil"] not in ("—", ""))
    matched_qualis = sum(1 for r in jrows if r["qualis"] not in ("—", ""))
    conf_matched = sum(1 for r in crows if r["qualis"] not in ("—", ""))

    # artigos-fonte: classifica cada artigo pelo SJR/Qualis do veículo (por ISSN)
    def _ano_int(v):
        try:
            return int(str(v).strip()[:4])
        except (ValueError, TypeError):
            return 0

    arows = []
    for ar in artigos.values():
        sm = scimago.get(ar["issn_norm"], {})
        arows.append(
            {
                "titulo": ar["titulo"],
                "ano": _ano_int(ar["ano"]) or None,
                "revista": ar["revista"],
                "issn": ar["issn_norm"],
                "doi": ar["doi"],
                "docentes": sorted(ar["docentes"]),
                "sjr_quartil": sm.get("quartil", "") or "—",
                "qualis": qualis.get(ar["issn_norm"], "") or "—",
            }
        )
    arows.sort(key=lambda r: (-(r["ano"] or 0), r["titulo"].lower()))

    return {
        "resumo": {
            "n_revistas_distintas": len(jrows),
            "n_artigos": artigos_total,
            "n_congressos_distintos": len(crows),
            "n_trabalhos_congresso": congressos_total,
            "revistas_com_sjr": matched_sjr,
            "revistas_com_qualis": matched_qualis,
            "congressos_com_qualis": conf_matched,
        },
        "distribuicao_sjr_quartil": dict(sorted(q_dist.items())),
        "distribuicao_qualis": dict(sorted(qualis_dist.items())),
        "distribuicao_qualis_conf": dict(sorted(conf_dist.items())),
        "top_revistas": jrows[:top],
        "top_congressos": crows[:top],
        "revistas": jrows,
        "congressos": crows,
        "artigos_fonte": arows,
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_Q_COLOR = {
    "Q1": "var(--brand)",
    "Q2": "var(--blue)",
    "Q3": "var(--amber)",
    "Q4": "var(--rose)",
    "—": "var(--line2)",
}
_QUALIS_COLOR = {
    "A1": "var(--brand-d)",
    "A2": "var(--brand)",
    "A3": "#3f9d63",
    "A4": "#6bbf86",
    "B1": "var(--blue)",
    "B2": "#5b8fc0",
    "B3": "var(--amber)",
    "B4": "#c9a13b",
    "B5": "#d8b56b",
    "C": "var(--rose)",
    "—": "var(--line2)",
}


def _bars(dist: dict, order: list, colors: dict, total: int) -> str:
    mx = max(list(dist.values()) + [1])
    rows = ""
    for k in order:
        v = dist.get(k, 0)
        if not v:
            continue
        w = v / mx * 100
        pct = f"{v / total * 100:.0f}%" if total else ""
        rows += (
            f'<div class="brow"><span class="bl">{k}</span>'
            f'<div class="btrack"><div class="bfill" style="width:{max(w,1.5):.1f}%;'
            f'background:{colors.get(k,"var(--line2)")};"></div></div>'
            f'<span class="bv">{v} <span style="color:var(--muted);font-weight:500;">· {pct}</span></span></div>'
        )
    return rows


def _insight(txt: str) -> str:
    """Caixa de insight automático (uma conclusão por seção)."""
    if not txt:
        return ""
    return (
        f'<div style="background:#eef4fb;border-left:4px solid var(--blue,#2f6fb0);'
        f"border-radius:8px;padding:12px 15px;margin-top:16px;font-size:13.5px;"
        f'line-height:1.6;color:var(--ink,#16241a);">'
        f'<b style="color:var(--blue,#2f6fb0);">💡 Insight:</b> {txt}</div>'
    )


def _lider_fwci_rows(
    ranking: list | None, citacoes: list | None, field: str = "area", min_found: int = 5
) -> str:
    """Por área (field='area') ou sub-área (field='subarea'): docente de maior FWCI."""
    if not ranking or not citacoes:
        return ""
    cbn = {c["nome"]: c for c in citacoes}
    best: dict[str, dict] = {}
    for rr in ranking:
        g = rr.get(field) or "—"
        if g == "—":
            continue
        c = cbn.get(rr["nome"])
        if (
            not c
            or c.get("encontrados_openalex", 0) < min_found
            or not c.get("fwci_mediana")
        ):
            continue
        if g not in best or c["fwci_mediana"] > best[g]["c"]["fwci_mediana"]:
            best[g] = {"nome": rr["nome"], "c": c}
    rows = ""
    for g, b in sorted(best.items(), key=lambda kv: -kv[1]["c"]["fwci_mediana"]):
        c = b["c"]
        rows += (
            f"<tr><td>{g}</td><td>{b['nome']}</td>"
            f"<td style='color:var(--brand);font-weight:700;'>{c['fwci_mediana']:.2f}</td>"
            f"<td>{c.get('artigos_top10pct',0)}</td><td>{c.get('citacoes_total',0)}</td>"
            f"<td>{c.get('h_index',0)}</td></tr>"
        )
    return rows


def _quad_qualis_fwci(ranking: list | None, citacoes: list | None) -> str:
    """Quadrante Qualis (veículo, X) × FWCI (impacto normalizado, Y)."""
    if not ranking or not citacoes:
        return ""
    import math as _m

    cbn = {c["nome"]: c for c in citacoes}
    pts = []
    for rr in ranking:
        c = cbn.get(rr["nome"])
        if (
            not c
            or rr.get("artigos_qualis", 0) < 3
            or c.get("encontrados_openalex", 0) < 5
        ):
            continue
        if not c.get("fwci_mediana"):
            continue
        pts.append(
            {
                "nome": rr["nome"],
                "x": rr["qualidade"],
                "y": c["fwci_mediana"],
                "h": c.get("h_index", 0),
            }
        )
    if len(pts) < 4:
        return ""

    def _med(v):
        s = sorted(v)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    medx, medy = round(_med([p["x"] for p in pts]), 1), round(
        _med([p["y"] for p in pts]), 2
    )
    maxy = max(p["y"] for p in pts) or 1
    W, Hh, M = 760, 440, 54

    def px(x):
        return M + (x / 100) * (W - 2 * M)

    def py(y):
        return Hh - M - (y / maxy) * (Hh - 2 * M)

    lx, ly = px(medx), py(medy)
    QCOL = {
        "estrela": "var(--brand)",
        "veiculo": "var(--amber)",
        "subvalorizado": "var(--blue)",
        "nicho": "var(--muted)",
    }
    for p in pts:
        hq, hf = p["x"] >= medx, p["y"] >= medy
        p["quad"] = (
            "estrela"
            if hq and hf
            else (
                "veiculo"
                if hq and not hf
                else "subvalorizado" if not hq and hf else "nicho"
            )
        )
    dots = "".join(
        f'<circle cx="{px(p["x"]):.0f}" cy="{py(p["y"]):.0f}" r="{4+_m.sqrt(p["h"]):.0f}" '
        f'fill="{QCOL[p["quad"]]}" fill-opacity="0.75"/>'
        for p in pts
    )
    lab = (
        sorted(pts, key=lambda p: -p["y"])[:6]
        + [p for p in pts if p["quad"] == "subvalorizado"][:5]
    )
    labels = "".join(
        f'<text x="{px(p["x"])+6:.0f}" y="{py(p["y"])+3:.0f}" font-size="10" fill="#16241a">'
        f'{p["nome"].split()[0]} {p["nome"].split()[-1]}</text>'
        for p in {id(p): p for p in lab}.values()
    )
    svg = f"""<svg viewBox="0 0 {W} {Hh}" style="width:100%;height:auto;font-family:var(--font);">
      <rect x="{lx:.0f}" y="{M}" width="{W-M-lx:.0f}" height="{ly-M:.0f}" fill="#0f7a40" opacity="0.05"/>
      <rect x="{M}" y="{M}" width="{lx-M:.0f}" height="{ly-M:.0f}" fill="#2f6fb0" opacity="0.05"/>
      <line x1="{lx:.0f}" y1="{M}" x2="{lx:.0f}" y2="{Hh-M}" stroke="var(--line2)" stroke-dasharray="4"/>
      <line x1="{M}" y1="{ly:.0f}" x2="{W-M}" y2="{ly:.0f}" stroke="var(--line2)" stroke-dasharray="4"/>
      <line x1="{M}" y1="{py(1.0):.0f}" x2="{W-M}" y2="{py(1.0):.0f}" stroke="var(--rose)" stroke-dasharray="2" opacity="0.5"/>
      <text x="{W-M}" y="{py(1.0)-3:.0f}" text-anchor="end" font-size="9" fill="var(--rose)">FWCI = 1 (média mundial)</text>
      <text x="{W-M}" y="{M-8}" text-anchor="end" font-size="11" fill="var(--brand)" font-weight="700">★ Estrelas (Qualis alto + FWCI alto)</text>
      <text x="{M}" y="{M-8}" font-size="11" fill="var(--blue)" font-weight="700">Subvalorizado (impacto real, Qualis menor)</text>
      <text x="{W-M}" y="{Hh-M+18}" text-anchor="end" font-size="11" fill="var(--amber)" font-weight="700">Veículo forte, baixo impacto</text>
      <text x="{M}" y="{Hh-M+18}" font-size="11" fill="var(--muted)" font-weight="700">Nicho</text>
      <text x="{W/2:.0f}" y="{Hh-12}" text-anchor="middle" font-size="11" fill="var(--sub)">→ Qualis (nota média do veículo) · mediana {medx}</text>
      <text x="14" y="{Hh/2:.0f}" font-size="11" fill="var(--sub)" transform="rotate(-90 14 {Hh/2:.0f})" text-anchor="middle">→ FWCI (impacto normalizado) · mediana {medy}</text>
      {dots}{labels}</svg>"""

    def tab(quad, titulo, cor):
        items = sorted((p for p in pts if p["quad"] == quad), key=lambda p: -p["y"])
        rows = "".join(
            f"<tr><td>{p['nome']}</td><td>{p['x']:.0f}</td><td class='n'>{p['y']:.2f}</td><td>{p['h']}</td></tr>"
            for p in items
        )
        return (
            f'<div><h3 style="color:{cor};font-size:15px;margin:0 0 6px;">{titulo} ({sum(1 for p in pts if p["quad"]==quad)})</h3>'
            f"<table><thead><tr><th>Docente</th><th>Qualis</th><th>FWCI</th><th>h</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )

    tabs = (
        tab("estrela", "★ Estrelas", "var(--brand)")
        + tab("subvalorizado", "Subvalorizado pelo Qualis", "var(--blue)")
        + tab("veiculo", "Veículo forte, baixo impacto", "var(--amber)")
        + tab("nicho", "Nicho", "var(--muted)")
    )
    return (
        f'<h3 style="font-family:var(--serif);font-size:20px;margin:26px 0 8px;">Quadrante Qualis × FWCI</h3>'
        f'<p class="desc">Veículo (<b>Qualis</b>, nota média do periódico 0–100, eixo X) × '
        f"<b>impacto normalizado</b> (FWCI — citações relativas à média mundial da área, eixo Y) de "
        f"{len(pts)} docentes. A mediana de cada eixo divide os 4 quadrantes (posição <i>relativa ao "
        f"grupo</i>, não juízo de mérito): "
        f"<b>★ Estrelas</b> = Qualis e FWCI ambos <b>acima</b> da mediana (bom veículo e citado acima da média da área); "
        f"<b>Subvalorizado</b> = FWCI acima, Qualis abaixo (impacto real alto apesar do veículo menor — o Qualis subestima); "
        f"<b>Veículo forte, baixo impacto</b> = Qualis acima, FWCI abaixo (publica em estrato alto mas citado abaixo da média da área); "
        f"<b>Nicho</b> = Qualis e FWCI ambos <b>abaixo</b> da mediana (veículo modesto e impacto modesto).</p>"
        f'<div class="card">{svg}</div><div class="grid2" style="margin-top:16px;">{tabs}</div>'
    )


_SRC_TEMPLATE = """
    <section class="section">
      <div class="eyebrow">Rastreabilidade</div>
      <h2>Artigos-fonte das métricas</h2>
      <p class="desc">A base de tudo: cada <b>artigo de periódico</b> dos docentes (Lattes), com a
      classificação do veículo de onde saem as métricas — <b>SJR</b> (quartil SCImago) e
      <b>Qualis</b> (estrato CAPES), casados por <b>ISSN</b>. Filtre por texto, quartil, estrato ou
      DOI; clique no cabeçalho para ordenar. Títulos com DOI linkam para o artigo.</p>
      <div class="af-chips">
        <div class="af-chip"><b>__N__</b><span>artigos distintos</span></div>
        <div class="af-chip b2"><b>__PSJR__%</b><span>com SJR</span></div>
        <div class="af-chip b3"><b>__PQUALIS__%</b><span>com Qualis</span></div>
        <div class="af-chip b4"><b>__PDOI__%</b><span>com DOI</span></div>
      </div>
      <div class="af-controls">
        <input id="af-q" type="search" placeholder="Filtrar por título, revista ou docente…">
        <select id="af-sjr"><option value="">SJR: todos</option>__SJROPTS__</select>
        <select id="af-qualis"><option value="">Qualis: todos</option>__QUALISOPTS__</select>
        <label class="af-chk"><input type="checkbox" id="af-doi"> só com DOI</label>
        <span id="af-count"></span>
      </div>
      <div class="card af-wrap">
      <table class="sortable af-tbl">
        <thead><tr><th>Ano</th><th>Título</th><th>Revista</th><th>SJR</th>__QHEAD__<th>Docente(s)</th></tr></thead>
        <tbody id="af-body">__ROWS__</tbody>
      </table>
      </div>
    </section>
    <style>
      .af-chips{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;}
      .af-chip{flex:1;min-width:120px;background:var(--paper,#fff);border:1px solid var(--line,#e3ece5);
        border-left:4px solid var(--brand,#0f7a40);border-radius:12px;padding:11px 16px;
        box-shadow:0 1px 3px rgba(16,40,24,.05);}
      .af-chip.b2{border-left-color:var(--blue,#2f6fb0);}
      .af-chip.b3{border-left-color:var(--amber,#b8860b);}
      .af-chip.b4{border-left-color:var(--rose,#b5455f);}
      .af-chip b{display:block;font-size:22px;font-weight:800;color:var(--brand-d,#0a5c30);line-height:1;}
      .af-chip span{font-size:11px;color:var(--muted,#71857a);text-transform:uppercase;letter-spacing:.04em;}
      .af-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px;}
      .af-controls input[type=search]{flex:1;min-width:220px;padding:9px 13px;
        border:1px solid var(--line2,#cfddd3);border-radius:10px;font:inherit;font-size:14px;}
      .af-controls select{font:inherit;font-size:13px;padding:9px 12px;border:1px solid var(--line2,#cfddd3);
        border-radius:10px;background:#fff;cursor:pointer;}
      .af-chk{font-size:13px;color:var(--muted,#71857a);display:inline-flex;gap:5px;align-items:center;cursor:pointer;}
      #af-count{font-size:13px;color:var(--muted,#71857a);margin-left:auto;font-weight:600;}
      .af-wrap{padding:0;max-height:68vh;overflow-y:auto;overflow-x:hidden;}
      /* fixo e 100% da largura — sem rolagem horizontal (vence a regra mobile do tema) */
      .af-tbl{margin:0;border:none;border-radius:0;box-shadow:none;
        display:table!important;width:100%!important;table-layout:fixed;}
      .af-tbl th,.af-tbl td{white-space:normal;overflow-wrap:anywhere;word-break:break-word;
        vertical-align:top;}
      .af-tbl th:nth-child(1),.af-tbl td:nth-child(1){width:6%;}      /* Ano */
      .af-tbl th:nth-child(2),.af-tbl td:nth-child(2){width:38%;}     /* Título */
      .af-tbl th:nth-child(3),.af-tbl td:nth-child(3){width:22%;}     /* Revista */
      .af-tbl th:nth-child(4),.af-tbl td:nth-child(4){width:8%;}      /* SJR */
      .af-tbl th:nth-child(5),.af-tbl td:nth-child(5){width:8%;}      /* Qualis */
      .af-tbl th:last-child,.af-tbl td:last-child{width:18%;}         /* Docente(s) */
      .af-tbl thead th{position:sticky;top:0;background:var(--brand-l,#e7f4ec);z-index:2;}
      .af-tbl tbody tr:nth-child(even){background:rgba(16,40,24,.022);}
      .af-tbl tbody tr:hover{background:var(--brand-l,#e7f4ec);}
      .af-doitag{display:inline-block;font-size:9.5px;font-weight:700;color:#0a5c30;background:#dff0e6;
        border-radius:4px;padding:0 5px;margin-left:5px;vertical-align:middle;letter-spacing:.03em;}
    </style>
    <script>
    (function(){
      var q=document.getElementById('af-q'),fsjr=document.getElementById('af-sjr'),
          fqual=document.getElementById('af-qualis'),fdoi=document.getElementById('af-doi'),
          body=document.getElementById('af-body'),cnt=document.getElementById('af-count');
      if(!body) return;
      var rows=[].slice.call(body.querySelectorAll('tr'));
      function upd(){
        var term=(q.value||'').trim().toLowerCase(),vs=fsjr.value,vq=fqual.value,vd=fdoi.checked,vis=0;
        rows.forEach(function(r){
          var ok=(!term||(r.getAttribute('data-f')||'').indexOf(term)>=0)
            &&(!vs||r.getAttribute('data-sjr')===vs)
            &&(!vq||r.getAttribute('data-qualis')===vq)
            &&(!vd||r.getAttribute('data-doi')==='1');
          r.style.display=ok?'':'none'; if(ok) vis++;
        });
        cnt.textContent=vis+' de '+rows.length+' artigos';
      }
      [q,fsjr,fqual,fdoi].forEach(function(el){el.addEventListener('input',upd);el.addEventListener('change',upd);});
      upd();
    })();
    </script>"""


EXPL_SJR_QUALIS = bloco_metrica(
    {
        "titulo": "Qualidade dos veículos (SJR e Qualis)",
        "o_que": "Distribuição dos artigos pelo <b>quartil SJR</b> (SCImago, internacional) e pelo "
        "<b>estrato Qualis</b> (CAPES, nacional), casados por <b>ISSN</b> do periódico.",
        "formula": "SJR: Q1 (topo 25%) → Q4 · Qualis: A1 (topo) → C",
        "como_ler": "Mais artigos em <b>Q1/Q2</b> e <b>A1-A2</b> = o campus publica em veículos de "
        "maior prestígio. É a qualidade do <b>onde se publica</b>.",
        "nao_concluir": [
            "Veículo de prestígio <b>≠</b> artigo de alto impacto — a <b>DORA</b> desaconselha avaliar "
            "o artigo pelo periódico.",
            "O SJR só cobre o <b>Scopus</b>; periódicos nacionais sem indexação ficam de fora "
            "(subestima a produção nacional).",
        ],
        "gestores": "Orientar a escolha de veículos e ler <b>junto com o FWCI</b> (impacto real). "
        "Periódico forte com poucas citações merece atenção.",
    }
)
EXPL_QUAD = bloco_metrica(
    {
        "titulo": "Quadrante Qualis × FWCI",
        "o_que": "Cruza o <b>prestígio do veículo</b> (Qualis, eixo X) com o <b>impacto real "
        "normalizado</b> (FWCI, eixo Y) de cada docente, dividido pela mediana do grupo.",
        "como_ler": "<b>Estrelas</b> (Qualis e FWCI altos); <b>Subvalorizado</b> (FWCI alto, Qualis "
        "menor — o Qualis subestima o impacto real); <b>Veículo forte, baixo impacto</b>; "
        "<b>Nicho</b> (ambos abaixo).",
        "nao_concluir": [
            "A posição é <b>relativa ao grupo</b> (mediana), <b>não</b> juízo absoluto de mérito.",
            "FWCI depende da <b>cobertura por DOI</b> (OpenAlex) e da amostra — quadrantes com poucos "
            "artigos são instáveis.",
        ],
        "gestores": "Achar os <b>subvalorizados</b> (impacto real alto apesar do veículo) para apoiar e "
        "dar visibilidade; usar para conversa, não para ranking.",
    }
)


def render_html(
    payload: dict,
    qualis_applied: bool,
    ranking: list | None = None,
    asc: list | None = None,
    citacoes: list | None = None,
) -> str:
    from src.scripts.generate_docentes_executive import CSS

    r = payload["resumo"]
    qdist = payload["distribuicao_sjr_quartil"]
    subval = None
    # normaliza chave '-' para '—'
    qd = defaultdict(int)
    for k, v in qdist.items():
        qd["—" if k in ("-", "") else k] += v
    tot_art = r["n_artigos"]
    ranked = sum(qd.get(x, 0) for x in ["Q1", "Q2", "Q3", "Q4"])
    pct_scopus = round(ranked / tot_art * 100) if tot_art else 0
    q1q2 = qd.get("Q1", 0) + qd.get("Q2", 0)

    kpis = f"""
    <section class="section"><div class="kpis">
      <div class="kpi"><div class="n">{r['n_revistas_distintas']}</div>
        <div class="u">revistas distintas</div><div class="s">{r['n_artigos']} artigos em periódicos</div></div>
      <div class="kpi"><div class="n">{pct_scopus}%</div>
        <div class="u">indexado no Scopus</div><div class="s">{ranked} de {tot_art} artigos com SJR</div></div>
      <div class="kpi"><div class="n">{qd.get('Q1',0)}</div>
        <div class="u">artigos em Q1</div><div class="s">topo mundial · {round(qd.get('Q1',0)/tot_art*100) if tot_art else 0}% do total</div></div>
      <div class="kpi"><div class="n">{r['n_congressos_distintos']}</div>
        <div class="u">congressos distintos</div><div class="s">{r['n_trabalhos_congresso']} trabalhos completos</div></div>
    </div></section>"""

    sjr_legend = (
        '<div class="legend">'
        '<span><i style="background:var(--brand)"></i>Q1</span>'
        '<span><i style="background:var(--blue)"></i>Q2</span>'
        '<span><i style="background:var(--amber)"></i>Q3</span>'
        '<span><i style="background:var(--rose)"></i>Q4</span>'
        '<span><i style="background:var(--line2)"></i>sem SJR</span></div>'
    )
    sec_sjr = f"""
    <section class="section">
      <div class="eyebrow">Impacto internacional</div>
      <h2>Qualidade dos periódicos — SCImago Journal Rank (SJR)</h2>
      <p class="desc">Distribuição dos {tot_art} artigos pelo quartil do periódico no SJR
      (métrica internacional derivada do Scopus). <b>{q1q2}</b> artigos ({round(q1q2/tot_art*100) if tot_art else 0}%)
      em Q1+Q2; {tot_art-ranked} em periódicos fora do Scopus (majoritariamente nacionais).</p>
      <div class="card"><div class="card-head"><h3>Artigos por quartil SJR</h3>{sjr_legend}</div>
        {_bars(qd, ['Q1','Q2','Q3','Q4','—'], _Q_COLOR, tot_art)}</div>
      {_insight(f"{round(q1q2/tot_art*100) if tot_art else 0}% da produção está em <b>Q1+Q2</b> "
                f"(topo mundial), mas <b>{round((tot_art-ranked)/tot_art*100) if tot_art else 0}%</b> "
                f"({tot_art-ranked} artigos) ficam fora do Scopus — periódicos nacionais que o SJR não "
                f"indexa. O SJR mede só a fatia internacional; o Qualis (abaixo) cobre o resto.")}
    </section>"""

    # tabela top revistas
    def _qbadge(q, palette):
        c = palette.get(q, "var(--line2)")
        txt = "#fff" if q not in ("—", "") else "var(--muted)"
        return (
            f'<span style="display:inline-block;min-width:30px;text-align:center;'
            f"padding:2px 8px;border-radius:6px;font-size:12px;font-weight:700;"
            f'background:{c};color:{txt};">{q or "—"}</span>'
        )

    # ordena por quartil SJR (Q1 melhor) e, dentro do quartil, pelo índice SJR desc
    _qrank = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "—": 9, "": 9, "-": 9}

    def _jkey(j):
        try:
            sjr = float(j["sjr"]) if j.get("sjr") else -1.0
        except ValueError:
            sjr = -1.0
        return (_qrank.get(j.get("sjr_quartil", "—"), 9), -sjr)

    jr = sorted(payload["revistas"], key=_jkey)[:20]
    qcol_head = "<th>Qualis</th>" if qualis_applied else ""
    jrows = ""
    for j in jr:
        qcell = (
            f"<td>{_qbadge(j.get('qualis','—'), _QUALIS_COLOR)}</td>"
            if qualis_applied
            else ""
        )
        jrows += (
            f"<tr><td>{j['revista'][:54]}</td>"
            f"<td>{j['publicacoes']}</td>"
            f"<td>{_qbadge(j['sjr_quartil'], _Q_COLOR)}</td>"
            f"<td>{j['sjr'] or '—'}</td><td>{j['sjr_h_index'] or '—'}</td>"
            f"{qcell}</tr>"
        )
    _n_q1 = sum(1 for x in payload["revistas"] if x.get("sjr_quartil") == "Q1")
    if jr:
        _topj = jr[0]
        ins_top = (
            f"O campus publica em <b>{_n_q1} revistas Q1</b> distintas; a de maior impacto é "
            f"<b>{_topj['revista'][:54]}</b> (SJR {_topj['sjr_quartil']}, índice {_topj['sjr'] or '—'}). "
            f"As revistas com mais artigos do campus, porém, são em geral nacionais sem SJR — "
            f"volume de publicação e prestígio do veículo nem sempre coincidem."
        )
    else:
        ins_top = "Sem periódicos indexados no SJR para o conjunto atual."
    sec_top = f"""
    <section class="section">
      <div class="eyebrow">Onde publicam</div>
      <h2>Principais revistas</h2>
      <p class="desc">Top 20 periódicos ordenados por quartil SJR e, dentro do quartil,
      pelo índice SJR (do maior impacto ao menor). Coluna "Artigos" = nº de artigos dos docentes.</p>
      <table><thead><tr><th>Revista</th><th>Artigos</th><th>SJR</th><th>Índice SJR</th><th>H</th>{qcol_head}</tr></thead>
      <tbody>{jrows}</tbody></table>
      {_insight(ins_top)}
    </section>"""

    # Qualis section
    sec_qualis = ""
    if qualis_applied:
        qld = defaultdict(int)
        for k, v in payload["distribuicao_qualis"].items():
            qld["—" if k in ("-", "") else k] += v
        qmatched = r.get("revistas_com_qualis", 0)
        a_strata = sum(qld.get(x, 0) for x in ["A1", "A2", "A3", "A4"])
        ql_legend = (
            '<div class="legend">'
            '<span><i style="background:var(--brand-d)"></i>A1–A4</span>'
            '<span><i style="background:var(--blue)"></i>B1–B2</span>'
            '<span><i style="background:var(--amber)"></i>B3–B5</span>'
            '<span><i style="background:var(--rose)"></i>C</span>'
            '<span><i style="background:var(--line2)"></i>sem Qualis</span></div>'
        )
        sec_qualis = f"""
    <section class="section">
      <div class="eyebrow">Classificação nacional</div>
      <h2>Qualis CAPES/CNPq (2017–2020, melhor estrato)</h2>
      <p class="desc">Estrato Qualis dos {tot_art} artigos — melhor classificação do periódico
      entre todas as áreas de avaliação. <b>{a_strata}</b> artigos em estratos A (A1–A4);
      {qmatched} das {r['n_revistas_distintas']} revistas têm Qualis.</p>
      <div class="card"><div class="card-head"><h3>Artigos por estrato Qualis</h3>{ql_legend}</div>
        {_bars(qld, ['A1','A2','A3','A4','B1','B2','B3','B4','B5','C','—'], _QUALIS_COLOR, tot_art)}</div>
      {_insight(f"<b>{round(a_strata/tot_art*100) if tot_art else 0}%</b> dos artigos ({a_strata} de "
                f"{tot_art}) estão em estrato <b>A (A1–A4)</b> pela régua nacional. O Qualis classifica "
                f"{qmatched} revistas — inclui periódicos brasileiros que o SJR não indexa, por isso a "
                f"cobertura aqui é maior que na seção SJR. As duas réguas se complementam: SJR mede "
                f"alcance internacional, Qualis mede reconhecimento no sistema CAPES.")}
    </section>"""

    # ranking de docentes por impacto (Qualis)
    MIN_ART = 5  # piso de artigos p/ médias de qualidade (usado no combinado)

    # ascensão: quem cresceu em qualidade no último decênio
    sec_asc = ""
    if asc:
        up = [x for x in asc if x["delta"] > 0][:12]
        ar = ""
        for i, x in enumerate(up, 1):
            seta = "▲"
            ar += (
                f"<tr><td>{i}</td><td>{x['nome']}</td><td>{x['subarea']}</td>"
                f"<td>{x['media_antiga']:.0f}</td><td>{x['media_recente']:.0f}</td>"
                f"<td style='color:var(--brand);font-weight:700;'>{seta} +{x['delta']:.0f}</td>"
                f"<td>{x['n_antigo']}→{x['n_recente']}</td></tr>"
            )
        # ascensão por FWCI (impacto crescente entre janelas)
        sec_fwasc = ""
        if citacoes:
            fa = [
                c
                for c in citacoes
                if c.get("fwci_delta") is not None and c["fwci_delta"] > 0
            ]
            fa.sort(key=lambda c: -c["fwci_delta"])
            fr = "".join(
                f"<tr><td>{i}</td><td>{c['nome']}</td>"
                f"<td>{c['fwci_antigo']:.2f}</td><td>{c['fwci_recente']:.2f}</td>"
                f"<td style='color:var(--brand);font-weight:700;'>▲ +{c['fwci_delta']:.2f}</td></tr>"
                for i, c in enumerate(fa[:12], 1)
            )
            if fr:
                sec_fwasc = f"""
      <h3 style="font-family:var(--serif);font-size:20px;margin:28px 0 8px;">Ascensão por FWCI (impacto crescente)</h3>
      <p class="desc">Impacto normalizado <b>subindo</b>: FWCI mediano dos artigos de <b>2016–2020</b>
      vs <b>2021–2025</b>. Δ positivo = os artigos recentes são mais citados (relativo à área) que os
      antigos. Exige ≥2 artigos com FWCI em cada janela.</p>
      <table><thead><tr><th>#</th><th>Docente</th><th>FWCI 2016–20</th><th>FWCI 2021–25</th>
      <th>Δ FWCI</th></tr></thead><tbody>{fr}</tbody></table>"""
        # subseção OpenAlex: momentum de citações recentes (últimos 2 anos)
        sec_mom = ""
        if citacoes:
            mom = [
                c
                for c in citacoes
                if c.get("citacoes_total", 0) >= 20
                and c.get("citacoes_recentes_2a", 0) > 0
            ]
            mom.sort(key=lambda c: -c.get("citacoes_recentes_2a", 0))
            mr = ""
            for i, c in enumerate(mom[:12], 1):
                mr += (
                    f"<tr><td>{i}</td><td>{c['nome']}</td>"
                    f"<td style='color:var(--brand);font-weight:700;'>{c.get('citacoes_recentes_2a',0)}</td>"
                    f"<td>{c.get('momentum_pct',0)}%</td><td>{c.get('citacoes_total',0)}</td>"
                    f"<td>{c.get('h_index',0)}</td></tr>"
                )
            sec_mom = f"""
      <h3 style="font-family:var(--serif);font-size:20px;margin:28px 0 8px;">Em ascensão por citações (OpenAlex)</h3>
      <p class="desc">Outra leitura de ascensão: o <b>momentum de citações</b> — quem está sendo mais
      citado <b>agora</b>. "Citações recentes" = recebidas em 2024–2025; "momentum" = % do total que
      veio desses 2 anos (alto = aquecendo). Inclui quem tem ≥20 citações.</p>
      <table><thead><tr><th>#</th><th>Docente</th><th>Citações recentes (2a)</th><th>Momentum</th>
      <th>Citações total</th><th>h</th></tr></thead><tbody>{mr}</tbody></table>{sec_fwasc}"""
        # insight de ascensão: maior salto de FWCI + nº de docentes com as duas janelas
        _fwlist = [
            c
            for c in (citacoes or [])
            if c.get("fwci_antigo") is not None and c.get("fwci_recente") is not None
        ]
        _fwlist.sort(key=lambda c: -(c.get("fwci_delta") or 0))
        if _fwlist and _fwlist[0].get("fwci_delta", 0) > 0:
            _t = _fwlist[0]
            ins_asc = (
                f"<b>{_t['nome']}</b> saltou de FWCI {_t['fwci_antigo']:.2f} "
                f"({'abaixo' if _t['fwci_antigo'] < 1 else 'acima'} da média mundial) para "
                f"<b>{_t['fwci_recente']:.2f}</b> — os artigos recentes dele são citados "
                f"{_t['fwci_recente']:.1f}× a média da área. Ascensão de impacto <b>real</b>, "
                f"não só de volume ou de veículo. {len(_fwlist)} docentes têm as duas janelas "
                f"de FWCI comparáveis."
            )
        else:
            ins_asc = (
                "A ascensão de qualidade (estrato Qualis) e a de impacto (FWCI) nem sempre "
                "andam juntas: subir de veículo não garante ser mais citado. Cruze as duas tabelas "
                "para achar quem cresceu nas duas dimensões."
            )
        sec_asc = f"""
    <section class="section">
      <div class="eyebrow">Trajetória de crescimento</div>
      <h2>Pesquisadores em ascensão</h2>
      <p class="desc">Variação da <b>qualidade média</b> (peso Qualis por artigo) entre a janela
      <b>2016–2020</b> e <b>2021–2025</b>. Δ positivo = passou a publicar em estratos mais altos.
      Inclui apenas quem tem ≥2 artigos com Qualis em cada janela. "Artigos" = nº antigo→recente.</p>
      <table><thead><tr><th>#</th><th>Docente</th><th>Sub-área</th>
      <th>Nota 2016–20</th><th>Nota 2021–25</th><th>Δ qualidade</th><th>Artigos</th></tr></thead>
      <tbody>{ar}</tbody></table>
      {sec_mom}
      {_insight(ins_asc)}
    </section>"""

    # líderes por grande área
    # congressos (com Qualis CC)
    cdist = defaultdict(int)
    for k, v in payload.get("distribuicao_qualis_conf", {}).items():
        cdist["—" if k in ("-", "") else k] += v
    ctot = sum(cdist.values())
    conf_matched = payload["resumo"].get("congressos_com_qualis", 0)
    conf_bars = _bars(
        cdist, ["A1", "A2", "B1", "B2", "B3", "B4", "B5", "—"], _QUALIS_COLOR, ctot
    )
    crows = "".join(
        f"<tr><td>{c['evento'][:60]}</td><td>{_qbadge(c.get('qualis','—'), _QUALIS_COLOR)}</td>"
        f"<td>{c['publicacoes']}</td><td>{c['n_docentes']}</td></tr>"
        for c in payload["top_congressos"][:15]
    )
    sec_cong = f"""
    <section class="section">
      <div class="eyebrow">Eventos · impacto</div>
      <h2>Congressos e seu Qualis (CC)</h2>
      <p class="desc">Em Computação, conferências são canal primário de publicação. Aqui cada
      evento é casado por acrônimo/nome ao <b>Qualis de Conferências da Computação</b>
      (A1–B5). {conf_matched} dos {payload['resumo']['n_congressos_distintos']} eventos têm
      Qualis CC; o restante são congressos de Engenharia/Educação fora da lista de CC.
      Edições são fundidas (removidos ano e número).</p>
      <div class="card"><div class="card-head"><h3>Trabalhos por estrato Qualis CC</h3></div>
        {conf_bars}</div>
      <h3 style="font-family:var(--serif);font-size:20px;margin:26px 0 8px;">Principais congressos</h3>
      <table><thead><tr><th>Congresso / Evento</th><th>Qualis CC</th><th>Trabalhos</th><th>Docentes</th></tr></thead>
      <tbody>{crows}</tbody></table>
      {_insight(f"Dos trabalhos com Qualis CC, <b>{round((cdist.get('A1',0)+cdist.get('A2',0))/(ctot-cdist.get('—',0))*100) if (ctot-cdist.get('—',0)) else 0}%</b> "
                f"estão em <b>A1/A2</b> (topo das conferências de Computação). Mas apenas {conf_matched} dos "
                f"{payload['resumo']['n_congressos_distintos']} eventos têm Qualis CC — Engenharia e Educação "
                f"não têm lista própria, então o esforço dessas áreas em congressos fica invisível nesta régua. "
                f"Leia o estrato como piso, não teto.")}
    </section>"""

    # ranking combinado: revistas + congressos
    sec_comb = ""
    if ranking:
        comb = sorted(ranking, key=lambda x: -x.get("score_total", x["score"]))[:12]
        cb = ""
        for i, x in enumerate(comb, 1):
            cb += (
                f"<tr><td>{i}</td><td>{x['nome']}</td><td>{x['subarea']}</td>"
                f"<td>{x['score']}</td><td>{x.get('score_conf',0)}</td>"
                f"<td><b>{x.get('score_total', x['score'])}</b></td>"
                f"<td>{x['artigos_qualis']} art · {x.get('conf_qualis',0)} conf</td></tr>"
            )

        # por QUALIDADE combinada: nota média = score_total / itens c/ Qualis (revista+conf)
        def _comb_items(x):
            return x.get("artigos_qualis", 0) + x.get("conf_qualis", 0)

        def _comb_qual(x):
            it = _comb_items(x)
            return (x.get("score_total", x["score"]) / it) if it else 0.0

        elig = [x for x in ranking if _comb_items(x) >= MIN_ART]
        elig.sort(key=lambda x: -_comb_qual(x))
        cq = ""
        for i, x in enumerate(elig[:12], 1):
            it = _comb_items(x)
            cq += (
                f"<tr><td>{i}</td><td>{x['nome']}</td><td>{x['subarea']}</td>"
                f"<td><b>{_comb_qual(x):.0f}</b></td>"
                f"<td>{x.get('score_total', x['score'])}</td>"
                f"<td>{x['artigos_qualis']} art · {x.get('conf_qualis',0)} conf</td></tr>"
            )
        sec_comb = f"""
    <section class="section">
      <div class="eyebrow">Visão integrada</div>
      <h2>Impacto combinado — revistas + congressos</h2>
      <p class="desc">Score total = soma dos pesos Qualis dos <b>periódicos</b> (por ISSN) e dos
      <b>congressos</b> (Qualis CC, por acrônimo/nome). Reconhece quem publica forte em
      conferências — padrão da Computação — além dos periódicos.</p>
      <table><thead><tr><th>#</th><th>Docente</th><th>Sub-área</th><th>Score revistas</th>
      <th>Score congressos</th><th>Score total</th><th>Itens c/ Qualis</th></tr></thead>
      <tbody>{cb}</tbody></table>

      <h3 style="font-family:var(--serif);font-size:22px;margin:34px 0 8px;">Por qualidade (nota média combinada), não volume</h3>
      <p class="desc">Nota = score total ÷ itens com Qualis (periódicos + congressos): a média do
      estrato considerando os dois canais (100 = só A1). Destaca consistência de alto estrato,
      não volume. Inclui quem tem ≥{MIN_ART} itens com Qualis somando revistas e congressos.</p>
      <table><thead><tr><th>#</th><th>Docente</th><th>Sub-área</th><th>Nota combinada (0–100)</th>
      <th>Score total</th><th>Itens c/ Qualis</th></tr></thead>
      <tbody>{cq}</tbody></table>
      {_insight(f"O líder por <b>volume</b> (score total) é <b>{comb[0]['nome']}</b>; por <b>qualidade</b> "
                f"(nota média) é <b>{elig[0]['nome'] if elig else '—'}</b>. Quando os dois nomes diferem, "
                f"a régua que você escolhe muda quem aparece no topo: política de produtividade premia volume, "
                f"política de excelência premia consistência de alto estrato. Decida qual incentivo quer dar.")}
      <div class="note-line">Congressos casados apenas na área de Computação (lista Qualis-CC 2016);
      eventos de Engenharia/Educação não pontuam — ainda subestima docentes dessas áreas.
      Líderes por área/sub-área (incl. combinado) estão na seção "Líderes por área e sub-área".</div>
    </section>"""

    # ranking por CITAÇÕES (OpenAlex, casado por DOI)
    # quadrante Qualis (veículo) × citações (impacto real)
    sec_quad = ""
    if ranking and citacoes:
        import math as _math

        cit_by_name = {c["nome"]: c for c in citacoes}
        pts = []
        for rr in ranking:
            c = cit_by_name.get(rr["nome"])
            if not c:
                continue
            if rr.get("artigos_qualis", 0) < 3 or c.get("artigos_com_doi", 0) < 3:
                continue  # precisa de sinal nas duas métricas
            pts.append(
                {
                    "nome": rr["nome"],
                    "x": rr["qualidade"],
                    "y": c.get("citacoes_total", 0),
                    "h": c.get("h_index", 0),
                    "sub": rr.get("subarea", "—"),
                }
            )
        if pts:

            def _median(vals):
                s = sorted(vals)
                n = len(s)
                return (
                    (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)
                    if s
                    else 0
                )

            medx = round(_median([p["x"] for p in pts]), 1)
            medy = round(_median([p["y"] for p in pts]))
            maxy = max(p["y"] for p in pts) or 1
            W, Hh, M = 760, 460, 54

            def _px(x):
                return M + (x / 100) * (W - 2 * M)

            def _py(y):
                return Hh - M - (_math.sqrt(y) / _math.sqrt(maxy)) * (Hh - 2 * M)

            lx, ly = _px(medx), _py(medy)
            # quadrante de cada ponto
            for p in pts:
                hi_q, hi_c = p["x"] >= medx, p["y"] >= medy
                p["quad"] = (
                    "estrela"
                    if hi_q and hi_c
                    else (
                        "veiculo"
                        if hi_q and not hi_c
                        else "subvalorizado" if not hi_q and hi_c else "nicho"
                    )
                )
            QCOL = {
                "estrela": "var(--brand)",
                "veiculo": "var(--amber)",
                "subvalorizado": "var(--blue)",
                "nicho": "var(--muted)",
            }
            dots = "".join(
                f'<circle cx="{_px(p["x"]):.0f}" cy="{_py(p["y"]):.0f}" r="{4+_math.sqrt(p["h"]):.0f}" '
                f'fill="{QCOL[p["quad"]]}" fill-opacity="0.75"/>'
                for p in pts
            )
            # rótulos: os de maior citação e os "subvalorizados"
            labelset = (
                sorted(pts, key=lambda p: -p["y"])[:6]
                + [p for p in pts if p["quad"] == "subvalorizado"][:5]
            )
            labels = "".join(
                f'<text x="{_px(p["x"])+6:.0f}" y="{_py(p["y"])+3:.0f}" font-size="10" fill="#16241a">'
                f'{p["nome"].split()[0]} {p["nome"].split()[-1]}</text>'
                for p in {id(p): p for p in labelset}.values()
            )
            svg = f"""<svg viewBox="0 0 {W} {Hh}" style="width:100%;height:auto;font-family:var(--font);">
              <rect x="{lx:.0f}" y="{M}" width="{W-M-lx:.0f}" height="{ly-M:.0f}" fill="#0f7a40" opacity="0.05"/>
              <rect x="{M}" y="{ly:.0f}" width="{lx-M:.0f}" height="{Hh-M-ly:.0f}" fill="#71857a" opacity="0.05"/>
              <line x1="{lx:.0f}" y1="{M}" x2="{lx:.0f}" y2="{Hh-M}" stroke="var(--line2)" stroke-dasharray="4"/>
              <line x1="{M}" y1="{ly:.0f}" x2="{W-M}" y2="{ly:.0f}" stroke="var(--line2)" stroke-dasharray="4"/>
              <text x="{W-M}" y="{M-8}" text-anchor="end" font-size="11" fill="var(--brand)" font-weight="700">★ Estrelas (Qualis alto + citado)</text>
              <text x="{M}" y="{M-8}" font-size="11" fill="var(--blue)" font-weight="700">Subvalorizado (citado, Qualis menor)</text>
              <text x="{W-M}" y="{Hh-M+18}" text-anchor="end" font-size="11" fill="var(--amber)" font-weight="700">Veículo forte, pouco citado</text>
              <text x="{M}" y="{Hh-M+18}" font-size="11" fill="var(--muted)" font-weight="700">Nicho</text>
              <text x="{W/2:.0f}" y="{Hh-12}" text-anchor="middle" font-size="11" fill="var(--sub)">→ Qualis (nota média do veículo, 0–100) · mediana {medx}</text>
              <text x="14" y="{Hh/2:.0f}" font-size="11" fill="var(--sub)" transform="rotate(-90 14 {Hh/2:.0f})" text-anchor="middle">→ citações (impacto real, escala √) · mediana {medy}</text>
              {dots}{labels}</svg>"""

            def _qtab(quad, titulo, cor):
                items = sorted(
                    (p for p in pts if p["quad"] == quad), key=lambda p: -p["y"]
                )
                rows = "".join(
                    f"<tr><td>{p['nome']}</td><td>{p['x']:.0f}</td><td class='n'>{p['y']}</td><td>{p['h']}</td></tr>"
                    for p in items
                )
                return (
                    f'<div><h3 style="color:{cor};font-size:15px;margin:0 0 6px;">{titulo} ({sum(1 for p in pts if p["quad"]==quad)})</h3>'
                    f"<table><thead><tr><th>Docente</th><th>Qualis</th><th>Citações</th><th>h</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table></div>"
                )

            tabs = (
                _qtab("estrela", "★ Estrelas", "var(--brand)")
                + _qtab("subvalorizado", "Subvalorizado pelo Qualis", "var(--blue)")
                + _qtab("veiculo", "Veículo forte, pouco citado", "var(--amber)")
                + _qtab("nicho", "Nicho", "var(--muted)")
            )
            sec_quad = f"""
    <section class="section">
      <div class="eyebrow">Veículo vs impacto real</div>
      <h2>Quadrante Qualis × Citações</h2>
      <p class="desc">Cruza a <b>qualidade do veículo</b> (nota média Qualis 0–100, eixo X) com o
      <b>impacto real</b> (total de citações OpenAlex, escala √, eixo Y). A mediana de cada eixo divide
      os 4 quadrantes (posição <i>relativa ao grupo</i>, não juízo de mérito) —
      <b>{len(pts)} docentes</b> com sinal nas duas métricas (≥3 artigos Qualis e ≥3 com DOI).
      <b>★ Estrelas</b>: Qualis e citações ambos <b>acima</b> da mediana (bom veículo e muito citado).
      <b>Subvalorizado</b>: citações acima, Qualis abaixo (muito citado apesar de Qualis menor — o Qualis subestima).
      <b>Veículo forte, pouco citado</b>: Qualis acima, citações abaixo (publica em estrato alto mas sem eco).
      <b>Nicho</b>: Qualis e citações ambos <b>abaixo</b> da mediana (veículo modesto e pouca repercussão).
      Tamanho do ponto = h-index.</p>
      <div class="card">{svg}</div>
      <div class="grid2" style="margin-top:16px;">{tabs}</div>
      <div class="note-line">Qualis mede o <i>veículo</i> (a priori); citações medem a <i>repercussão</i>
      (a posteriori). Divergências apontam onde uma métrica sozinha engana.</div>
    </section>"""

    # avaliação por GRANDE ÁREA CNPq (agrega Qualis + citações + FWCI)
    sec_area = ""
    if ranking:
        cbn = {c["nome"]: c for c in (citacoes or [])}
        ag: dict[str, dict] = defaultdict(
            lambda: {
                "n": 0,
                "score": 0,
                "estrato_A": 0,
                "artigos": 0,
                "artigos_qualis": 0,
                "cit": 0,
                "fwci": [],
                "top10": 0,
                "com_doi": 0,
            }
        )
        for rr in ranking:
            ga = rr.get("area") or "—"
            if ga == "—":
                continue
            a = ag[ga]
            a["n"] += 1
            a["score"] += rr.get("score", 0)
            a["estrato_A"] += rr.get("estrato_A", 0)
            a["artigos"] += rr.get("artigos", 0)
            a["artigos_qualis"] += rr.get("artigos_qualis", 0)
            c = cbn.get(rr["nome"])
            if c:
                a["cit"] += c.get("citacoes_total", 0)
                a["top10"] += c.get("artigos_top10pct", 0)
                if c.get("encontrados_openalex", 0) >= 3 and c.get("fwci_mediana"):
                    a["fwci"].append(c["fwci_mediana"])
                if c.get("artigos_com_doi", 0):
                    a["com_doi"] += 1
        arows = ""
        for ga, a in sorted(ag.items(), key=lambda kv: -kv[1]["cit"]):
            fwci_m = round(sum(a["fwci"]) / len(a["fwci"]), 2) if a["fwci"] else 0
            cor = (
                "var(--brand)"
                if fwci_m >= 1.5
                else "var(--amber)" if fwci_m >= 1 else "var(--rose)"
            )
            qmean = (
                round(a["score"] / a["artigos_qualis"], 0) if a["artigos_qualis"] else 0
            )
            arows += (
                f"<tr><td>{ga}</td><td>{a['n']}</td>"
                f"<td style='color:{cor};font-weight:700;'>{fwci_m:.2f}</td>"
                f"<td class='n'>{a['cit']}</td><td>{a['top10']}</td>"
                f"<td>{a['estrato_A']}</td><td>{qmean:.0f}</td>"
                f"<td>{round(a['cit']/a['n']) if a['n'] else 0}</td></tr>"
            )
        _by_cit = sorted(ag.items(), key=lambda kv: -kv[1]["cit"])
        _by_fwci = sorted(
            (
                (g, (sum(a["fwci"]) / len(a["fwci"]) if a["fwci"] else 0))
                for g, a in ag.items()
            ),
            key=lambda kv: -kv[1],
        )
        _area_cit = _by_cit[0][0] if _by_cit else "—"
        _area_fw, _area_fwv = _by_fwci[0] if _by_fwci else ("—", 0)
        if _area_cit != _area_fw and _area_fwv > 0:
            ins_area = (
                f"<b>{_area_cit}</b> acumula mais citações brutas — mas é <b>{_area_fw}</b> que tem "
                f"o maior FWCI ({_area_fwv:.2f}), ou seja, publica acima da média mundial da própria "
                f"área. São coisas diferentes: volume de citação segue o tamanho e o ritmo da área; "
                f"FWCI mede se a produção bate o padrão internacional dela. Para comparar áreas entre "
                f"si, use o FWCI, nunca a citação bruta."
            )
        else:
            ins_area = (
                f"<b>{_area_fw}</b> lidera tanto em citações quanto em FWCI ({_area_fwv:.2f}). "
                f"Ainda assim, compare áreas pelo FWCI: citação bruta favorece áreas que publicam "
                f"e citam em ritmo mais intenso (ex.: Computação sobre Educação)."
            )
        sec_area = f"""
    <section class="section">
      <div class="eyebrow">Por grande área (CNPq)</div>
      <h2>Avaliação por área de conhecimento</h2>
      <p class="desc">Agrega as métricas por <b>grande área CNPq</b> (Engenharias, Ciências Exatas e
      da Terra…). Comparar <b>citação bruta</b> entre áreas é injusto (cada área cita em ritmo
      diferente) — por isso o <b>FWCI</b> (normalizado por área e ano) é a coluna que permite
      comparação justa: FWCI &gt; 1 = acima da média mundial da própria área. "Qualis méd." = nota
      média do veículo; "Cit/doc." = citações por docente.</p>
      <table><thead><tr><th>Grande área</th><th>Docentes</th><th>FWCI médio</th><th>Citações</th>
      <th>Top 10%</th><th>Artigos A</th><th>Qualis méd.</th><th>Cit/doc.</th></tr></thead>
      <tbody>{arows}</tbody></table>
      <div class="note-line">FWCI iguala a régua entre áreas; citações brutas e nº de artigos A
      favorecem áreas de publicação mais intensa (ex.: Computação). Líderes por área/sub-área estão
      na seção "Líderes por área e sub-área".</div>
      {_insight(ins_area)}
    </section>"""

    # quadrante produtividade (volume) × impacto (citações) — executivo
    sec_prod = ""
    if ranking and citacoes:
        import math as _m2

        cbn = {c["nome"]: c for c in citacoes}
        pp = []
        for rr in ranking:
            c = cbn.get(rr["nome"])
            if not c or c.get("artigos_com_doi", 0) < 3:
                continue
            pp.append(
                {
                    "nome": rr["nome"],
                    "x": rr.get("artigos", 0),
                    "y": c.get("citacoes_total", 0),
                    "h": c.get("h_index", 0),
                }
            )
        if pp:

            def _med(v):
                s = sorted(v)
                n = len(s)
                return (
                    (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)
                    if s
                    else 0
                )

            mx = round(_med([p["x"] for p in pp]), 1)
            my = round(_med([p["y"] for p in pp]))
            maxx = max(p["x"] for p in pp) or 1
            maxy = max(p["y"] for p in pp) or 1
            W, Hh, M = 760, 460, 54

            def _px(x):
                return M + (x / maxx) * (W - 2 * M)

            def _py(y):
                return Hh - M - (_m2.sqrt(y) / _m2.sqrt(maxy)) * (Hh - 2 * M)

            lx, ly = _px(mx), _py(my)
            for p in pp:
                hv, hc = p["x"] >= mx, p["y"] >= my
                p["q"] = (
                    "estrela"
                    if hv and hc
                    else (
                        "promessa"
                        if not hv and hc
                        else "prolifico" if hv and not hc else "nicho"
                    )
                )
            QC = {
                "estrela": "var(--brand)",
                "promessa": "var(--blue)",
                "prolifico": "var(--amber)",
                "nicho": "var(--muted)",
            }
            dots = "".join(
                f'<circle cx="{_px(p["x"]):.0f}" cy="{_py(p["y"]):.0f}" r="{4+_m2.sqrt(p["h"]):.0f}" '
                f'fill="{QC[p["q"]]}" fill-opacity="0.75"/>'
                for p in pp
            )
            lab = (
                sorted(pp, key=lambda p: -p["y"])[:6]
                + [p for p in pp if p["q"] == "promessa"][:5]
            )
            labels = "".join(
                f'<text x="{_px(p["x"])+6:.0f}" y="{_py(p["y"])+3:.0f}" font-size="10" fill="#16241a">'
                f'{p["nome"].split()[0]} {p["nome"].split()[-1]}</text>'
                for p in {id(p): p for p in lab}.values()
            )
            svg = f"""<svg viewBox="0 0 {W} {Hh}" style="width:100%;height:auto;font-family:var(--font);">
              <rect x="{lx:.0f}" y="{M}" width="{W-M-lx:.0f}" height="{ly-M:.0f}" fill="#0f7a40" opacity="0.05"/>
              <line x1="{lx:.0f}" y1="{M}" x2="{lx:.0f}" y2="{Hh-M}" stroke="var(--line2)" stroke-dasharray="4"/>
              <line x1="{M}" y1="{ly:.0f}" x2="{W-M}" y2="{ly:.0f}" stroke="var(--line2)" stroke-dasharray="4"/>
              <text x="{W-M}" y="{M-8}" text-anchor="end" font-size="11" fill="var(--brand)" font-weight="700">★ Estrelas (prolífico + citado)</text>
              <text x="{M}" y="{M-8}" font-size="11" fill="var(--blue)" font-weight="700">Promessas (poucos artigos, muito citados)</text>
              <text x="{W-M}" y="{Hh-M+18}" text-anchor="end" font-size="11" fill="var(--amber)" font-weight="700">Prolíficos pouco citados</text>
              <text x="{M}" y="{Hh-M+18}" font-size="11" fill="var(--muted)" font-weight="700">Nicho</text>
              <text x="{W/2:.0f}" y="{Hh-12}" text-anchor="middle" font-size="11" fill="var(--sub)">→ volume (nº de artigos) · mediana {mx}</text>
              <text x="14" y="{Hh/2:.0f}" font-size="11" fill="var(--sub)" transform="rotate(-90 14 {Hh/2:.0f})" text-anchor="middle">→ citações (impacto, escala √) · mediana {my}</text>
              {dots}{labels}</svg>"""

            def _ptab(q, titulo, cor):
                items = sorted((p for p in pp if p["q"] == q), key=lambda p: -p["y"])
                rows = "".join(
                    f"<tr><td>{p['nome']}</td><td>{p['x']}</td><td class='n'>{p['y']}</td><td>{p['h']}</td></tr>"
                    for p in items
                )
                return (
                    f'<div><h3 style="color:{cor};font-size:15px;margin:0 0 6px;">{titulo} ({sum(1 for p in pp if p["q"]==q)})</h3>'
                    f"<table><thead><tr><th>Docente</th><th>Artigos</th><th>Citações</th><th>h</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table></div>"
                )

            tabs = (
                _ptab("estrela", "★ Estrelas", "var(--brand)")
                + _ptab("promessa", "Promessas (alto impacto/artigo)", "var(--blue)")
                + _ptab("prolifico", "Prolíficos pouco citados", "var(--amber)")
                + _ptab("nicho", "Nicho", "var(--muted)")
            )
            sec_prod = f"""
    <section class="section">
      <div class="eyebrow">Mapa executivo</div>
      <h2>Quadrante Produtividade × Impacto</h2>
      <p class="desc">Volume (<b>nº de artigos</b>, eixo X) contra <b>impacto</b> (total de citações,
      escala √, eixo Y), para leitura de gestão em uma olhada. A mediana de cada eixo divide os 4
      quadrantes (posição <i>relativa ao grupo</i>, não juízo de mérito):
      <b>★ Estrelas</b>: artigos e citações ambos <b>acima</b> da mediana (muitos artigos e muito citados).
      <b>Promessas</b>: citações acima, artigos abaixo (poucos artigos mas alto impacto — potencial).
      <b>Prolíficos pouco citados</b>: artigos acima, citações abaixo (muito volume, pouca repercussão).
      <b>Nicho</b>: artigos e citações ambos <b>abaixo</b> da mediana (pouco volume e pouco impacto).
      Tamanho do ponto = h-index. {len(pp)} docentes com DOI.</p>
      <div class="card">{svg}</div>
      <div class="grid2" style="margin-top:16px;">{tabs}</div>
    </section>"""

    # ---- RESUMO ANALÍTICO (topo) ----
    sec_resumo = ""
    if ranking:
        cbn = {c["nome"]: c for c in (citacoes or [])}
        tot_cit = sum(c.get("citacoes_total", 0) for c in (citacoes or []))
        top_cit = max(
            (citacoes or []), key=lambda c: c.get("citacoes_total", 0), default={}
        )
        fwci_elig = [
            c
            for c in (citacoes or [])
            if c.get("encontrados_openalex", 0) >= 5 and c.get("fwci_mediana")
        ]
        top_fwci = max(fwci_elig, key=lambda c: c["fwci_mediana"], default={})
        top_qualis = ranking[0] if ranking else {}
        # FWCI médio por área (Engenharias x Exatas)
        af: dict[str, list] = defaultdict(list)
        for rr in ranking:
            c = cbn.get(rr["nome"])
            if (
                rr.get("area")
                and rr["area"] != "—"
                and c
                and c.get("encontrados_openalex", 0) >= 3
                and c.get("fwci_mediana")
            ):
                af[rr["area"]].append(c["fwci_mediana"])
        area_fwci = {k: round(sum(v) / len(v), 2) for k, v in af.items() if v}
        area_rank = sorted(area_fwci.items(), key=lambda kv: -kv[1])
        # subvalorizado: maior FWCI fora dos veículos de Qualis alto
        med_q = None
        qs = sorted(
            [rr["qualidade"] for rr in ranking if rr.get("artigos_qualis", 0) >= 3]
        )
        if qs:
            med_q = qs[len(qs) // 2]
        subval = None
        if med_q is not None:
            cand = [
                (rr["nome"], cbn.get(rr["nome"], {}).get("fwci_mediana", 0))
                for rr in ranking
                if rr.get("qualidade", 0) < med_q
                and cbn.get(rr["nome"], {}).get("encontrados_openalex", 0) >= 5
            ]
            subval = max(cand, key=lambda x: x[1], default=None)
        n_doi = sum(1 for c in (citacoes or []) if c.get("artigos_com_doi", 0))
        eng = area_fwci.get("Engenharias")
        exa = area_fwci.get("Ciências Exatas e da Terra")

        n_doc = len(ranking)
        n_fwci = sum(
            1 for c in (citacoes or []) if c.get("encontrados_openalex", 0) >= FWCI_MIN
        )
        # área de maior e menor FWCI (para a tese)
        if eng and exa:
            if exa >= eng:
                an, af1, bn, bf = "Ciências Exatas e da Terra", exa, "Engenharias", eng
            else:
                an, af1, bn, bf = "Engenharias", eng, "Ciências Exatas e da Terra", exa
        else:
            an = bn = ""
            af1 = bf = 0

        # ---- faixa de estatísticas (stat band) ----
        def _stat(num, lab, sub):
            return (
                f'<div class="rz-stat"><div class="rz-n">{num}</div>'
                f'<div class="rz-l">{lab}</div><div class="rz-s">{sub}</div></div>'
            )

        stats = (
            _stat(
                r["n_artigos"],
                "artigos em periódicos",
                f"+{r['n_trabalhos_congresso']} em congressos",
            )
            + _stat(
                f"{round(q1q2/tot_art*100) if tot_art else 0}%",
                "em Q1+Q2 (SJR)",
                f"{q1q2} de {tot_art} artigos",
            )
            + _stat(
                f"{tot_cit:,}".replace(",", "."),
                "citações (OpenAlex)",
                f"{n_doi} docentes com DOI",
            )
            + _stat(
                f"{(area_rank[0][1] if area_rank else 0):.1f}",
                "FWCI — área líder",
                (area_rank[0][0] if area_rank else "—"),
            )
        )

        # ---- cards de insight (paralelos, sem numeração) ----
        ins = []
        if an:
            ins.append(
                (
                    "Por área",
                    "var(--brand)",
                    f"<b>{an}</b> lidera o <b>impacto relativo</b> (FWCI {af1:.2f}); "
                    f"{bn} vence no volume bruto (FWCI {bf:.2f}). A citação crua favorece quem "
                    f"publica mais — o FWCI iguala a régua entre áreas.",
                )
            )
        if top_cit and top_fwci and top_cit.get("nome") != top_fwci.get("nome"):
            ins.append(
                (
                    "Quantidade × qualidade",
                    "var(--blue)",
                    f"Mais <b>citado</b>: {top_cit['nome']} ({top_cit.get('citacoes_total',0)}). "
                    f"Maior <b>impacto</b> (FWCI): {top_fwci['nome']} "
                    f"({top_fwci['fwci_mediana']:.1f}× a média mundial). Volume e impacto não andam juntos.",
                )
            )
        if subval and subval[1] >= 1.5:
            ins.append(
                (
                    "Subvalorizado pelo Qualis",
                    "var(--amber)",
                    f"<b>{subval[0]}</b> tem FWCI {subval[1]:.1f} publicando em veículos de Qualis "
                    f"<b>abaixo da mediana</b> — impacto real que a classificação do periódico não vê.",
                )
            )
        ins.append(
            (
                "Computação",
                "var(--rose,#b5455f)",
                "Em CC a <b>conferência</b> é canal primário. Incluir o Qualis de eventos "
                "reordena o ranking — docentes de Computação sobem no score combinado.",
            )
        )
        cards = "".join(
            f'<div class="rz-card" style="--c:{cor};"><span class="rz-tag">{tag}</span>'
            f"<p>{txt}</p></div>"
            for tag, cor, txt in ins
        )

        sec_resumo = f"""
    <section class="section rz">
      <style>
      .rz{{border:1px solid var(--line);border-left:5px solid var(--brand);
        background:linear-gradient(135deg,var(--brand-l,#e7f4ec) 0%,#fff 55%);padding:34px 32px;}}
      .rz .eyebrow{{color:var(--brand-d,#0a5c30);}}
      .rz .thesis{{font-family:var(--serif);font-size:clamp(26px,3.6vw,40px);line-height:1.12;
        font-weight:700;color:var(--ink);max-width:20ch;margin:6px 0 4px;letter-spacing:-.01em;}}
      .rz .thesis em{{font-style:normal;color:var(--brand-d,#0a5c30);
        background:linear-gradient(transparent 62%,rgba(15,122,64,.18) 0);}}
      .rz .lede{{font-size:16px;color:var(--ink2,#3c4f42);max-width:62ch;margin:0 0 26px;}}
      .rz-stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;border-top:1px solid var(--line);
        border-bottom:1px solid var(--line);margin:0 0 26px;}}
      .rz-stat{{padding:18px 18px 16px;border-left:1px solid var(--line);}}
      .rz-stat:first-child{{border-left:none;padding-left:0;}}
      .rz-n{{font-family:var(--serif);font-size:34px;font-weight:800;color:var(--brand-d,#0a5c30);line-height:1;}}
      .rz-l{{font-size:13px;font-weight:600;color:var(--ink);margin-top:7px;}}
      .rz-s{{font-size:11.5px;color:var(--muted,#71857a);margin-top:2px;}}
      .rz-cards{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
      .rz-card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px;
        border-top:3px solid var(--c);box-shadow:var(--shadow);}}
      .rz-tag{{display:inline-block;font-size:10.5px;font-weight:800;letter-spacing:.09em;
        text-transform:uppercase;color:var(--c);margin-bottom:7px;}}
      .rz-card p{{font-size:13.5px;line-height:1.6;color:var(--ink2,#3c4f42);margin:0;}}
      .rz-verdict{{margin-top:24px;background:linear-gradient(135deg,var(--brand-d,#0a5c30),var(--brand));
        color:#fff;border-radius:14px;padding:22px 26px;}}
      .rz-verdict b{{color:#fff;}}
      .rz-verdict .vk{{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
        opacity:.85;margin-bottom:8px;}}
      .rz-verdict .vt{{font-size:16px;line-height:1.6;}}
      .rz-cov{{font-size:12px;opacity:.9;margin-top:12px;border-top:1px solid rgba(255,255,255,.25);padding-top:10px;}}
      @media(max-width:760px){{.rz-stats,.rz-cards{{grid-template-columns:1fr 1fr;}}
        .rz-stat{{border-left:none;padding-left:0;}}}}
      </style>
      <div class="eyebrow">Resumo analítico</div>
      <h2 class="thesis">Onde o campus publica <em>não é</em> onde ele repercute.</h2>
      <p class="lede">{round(q1q2/tot_art*100) if tot_art else 0}% da produção está em periódicos Q1+Q2,
      mas o impacto real (citações, FWCI) está concentrado em poucos docentes — e nem sempre nos
      veículos de Qualis mais alto. Esta página separa as duas coisas: <b>qualidade do veículo</b>
      (SJR/Qualis) e <b>repercussão</b> (citações/FWCI por DOI).</p>
      <div class="rz-stats">{stats}</div>
      <div class="rz-cards">{cards}</div>
      <div class="rz-verdict">
        <div class="vk">Como ler</div>
        <div class="vt">Qualis e SJR medem o <b>veículo</b> (antes de publicar); citações e FWCI medem
        a <b>repercussão</b> (depois). Onde divergem estão os <b>achados</b> — estrelas, subvalorizados
        e veículos sem eco, mapeados nos quadrantes.</div>
        <div class="rz-cov"><b>Cobertura:</b> citações/FWCI por DOI — {n_doi} de {n_doc} docentes têm
        DOI no Lattes; {n_fwci} têm FWCI confiável (≥{FWCI_MIN} artigos). Congressos com Qualis só em
        Computação. <b>Versão preliminar — métricas em validação.</b></div>
      </div>
    </section>"""

    # Metodologia + fontes
    q_total = sum(payload["distribuicao_qualis"].values()) if qualis_applied else 0
    sec_metodo = f"""
    <section class="section">
      <div class="eyebrow">Metodologia e fontes</div>
      <h2>Como esta análise foi feita</h2>
      <div class="findings">
        <div class="finding"><span class="tag rs">Coleta</span>
          <h3>1. Veículos a partir do Lattes</h3>
          <p>As revistas e congressos vêm dos currículos <b>Lattes</b> dos{
          (' ' + str(len(ranking))) if ranking else ''} docentes do campus (seções
          <i>artigos em periódicos</i> e <i>trabalhos completos em congressos</i>).
          Cada artigo traz o <b>ISSN</b> do periódico —
          a chave de cruzamento com as bases de impacto. Edições de um mesmo congresso são
          unificadas removendo ano e número de edição (15th, XLIV, II…).</p>
        </div>
        <div class="finding"><span class="tag eq">Impacto internacional</span>
          <h3>2. SJR (SCImago) por ISSN</h3>
          <p>Cada revista é casada por <b>ISSN</b> com a base <b>SCImago Journal Rank (SJR)</b>,
          métrica internacional derivada do Scopus. Dela vêm o <b>quartil Q1–Q4</b> (melhor
          quartil do periódico), o índice SJR e o H-index. Revistas fora do Scopus ficam "sem SJR".</p>
        </div>
        <div class="finding"><span class="tag sp">Classificação nacional</span>
          <h3>3. Qualis CAPES por ISSN</h3>
          <p>O mesmo <b>ISSN</b> é casado com a tabela <b>Qualis Periódicos da CAPES
          (quadriênio 2017–2020)</b>. Como o Qualis varia por área de avaliação, usamos o
          <b>melhor estrato</b> do periódico entre todas as áreas (A1 é o topo). Por isso o
          Qualis cobre mais revistas que o SJR — inclui periódicos nacionais não indexados no Scopus.</p>
        </div>
        <div class="finding"><span class="tag sp">Congressos (Computação)</span>
          <h3>4. Qualis de Conferências CC</h3>
          <p>Como em Computação a conferência é canal primário, casamos cada congresso (por
          <b>acrônimo</b> ou nome) ao <b>Qualis de Conferências da Computação</b> (lista CC 2016,
          A1–B5). É o único ranking de eventos disponível — a CAPES descontinuou o Qualis
          Eventos geral em 2019. Cobre os eventos de CC; os de Engenharia/Educação ficam de fora.</p>
        </div>
        <div class="finding"><span class="tag eq">Ranking de docentes</span>
          <h3>5. Score de impacto</h3>
          <p>O score de cada docente é a <b>soma dos pesos Qualis</b> (A1=100, A2=85, A3=70,
          A4=55, B1=40, B2=30, B3=20, B4=10, C=3). O <b>score total</b> soma periódicos +
          congressos CC. A divisão por sub-área usa o campo "área" do Lattes.</p>
        </div>
        <div class="finding"><span class="tag rs">Citações reais</span>
          <h3>6. Citações via OpenAlex (DOI)</h3>
          <p>Além do Qualis (qualidade do <i>veículo</i>), medimos o <b>impacto real</b>: as
          citações de cada artigo no <b>OpenAlex</b>, casadas pelo <b>DOI</b> do Lattes (1:1).
          Daí saem <b>citações totais, h-index e i10</b> por docente, sem depender de busca por
          nome (que erra com homônimos).</p>
        </div>
      </div>
      <div class="note" style="border-color:var(--amber);margin-top:6px;">
        <b>Por que não Google Scholar?</b> O Google Scholar tem as citações mais abrangentes, mas
        <b>não foi possível usá-lo</b>: o acesso automatizado é bloqueado (CAPTCHA e bloqueio de IP),
        sem API pública. Por isso as citações vêm do <b>OpenAlex</b>, base aberta e estável, casada por
        <b>DOI</b> (1:1, sem ambiguidade de homônimo). Os números de citação tendem a ser <b>menores</b>
        que os do Scholar, mas são consistentes e comparáveis entre docentes.
      </div>
      <div class="note-line">
        <b>Limitações:</b> o Qualis de conferências cobre só Computação (lista CC 2016) — congressos
        de Engenharia/Educação não pontuam, subestimando esses docentes. Casamento de congressos é
        por nome/acrônimo (sem ISSN), sujeito a erro. Artigos em periódicos fora do Scopus não
        recebem quartil SJR. O "melhor estrato entre áreas" é leitura otimista do Qualis de periódicos.
      </div>
      <div class="card" style="margin-top:18px;">
        <h3>Fontes dos dados</h3>
        <table>
          <thead><tr><th>Dado</th><th>Fonte</th><th>Link</th></tr></thead>
          <tbody>
            <tr><td>Veículos de publicação (revistas, congressos, ISSN)</td>
              <td>Plataforma Lattes (CNPq)</td>
              <td><a href="http://lattes.cnpq.br/">lattes.cnpq.br</a></td></tr>
            <tr><td>Impacto internacional (quartil SJR, índice, H-index)</td>
              <td>SCImago Journal &amp; Country Rank</td>
              <td><a href="https://www.scimagojr.com/journalrank.php">scimagojr.com</a></td></tr>
            <tr><td>Qualis Periódicos 2017–2020 (estrato por ISSN)</td>
              <td>CAPES / Plataforma Sucupira</td>
              <td><a href="https://sucupira.capes.gov.br/">sucupira.capes.gov.br</a></td></tr>
            <tr><td>Qualis de Conferências CC (estrato por acrônimo/nome)</td>
              <td>CAPES (lista CC 2016) · portal UFMT</td>
              <td><a href="https://qualis.ic.ufmt.br/">qualis.ic.ufmt.br</a></td></tr>
            <tr><td>Citações, h-index, i10 (por DOI)</td>
              <td>OpenAlex</td>
              <td><a href="https://openalex.org/">openalex.org</a></td></tr>
          </tbody>
        </table>
      </div>
    </section>"""

    # ===================================================================
    # SEÇÕES CONSOLIDADAS (A/B/C) — substituem rankings/líderes/quadrantes soltos
    # ===================================================================
    cbn = {c["nome"]: c for c in (citacoes or [])}
    n_doc = len(ranking) if ranking else 0
    n_doi = sum(1 for c in (citacoes or []) if c.get("artigos_com_doi", 0))
    n_fwci = sum(
        1 for c in (citacoes or []) if c.get("encontrados_openalex", 0) >= FWCI_MIN
    )
    cov = (
        f'<div class="note" style="border-color:var(--amber);"><b>Cobertura:</b> citações e FWCI '
        f"vêm de DOI — <b>{n_doi} de {n_doc}</b> docentes têm DOI no Lattes e só <b>{n_fwci}</b> "
        f"têm ≥{FWCI_MIN} artigos no OpenAlex (FWCI confiável). Quem não tem DOI aparece sem citação; "
        f"não significa ausência de impacto.</div>"
    )

    # ---- A. Ranking-mestre (1 tabela: Qualis, nota, citações, FWCI, h) ----
    sec_master = ""
    if ranking:
        # FWCI só é confiável com >= FWCI_MIN artigos; abaixo disso não entra no ranking
        def _fwci_ok(rr):
            c = cbn.get(rr["nome"], {})
            return (
                c.get("fwci_mediana")
                if c.get("encontrados_openalex", 0) >= FWCI_MIN
                else None
            )

        # ordena por qualidade + impacto: FWCI (confiável) desc, depois nota Qualis desc
        master_rows = sorted(
            ranking, key=lambda rr: (-(_fwci_ok(rr) or 0), -rr.get("qualidade", 0))
        )
        mrows = ""
        for rr in master_rows:
            c = cbn.get(rr["nome"], {})
            fw = _fwci_ok(rr)
            fwtxt = f"{fw:.2f}" if fw else "—"
            # g (Egghe), m (h/idade), citações/artigo, citações fracionadas (autoria)
            g_v = c.get("g_index", 0) if c else 0
            m_v = c.get("m_index", 0) if c else 0
            cpp_v = c.get("citacoes_por_artigo", 0) if c else 0
            cf_v = c.get("citacoes_fracionadas", 0) if c else 0
            g_t = str(g_v) if (c and c.get("g_index")) else "—"
            m_t = f"{m_v:.2f}" if (c and m_v) else "—"
            cpp_t = f"{cpp_v:.1f}" if (c and cpp_v) else "—"
            cf_t = f"{cf_v:.1f}" if (c and cf_v) else "—"
            mrows += (
                f"<tr>"
                f'<td>{rr["nome"]}</td><td>{rr.get("area","—")}</td>'
                f'<td data-v="{rr.get("score",0)}">{rr.get("score",0)}</td>'
                f'<td data-v="{rr.get("qualidade",0)}">{rr.get("qualidade",0):.0f}</td>'
                f'<td data-v="{c.get("citacoes_total",0)}">{c.get("citacoes_total","—") if c else "—"}</td>'
                f'<td data-v="{fw or 0}">{fwtxt}</td>'
                f'<td data-v="{c.get("h_index",0)}">{c.get("h_index","—") if c else "—"}</td>'
                f'<td data-v="{g_v}">{g_t}</td>'
                f'<td data-v="{m_v}">{m_t}</td>'
                f'<td data-v="{cpp_v}">{cpp_t}</td>'
                f'<td data-v="{cf_v}">{cf_t}</td>'
                f'<td data-v="{rr.get("artigos_qualis",0)}">{rr.get("artigos_qualis",0)}</td>'
                f"</tr>"
            )
        # "Achados": poucos artigos (< FWCI_MIN) mas com impacto pontual alto
        achados = []
        for c in citacoes or []:
            n_f = c.get("encontrados_openalex", 0)
            if 1 <= n_f < FWCI_MIN and (c.get("fwci_mediana") or 0) >= 1.5:
                arts = c.get("top_artigos") or []
                star = max(arts, key=lambda a: (a.get("fwci") or 0), default={})
                achados.append(
                    {
                        "nome": c["nome"],
                        "n": n_f,
                        "fwci": c.get("fwci_mediana", 0),
                        "cit": c.get("citacoes_total", 0),
                        "star": star,
                    }
                )
        achados.sort(key=lambda x: -(x["star"].get("fwci") or 0))

        def _alink(star):
            tit = (star.get("titulo") or "")[:60]
            doi = star.get("doi")
            t = (
                f'<a href="https://doi.org/{doi}" target="_blank" rel="noopener">{tit}</a>'
                if doi
                else tit
            )
            return (
                f"{t} <span style='color:var(--muted);'>"
                f"({star.get('ano','')}, {star.get('citacoes',0)} cit)</span>"
            )

        arows = "".join(
            f"<tr><td>{x['nome']}</td><td>{x['n']}</td>"
            f"<td style='color:var(--blue);font-weight:700;'>{(x['star'].get('fwci') or 0):.1f}</td>"
            f"<td>{x['cit']}</td>"
            f"<td>{_alink(x['star'])}</td></tr>"
            for x in achados[:12]
        )
        sec_achados = (
            f"""
      <h3 style="font-family:var(--serif);font-size:20px;margin:28px 0 8px;">Achados — alto impacto, poucos artigos</h3>
      <p class="desc">Docentes com <b>menos de {FWCI_MIN} artigos</b> no OpenAlex (fora do ranking por
      baixa amostra), mas com um <b>artigo de impacto pontual muito alto</b> (FWCI elevado). São casos
      a olhar: potencial subexplorado ou um trabalho de destaque isolado. "FWCI" aqui é do artigo-destaque.</p>
      <table><thead><tr><th>Docente</th><th>Artigos</th><th>FWCI destaque</th><th>Citações</th>
      <th>Artigo de maior impacto</th></tr></thead><tbody>{arows}</tbody></table>"""
            if achados
            else ""
        )
        sec_master = f"""
    <section class="section">
      <div class="eyebrow">Ranking de docentes</div>
      <h2>Tabela-mestre de impacto</h2>
      <p class="desc">Uma tabela com as métricas que antes estavam espalhadas. <b>Score Qualis</b>
      = volume × qualidade do veículo (A1=100…C=3). <b>Nota Qualis</b> = média por artigo (qualidade
      pura). <b>Citações</b>, <b>h</b>, <b>g</b>, <b>m</b> = impacto real (OpenAlex, por DOI). <b>FWCI</b>
      = impacto normalizado por área (1 = média mundial). <b>g</b> (Egghe) dá peso aos trabalhos muito
      citados; <b>m</b> = h ÷ idade acadêmica (corrige antiguidade); <b>Cit/art</b> = intensidade média;
      <b>Cit. frac.</b> = citações divididas pelo nº de autores (corrige hipercoautoria). <b>Ordenada por
      qualidade + impacto</b> (FWCI, depois nota Qualis); clique em qualquer cabeçalho para reordenar.
      Fórmulas e referências no fim da página.</p>
      {cov}
      <div style="overflow-x:auto;"><table class="sortable"><thead><tr>
        <th>Docente</th><th>Área</th><th data-sort="num">Score Qualis</th><th data-sort="num">Nota</th>
        <th data-sort="num">Citações</th><th data-sort="num">FWCI</th><th data-sort="num">h</th>
        <th data-sort="num">g</th><th data-sort="num">m</th><th data-sort="num">Cit/art</th>
        <th data-sort="num">Cit. frac.</th>
        <th data-sort="num">Artigos Qualis</th></tr></thead><tbody>{mrows}</tbody></table></div>
      <div class="note-line">"Artigos Qualis" = artigos do docente com estrato (registros por docente,
      não deduplicados entre coautores — difere do total de artigos distintos do campus).</div>
      {_insight((lambda topf, topq: (f"<b>{topf['nome']}</b> lidera por impacto (FWCI {(_fwci_ok(topf) or 0):.2f}), "
                f"enquanto <b>{topq['nome']}</b> lidera por score Qualis ({topq.get('score',0)}). "
                f"Topo de veículo e topo de impacto são pessoas diferentes — confirma a tese do relatório: "
                f"onde o campus publica não é necessariamente onde ele repercute. Reordene pela coluna que "
                f"importa para a decisão em questão.") if topf and topq and topf['nome'] != topq['nome']
                else f"Reordene a tabela pela coluna que importa: score Qualis premia veículo, FWCI premia "
                f"impacto real. As duas leituras raramente apontam para os mesmos nomes.")(
                master_rows[0] if master_rows else None,
                max(ranking, key=lambda r: r.get('score', 0)) if ranking else None))}
      {sec_achados}
    </section>"""

    # ---- C. Mapas estratégicos (3 quadrantes juntos) ----
    sec_maps = f"""
    <section class="section">
      <div class="eyebrow">Mapas estratégicos</div>
      <h2>Quadrantes de posicionamento</h2>
      <p class="desc">Três cruzamentos para leitura rápida de gestão: veículo × impacto real
      (citações e FWCI) e produtividade × impacto. Estrelas, subvalorizados, veículos sem eco.</p>
      {_quad_qualis_fwci(ranking, citacoes)}
      {_insight((f"O quadrante <b>subvalorizado</b> é o mais acionável: <b>{subval[0]}</b> tem FWCI "
                f"{subval[1]:.1f} (citado acima da média mundial) publicando em veículos de Qualis baixo — "
                f"apoiar a submissão a periódicos de estrato A converteria impacto já existente em "
                f"reconhecimento formal. No oposto, "
                if subval and subval[1] >= 1.5 else "Leia os quadrantes por ação: ")
                + "“veículos sem eco” (alto Qualis, baixa citação) sinalizam prestígio do veículo que "
                "ainda não virou repercussão. Cada quadrante sugere uma intervenção diferente.")}
    </section>{sec_quad}{sec_prod}"""

    # ---- B. Líderes por área e sub-área (Qualis + FWCI num só lugar) ----
    sec_leaders = ""
    if ranking:
        bestq, bestf = {}, {}
        for rr in ranking:
            ga = rr.get("area") or "—"
            if ga == "—":
                continue
            if ga not in bestq or rr.get("score", 0) > bestq[ga].get("score", 0):
                bestq[ga] = rr
        larea = "".join(
            f"<tr><td>{ga}</td><td>{b['nome']}</td><td>{b.get('score',0)}</td>"
            f"<td>{b.get('estrato_A',0)}</td></tr>"
            for ga, b in sorted(bestq.items(), key=lambda kv: -kv[1].get("score", 0))
            if b.get("score", 0) > 0
        )
        sec_leaders = f"""
    <section class="section">
      <div class="eyebrow">Liderança</div>
      <h2>Líderes por área e sub-área</h2>
      <p class="desc">Quem lidera cada área por <b>volume×qualidade (Qualis)</b> e por
      <b>impacto normalizado (FWCI)</b> — as duas leituras lado a lado.</p>
      <div class="grid2">
        <div><h3 style="font-size:15px;">Por grande área · Score Qualis</h3>
          <table><thead><tr><th>Área</th><th>Líder</th><th>Score</th><th>A1–A4</th></tr></thead>
          <tbody>{larea}</tbody></table></div>
        <div><h3 style="font-size:15px;">Por grande área · FWCI (impacto)</h3>
          <table><thead><tr><th>Área</th><th>Líder</th><th>FWCI</th><th>Top10%</th><th>Cit</th><th>h</th></tr></thead>
          <tbody>{_lider_fwci_rows(ranking, citacoes, "area", FWCI_MIN)}</tbody></table></div>
      </div>
      <h3 style="font-family:var(--serif);font-size:20px;margin:24px 0 8px;">Por sub-área · FWCI</h3>
      <table><thead><tr><th>Sub-área</th><th>Líder por FWCI</th><th>FWCI</th><th>Top10%</th><th>Cit</th><th>h</th></tr></thead>
      <tbody>{_lider_fwci_rows(ranking, citacoes, "subarea", FWCI_MIN_SUB)}</tbody></table>
      {_insight("Liderar por <b>Qualis</b> (publicar em bons veículos) e liderar por <b>FWCI</b> "
                "(ser citado acima da média da área) raramente recai na mesma pessoa. Quem aparece nas "
                "<b>duas</b> colunas da mesma área é a aposta mais segura para coordenar ou representar "
                "a área; quem só aparece no FWCI é talento de impacto que o sistema de veículos ainda "
                "não capturou.")}
    </section>"""

    # ---- Fórmulas e referências (artigos seminais) ----
    _refs = [
        (
            "h-index",
            "núcleo de produção citada — combina volume e impacto",
            "maior <i>h</i> tal que <i>h</i> artigos tenham ≥ <i>h</i> citações cada",
            "Hirsch, J. E. (2005). <i>An index to quantify an individual's scientific research output.</i> PNAS 102(46):16569–16572.",
            "https://doi.org/10.1073/pnas.0507655102",
        ),
        (
            "g-index",
            "concentração de impacto — peso extra aos trabalhos muito citados",
            "maior <i>g</i> tal que os <i>g</i> artigos mais citados somem ≥ <i>g</i>² citações",
            "Egghe, L. (2006). <i>Theory and practise of the g-index.</i> Scientometrics 69(1):131–152.",
            "https://doi.org/10.1007/s11192-006-0144-7",
        ),
        (
            "m-index (m-quotient)",
            "h ajustado pela idade acadêmica (reduz viés de antiguidade)",
            "<i>m</i> = h ÷ anos desde a 1ª publicação",
            "Hirsch, J. E. (2005). PNAS 102(46):16569–16572 (proposto no mesmo artigo do h).",
            "https://doi.org/10.1073/pnas.0507655102",
        ),
        (
            "i10-index",
            "nº de artigos com pelo menos 10 citações (leitura rápida)",
            "i10 = contagem(citações ≥ 10)",
            "Google Scholar Metrics — definição operacional do perfil público.",
            "https://scholar.google.com/intl/pt-BR/scholar/metrics.html",
        ),
        (
            "Citações",
            "impacto bruto na base escolhida (OpenAlex, casado por DOI)",
            "C = Σ citações dos artigos do docente",
            "Waltman, L. (2016). <i>A review of the literature on citation impact indicators.</i> Journal of Informetrics 10(2):365–391.",
            "https://doi.org/10.1016/j.joi.2016.02.007",
        ),
        (
            "Citações por artigo",
            "intensidade média — reportada com a mediana (robusta a outliers)",
            "CPP = C ÷ nº de artigos; mediana das citações ao lado",
            "Clarivate — Essential Science Indicators (cites per paper).",
            "https://esi.clarivate.com/",
        ),
        (
            "FWCI (impacto normalizado por campo)",
            "compara áreas com densidades de citação diferentes (1 = média mundial)",
            "FWCI = citações observadas ÷ citações esperadas (mesmo campo, ano e tipo); agregamos pela mediana por docente",
            "Waltman, van Eck, van Leeuwen, Visser & van Raan (2011). <i>Towards a new crown indicator.</i> Scientometrics 87:467–481.",
            "https://doi.org/10.1007/s11192-011-0354-5",
        ),
        (
            "Percentil de citação (top 10% / 1%)",
            "posição relativa; robusto à assimetria das distribuições de citação",
            "% de artigos do mesmo campo/ano citados menos; top 10% = percentil ≥ 90 (OpenAlex)",
            "Bornmann, Leydesdorff & Mutz (2013). <i>The use of percentiles and percentile rank classes…</i> Journal of Informetrics 7(1):158–165.",
            "https://doi.org/10.1016/j.joi.2012.11.005",
        ),
        (
            "Crédito fracionado por autoria",
            "corrige a hipercoautoria — divide o crédito entre os coautores",
            "produção = Σ 1/n_autores; impacto = Σ citações/n_autores (n_autores via OpenAlex)",
            "Waltman & van Eck (2015). <i>Field-normalized citation impact indicators and the choice of an appropriate counting method.</i> Journal of Informetrics 9(4):872–894.",
            "https://doi.org/10.1016/j.joi.2015.01.006",
        ),
        (
            "Momentum / velocidade de citação",
            "tração recente — sinal de impacto crescente, não medida final",
            "citações recebidas em 2024–2025; momentum = % do total vindo desses 2 anos",
            "Indicadores de contagem recente (OpenAlex counts_by_year); cf. Semantic Scholar Citation Velocity.",
            "https://docs.openalex.org/api-entities/works/work-object#counts_by_year",
        ),
        (
            "Painel multi-indicador",
            "nenhuma métrica isolada basta — usar várias em conjunto",
            "tabela-mestre combina Qualis, citações, FWCI, h, g, m e fracionado",
            "Ioannidis, Baas, Klavans & Boyack (2019). <i>A standardized citation metrics author database…</i> PLOS Biology 17(8):e3000384.",
            "https://doi.org/10.1371/journal.pbio.3000384",
        ),
    ]
    _refrows = "".join(
        f"<tr><td><b>{nome}</b></td><td>{mede}</td><td>{formula}</td>"
        f"<td>{ref} <a href='{url}' target='_blank' rel='noopener'>↗</a></td></tr>"
        for nome, mede, formula, ref, url in _refs
    )

    # cards didáticos: fórmula + exemplo resolvido + como ler, por indicador
    _C = (
        "background:var(--brand-l,#e7f4ec);padding:1px 6px;border-radius:5px;"
        "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;"
    )

    def _card(tag, cls, nome, corpo):
        return (
            f'<div class="finding"><span class="tag {cls}">{tag}</span>'
            f"<h3>{nome}</h3><p>{corpo}</p></div>"
        )

    # — indicadores do veículo (a priori: antes de qualquer citação) —
    _veic = "".join(
        [
            _card(
                "Veículo",
                "eq",
                "Quartil SJR (SCImago)",
                f"Quartil do <b>periódico</b> na sua área no SCImago (deriva do Scopus). "
                f"<b>Q1</b> = 25% de maior impacto da área; <b>Q4</b> = 25% menor. "
                f"<b>Leitura:</b> mede a qualidade do <i>veículo</i>, não do artigo; revistas "
                f'fora do Scopus ficam "sem SJR".',
            ),
            _card(
                "Veículo",
                "sp",
                "Estrato Qualis CAPES",
                f"Classificação do periódico pela CAPES (A1 topo → C). Usamos o <b>melhor estrato</b> "
                f"entre as áreas de avaliação. <b>Leitura:</b> reconhecimento no sistema nacional; "
                f"cobre revistas brasileiras que o SJR não indexa.",
            ),
            _card(
                "Veículo",
                "eq",
                "Score &amp; Nota Qualis",
                f'<span style="{_C}">Score = Σ pesos do estrato</span> (A1=100, A2=85, A3=70, A4=55, '
                f'B1=40…C=3). <span style="{_C}">Nota = Score ÷ artigos com Qualis</span>. '
                f"<b>Ex.:</b> 3 artigos A1+A2+B1 → Score 100+85+40 = 225; Nota 75. "
                f"<b>Leitura:</b> Score premia <i>volume</i>; Nota premia <i>consistência</i> de alto estrato.",
            ),
        ]
    )
    # — indicadores de impacto do pesquisador (a posteriori: depois das citações) —
    _pesq = "".join(
        [
            _card(
                "Impacto",
                "rs",
                "Citações totais",
                f'<span style="{_C}">C = Σ citações de todos os artigos</span> (OpenAlex, por DOI). '
                f"<b>Ex.:</b> 12 artigos somando 240 citações → C = 240. "
                f"<b>Leitura:</b> impacto bruto; só comparável <i>dentro da mesma área e janela</i> — "
                f"entre áreas, use o FWCI.",
            ),
            _card(
                "Impacto",
                "rs",
                "h-index (Hirsch)",
                f'Maior <span style="{_C}">h</span> com <i>h</i> artigos de ≥ <i>h</i> citações cada. '
                f"<b>Ex.:</b> citações [25, 8, 5, 3, 3] → <b>h = 3</b> (3 artigos com ≥3 citações). "
                f"<b>Leitura:</b> tamanho do núcleo citado; favorece carreiras longas e áreas que citam muito.",
            ),
            _card(
                "Impacto",
                "rs",
                "g-index (Egghe)",
                f'Maior <span style="{_C}">g</span> com os <i>g</i> artigos mais citados somando ≥ <i>g</i>². '
                f"<b>Ex.:</b> [25, 8, 5, 3, 3, 2] soma 46 ≥ 6² = 36 → <b>g = 6</b>. "
                f"<b>Leitura:</b> <i>g</i> ≫ <i>h</i> indica poucos trabalhos muito citados puxando o impacto.",
            ),
            _card(
                "Carreira",
                "sp",
                "m-index (m-quotient)",
                f'<span style="{_C}">m = h ÷ anos de carreira</span> (desde a 1ª publicação). '
                f"<b>Ex.:</b> h = 12 em 8 anos → <b>m = 1,5</b>. "
                f"<b>Leitura:</b> crescimento do núcleo citado por ano — compara início vs fim de "
                f"carreira de forma justa. Aqui a idade vem do 1º artigo com DOI no OpenAlex.",
            ),
            _card(
                "Impacto",
                "rs",
                "i10-index",
                f'<span style="{_C}">i10 = nº de artigos com ≥ 10 citações</span>. '
                f"<b>Ex.:</b> [25, 13, 11, 9, 2] → <b>i10 = 3</b>. "
                f"<b>Leitura:</b> quantos trabalhos passaram de um piso mínimo de visibilidade (limiar grosseiro).",
            ),
            _card(
                "Normalizado",
                "eq",
                "FWCI (impacto normalizado por campo)",
                f'<span style="{_C}">FWCI = citações observadas ÷ esperadas</span> (mesma área, ano e tipo). '
                f"<b>Ex.:</b> 18 citações obtidas vs 12 esperadas → <b>1,5</b> (50% acima da média mundial). "
                f"<b>Leitura:</b> 1 = média mundial; &gt;1 acima; &lt;1 abaixo. <b>Única métrica justa para "
                f"comparar áreas diferentes.</b>",
            ),
            _card(
                "Normalizado",
                "eq",
                "Percentil · top 10% / top 1%",
                f"Posição relativa do artigo no seu campo/ano. <b>Ex.:</b> percentil 95 = supera 95% dos pares; "
                f"<b>top 10%</b> = percentil ≥ 90. <b>Leitura:</b> robusto à forte assimetria das citações "
                f"(a média engana, o percentil não).",
            ),
            _card(
                "Intensidade",
                "rs",
                "Citações por artigo + mediana",
                f'<span style="{_C}">CPP = C ÷ nº de artigos</span>, sempre lida com a <b>mediana</b>. '
                f"<b>Ex.:</b> 240/12 = 20 de média, mas <b>mediana 4</b> se um artigo viral domina. "
                f"<b>Leitura:</b> use a mediana para não ser enganado por um único <i>blockbuster</i>.",
            ),
            _card(
                "Autoria",
                "sp",
                "Crédito fracionado por autoria",
                f'Crédito dividido pelo nº de autores: <span style="{_C}">Σ 1/n_autores</span> (produção) e '
                f'<span style="{_C}">Σ citações/n_autores</span> (impacto). <b>Ex.:</b> 3 artigos com 2, 4 e 1 '
                f"autores → 0,5 + 0,25 + 1,0 = <b>1,75</b> artigos equivalentes. "
                f"<b>Leitura:</b> corrige a hipercoautoria — quem assina com muitos coautores recua.",
            ),
            _card(
                "Temporal",
                "rs",
                "Momentum / velocidade de citação",
                f'<span style="{_C}">momentum = citações de 2024–2025 ÷ total</span>. '
                f"<b>Ex.:</b> 200 citações, 60 recentes → <b>30%</b> de momentum. "
                f"<b>Leitura:</b> sinal de tração <i>recente</i> (aquecendo), não medida de valor consolidado.",
            ),
        ]
    )
    # ---- Artigos-fonte das métricas (rastreabilidade) ----
    _e = (
        lambda s: (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    af = payload.get("artigos_fonte", [])
    n_af = len(af) or 1
    n_af_sjr = sum(1 for a in af if a["sjr_quartil"] not in ("—", ""))
    n_af_qualis = sum(1 for a in af if a["qualis"] not in ("—", ""))
    n_af_doi = 0
    af_rows = ""
    for a in af:
        t = a["titulo"] or "(sem título)"
        t = (t[:140] + "…") if len(t) > 140 else t
        t = _e(t)
        # extrai um DOI real (10.xxxx/…) de campos sujos do Lattes (URLs Scopus etc.)
        _m = re.search(r"10\.\d{4,9}/[^\s\"'<>&?]+", a.get("doi") or "")
        doi = _m.group(0) if _m else ""
        if doi:
            n_af_doi += 1
        thtml = (
            f'<a href="https://doi.org/{_e(doi)}" target="_blank" rel="noopener">{t}</a>'
            f'<span class="af-doitag">DOI</span>'
            if doi
            else t
        )
        ds = a["docentes"]
        docs = _e(", ".join(f"{n.split()[0]} {n.split()[-1]}" for n in ds[:3]))
        if len(ds) > 3:
            docs += f" <span style='color:var(--muted)'>+{len(ds) - 3}</span>"
        sjrv = a["sjr_quartil"] or "—"
        qv = a["qualis"] or "—"
        qcell = f"<td>{_qbadge(qv, _QUALIS_COLOR)}</td>" if qualis_applied else ""
        ftext = _e(f"{a['titulo']} {a['revista']} {' '.join(ds)}").lower()
        af_rows += (
            f'<tr data-f="{ftext}" data-sjr="{_e(sjrv)}" data-qualis="{_e(qv)}" '
            f'data-doi="{1 if doi else 0}"><td data-v="{a["ano"] or 0}">{a["ano"] or "—"}</td>'
            f'<td>{thtml}</td><td>{_e((a["revista"] or "—")[:48])}</td>'
            f"<td>{_qbadge(sjrv, _Q_COLOR)}</td>{qcell}"
            f"<td>{docs}</td></tr>"
        )
    qhead = "<th>Qualis</th>" if qualis_applied else ""
    # opções dos filtros, na ordem natural (Q1→Q4 ; A1→C), só as presentes
    _sjr_ord = ["Q1", "Q2", "Q3", "Q4", "—"]
    _qual_ord = ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "B5", "C", "—"]
    _sjr_pres = {a["sjr_quartil"] or "—" for a in af}
    _qual_pres = {a["qualis"] or "—" for a in af}
    sjr_opts = "".join(
        f'<option value="{x}">SJR {x}</option>' for x in _sjr_ord if x in _sjr_pres
    )
    qualis_opts = "".join(
        f'<option value="{x}">Qualis {x}</option>' for x in _qual_ord if x in _qual_pres
    )
    sec_src = (
        _SRC_TEMPLATE.replace("__N__", str(len(af)))
        .replace("__PSJR__", str(round(n_af_sjr / n_af * 100)))
        .replace("__PQUALIS__", str(round(n_af_qualis / n_af * 100)))
        .replace("__PDOI__", str(round(n_af_doi / n_af * 100)))
        .replace("__SJROPTS__", sjr_opts)
        .replace("__QUALISOPTS__", qualis_opts)
        .replace("__QHEAD__", qhead)
        .replace("__ROWS__", af_rows)
    )

    sec_refs = f"""
    <section class="section">
      <div class="eyebrow">Fórmulas e referências</div>
      <h2>Como cada métrica é calculada — e de onde vem</h2>
      <p class="desc">Seguindo a literatura bibliométrica, nenhuma métrica é usada isoladamente: as
      brutas (citações) vêm primeiro, depois as <b>normalizadas por campo</b> (FWCI) e por
      <b>estágio de carreira</b> (m-index), e só então os sinais complementares (momentum). A leitura
      respeita sempre <b>área, ano, tipo documental e a base</b> (OpenAlex, casado por DOI). Os
      princípios de uso responsável seguem o <b>Manifesto de Leiden</b>, a <b>DORA</b> e a <b>CoARA</b>:
      métricas subordinadas ao juízo qualitativo, transparentes e contextualizadas.</p>

      <h3 style="font-family:var(--serif);font-size:20px;margin:26px 0 4px;">Indicadores do veículo
      <span style="font-weight:400;color:var(--muted);font-size:15px;">— a priori, antes de qualquer citação</span></h3>
      <p class="desc">Onde o trabalho foi publicado. Sinalizam <b>prestígio do canal</b>, não a
      repercussão do artigo em si.</p>
      <div class="findings">{_veic}</div>

      <h3 style="font-family:var(--serif);font-size:20px;margin:26px 0 4px;">Indicadores de impacto do pesquisador
      <span style="font-weight:400;color:var(--muted);font-size:15px;">— a posteriori, a partir das citações reais</span></h3>
      <p class="desc">Quanto o trabalho efetivamente repercutiu (citações OpenAlex, por DOI). Brutos,
      depois normalizados por <b>campo</b> (FWCI, percentil), <b>carreira</b> (m) e <b>autoria</b> (fracionado).</p>
      <div class="findings">{_pesq}</div>

      <h3 style="font-family:var(--serif);font-size:20px;margin:30px 0 8px;">Resumo — fórmulas e referências seminais</h3>
      <div class="card" style="overflow-x:auto;">
        <table>
          <thead><tr><th>Métrica</th><th>O que mede</th><th>Fórmula</th><th>Referência seminal</th></tr></thead>
          <tbody>{_refrows}</tbody>
        </table>
      </div>
      <div class="note" style="border-color:var(--amber);margin-top:14px;">
        <b>Integridade e limitações.</b> As métricas não filtram <b>autocitação</b> nem fragmentação
        estratégica de resultados — leia divergências com cautela (cf. supressão de títulos no JCR por
        padrões anômalos de citação). O <b>m-index</b> usa a 1ª publicação <i>com DOI</i> no OpenAlex
        como proxy de idade acadêmica, podendo subestimar a carreira de quem publicou antes de adotar
        DOI. O <b>FWCI</b> depende da definição de campo da base; o percentil usa o limite inferior do
        intervalo (leitura conservadora). <b>RCR</b> (NIH/iCite) não é usado: cobre essencialmente
        biomedicina/PubMed, fora do perfil do campus.
      </div>
      <div class="note-line">
        Uso responsável: Hicks, Wouters, Waltman, de Rijcke &amp; Rafols (2015),
        <i>The Leiden Manifesto for research metrics</i>, Nature 520:429–431
        (<a href="https://doi.org/10.1038/520429a" target="_blank" rel="noopener">doi:10.1038/520429a</a>) ·
        <a href="https://sfdora.org/" target="_blank" rel="noopener">DORA</a> ·
        <a href="https://coara.eu/" target="_blank" rel="noopener">CoARA</a>.
      </div>
    </section>"""

    fontes = payload.get("fontes", {})
    qfonte = fontes.get("qualis", "")
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Veículos de Publicação — IFES Campus Serra</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{CSS}{MOBILE_CSS}</style></head><body>
<div id="exp-banner" style="background:#b5455f;color:#fff;padding:10px 16px;font-weight:600;font-size:13.5px;text-align:center;position:sticky;top:0;z-index:9999;box-shadow:0 2px 6px rgba(0,0,0,.2);font-family:system-ui,-apple-system,'Segoe UI',sans-serif;">⚠️ Estudo experimental em condução — os dados são preliminares e podem ser modificados. Não usar como fonte da verdade.</div>
<div class="page">
  <div class="hero">
    <span class="kicker">IFES Campus Serra · Análise de Veículos</span>
    <h1>Onde a pesquisa do campus é publicada</h1>
    <p class="lede">Revistas e congressos dos docentes, classificados por impacto internacional
    (SJR/SCImago){' e Qualis CAPES' if qualis_applied else ''}.</p>
    <div class="meta"><span><b>{r['n_revistas_distintas']}</b> revistas</span>
      <span><b>{r['n_artigos']}</b> artigos</span>
      <span><b>{r['n_congressos_distintos']}</b> congressos</span>
      <span>Fonte: Lattes + SJR{' + Qualis' if qualis_applied else ''}</span></div>
  </div>
  {sec_resumo}{kpis}{sec_sjr}{sec_qualis}{EXPL_SJR_QUALIS}{sec_area}{sec_maps}{sec_leaders}{sec_asc}{sec_top}{sec_cong}{sec_comb}{sec_master}{EXPL_QUAD}{sec_src}{sec_metodo}{sec_refs}
  <div class="foot"><span>Gerado em {payload.get('gerado_em','')} · veículos: Lattes ·
  impacto: {fontes.get('impacto_internacional','SJR')} · qualis: {qfonte}</span></div>
</div>
<style>
#fnav{{position:fixed;top:50%;right:18px;transform:translateY(-50%);z-index:50;font-family:var(--font);}}
#fnav-btn{{background:var(--brand-d,#0a5c30);color:#fff;border:none;border-radius:24px;padding:11px 16px;
  font-size:14px;font-weight:600;cursor:pointer;box-shadow:0 4px 14px rgba(16,40,24,.25);}}
#fnav-list{{display:none;flex-direction:column;gap:2px;background:#fff;border:1px solid var(--line,#e2ebe4);
  border-radius:12px;padding:8px;margin-top:8px;max-height:70vh;overflow:auto;box-shadow:0 8px 28px rgba(16,40,24,.18);
  max-width:280px;}}
#fnav.open #fnav-list{{display:flex;}}
#fnav-list a{{font-size:12.5px;color:var(--ink,#16241a);text-decoration:none;padding:6px 10px;border-radius:7px;}}
#fnav-list a:hover{{background:var(--brand-l,#e7f4ec);color:var(--brand-d,#0a5c30);}}
@media print{{#fnav{{display:none;}}}}
</style>
<style>
/* ---- Mobile-first: base = telas pequenas; >=760px restaura o desktop ---- */
.page{{padding:0 14px 56px;}}
.hero{{padding:38px 0 26px;margin-bottom:30px;}}
.hero .lede{{font-size:16px;margin-top:14px;}}
.hero .meta{{gap:8px 16px;}}
.section{{margin:34px 0;}}
.section h2{{font-size:22px;}}
.section .desc{{font-size:14.5px;margin-bottom:18px;}}
.card{{padding:18px 15px;}}
.callout{{padding:26px 20px;}}
.callout h2{{font-size:22px;}}
.rz{{padding:24px 18px;}}
.rz-stats{{grid-template-columns:1fr 1fr;}}
.rz-cards{{grid-template-columns:1fr;}}
/* tabelas: rolam na horizontal em vez de estourar a viewport (padrão GitHub) */
.section table{{display:block;width:max-content;max-width:100%;
  overflow-x:auto;-webkit-overflow-scrolling:touch;}}
th,td{{padding:8px 10px;font-size:13px;}}
/* nav flutuante vai pro rodapé no mobile (não cobre o conteúdo central) */
#fnav{{top:auto;bottom:14px;right:12px;transform:none;}}
#fnav-btn{{padding:9px 14px;font-size:13px;}}
#fnav-list{{max-height:60vh;max-width:78vw;}}

@media(min-width:760px){{
  .page{{padding:0 28px 80px;}}
  .hero{{padding:64px 0 44px;margin-bottom:48px;}}
  .hero .lede{{font-size:19px;margin-top:20px;}}
  .hero .meta{{gap:10px 26px;}}
  .section{{margin:56px 0;}}
  .section h2{{font-size:27px;}}
  .section .desc{{font-size:15px;margin-bottom:26px;}}
  .card{{padding:26px 28px;}}
  .callout{{padding:38px 40px;}}
  .callout h2{{font-size:28px;}}
  .rz{{padding:34px 32px;}}
  .rz-stats{{grid-template-columns:repeat(4,1fr);}}
  .rz-cards{{grid-template-columns:1fr 1fr;}}
  .section table{{display:table;width:100%;}}
  th,td{{padding:11px 14px;font-size:14px;}}
  #fnav{{top:50%;bottom:auto;right:18px;transform:translateY(-50%);}}
}}
</style>
<div id="fnav"><button id="fnav-btn">☰ Seções</button><div id="fnav-list"></div></div>
<script>
(function(){{
  var secs=[].slice.call(document.querySelectorAll('section.section')).filter(function(s){{return s.querySelector('h2');}});
  var list=document.getElementById('fnav-list'), nav=document.getElementById('fnav');
  function mk(text, href, sub){{
    var a=document.createElement('a'); a.href=href; a.textContent=(sub?'– ':'')+text;
    if(sub){{a.style.fontSize='11.5px';a.style.paddingLeft='22px';a.style.color='var(--sub,#5f7268)';}}
    else{{a.style.fontWeight='600';}}
    a.onclick=function(){{nav.classList.remove('open');}}; list.appendChild(a);
  }}
  secs.forEach(function(s,i){{
    s.id='sec'+i; mk(s.querySelector('h2').textContent.trim(), '#sec'+i, false);
    [].slice.call(s.querySelectorAll('h3')).forEach(function(h,j){{
      var t=h.textContent.trim();
      // só subseções reais (cabeçalhos serif); ignora títulos de tabela/quadrante
      if(t.length<3 || (h.getAttribute('style')||'').indexOf('serif')<0) return;
      h.id='sec'+i+'-'+j; mk(t, '#sec'+i+'-'+j, true);
    }});
  }});
  document.getElementById('fnav-btn').onclick=function(){{nav.classList.toggle('open');}};
}})();
// ordenação da tabela-mestre por coluna
(function(){{
  document.querySelectorAll('table.sortable').forEach(function(tb){{
    var ths=tb.querySelectorAll('thead th');
    ths.forEach(function(th,ci){{ th.style.cursor='pointer'; var dir=1;
      th.onclick=function(){{ dir=-dir;
        var rows=[].slice.call(tb.querySelectorAll('tbody tr'));
        rows.sort(function(a,b){{
          var x=a.children[ci], y=b.children[ci];
          var xv=x.getAttribute('data-v'), yv=y.getAttribute('data-v');
          if(xv!==null&&yv!==null) return (parseFloat(xv)-parseFloat(yv))*dir;
          return x.textContent.localeCompare(y.textContent)*dir;
        }});
        var tbody=tb.querySelector('tbody'); rows.forEach(function(r){{tbody.appendChild(r);}});
      }};
    }});
  }});
}})();
</script>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--html", default=str(OUT_DIR / "venues_analysis.html"))
    ap.add_argument(
        "--no-qualis",
        action="store_true",
        help="ignora o Qualis mesmo se o CSV existir (só SJR)",
    )
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument(
        "--download-scimago",
        action="store_true",
        help="baixa/atualiza a base SCImago (data/reference/scimago.csv)",
    )
    ap.add_argument(
        "--qualis",
        default=str(REF_DIR / "qualis.csv"),
        help="CSV Qualis (ISSN -> estrato)",
    )
    ap.add_argument(
        "--qualis-area",
        default=None,
        help="classifica só por uma área de avaliação CAPES "
        "(ex.: 'Engenharias IV'); padrão usa o melhor estrato entre áreas",
    )
    args = ap.parse_args()

    if args.download_scimago or not SCIMAGO_CSV.exists():
        download_scimago()

    scimago = load_scimago()
    qualis = {} if args.no_qualis else load_qualis(Path(args.qualis), args.qualis_area)
    conf_acro, conf_name = load_qualis_conf()
    qualis_applied = bool(qualis)
    area_tag = f" · área={args.qualis_area}" if args.qualis_area else ""
    print(
        f"Referências: SCImago={len(scimago)} ISSNs · Qualis={len(qualis)} ISSNs"
        f"{area_tag}"
        f" · Qualis-Conf={len(conf_acro)} acrônimos"
        f"{' (desligado)' if args.no_qualis else ''}"
    )

    roster = _roster()
    journals, confs, artigos = collect_venues(roster)
    print(
        f"Coletado: {len(journals)} revistas · {len(confs)} congressos "
        f"· {len(artigos)} artigos-fonte (de {len(roster)} docentes)"
    )

    payload = enrich_and_summarize(
        journals, confs, scimago, qualis, args.top, conf_acro, conf_name, artigos
    )
    ranking = (
        rank_docentes(roster, qualis, scimago, conf_acro, conf_name)
        if qualis_applied
        else []
    )
    asc = ascension(roster, qualis) if qualis_applied else []
    citacoes = load_openalex()
    print(f"OpenAlex: {len(citacoes)} docentes com citações")
    payload["ranking_docentes"] = ranking
    payload["ascensao"] = asc
    payload["citacoes_openalex"] = citacoes
    payload["gerado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload["fontes"] = {
        "veiculos": "currículos Lattes (data/lattes_json)",
        "impacto_internacional": "SCImago Journal Rank (SJR), casado por ISSN",
        "qualis": (
            f"CAPES/CNPq — área {args.qualis_area}, casado por ISSN"
            if (qualis and args.qualis_area)
            else "CAPES/CNPq, casado por ISSN" if qualis else "não fornecido"
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written: {out}")

    html_path = Path(args.html)
    html_path.write_text(
        render_html(payload, qualis_applied, ranking, asc, citacoes), encoding="utf-8"
    )
    print(f"Written: {html_path}")

    r = payload["resumo"]
    print(
        f"\n  revistas={r['n_revistas_distintas']} (SJR {r['revistas_com_sjr']} · "
        f"Qualis {r['revistas_com_qualis']}) · artigos={r['n_artigos']}"
    )
    print(f"  SJR quartil: {payload['distribuicao_sjr_quartil']}")
    print("  Top 5 revistas:")
    for j in payload["top_revistas"][:5]:
        print(
            f"    {j['publicacoes']:>3}x  {j['revista'][:50]:<50} "
            f"SJR={j['sjr_quartil']} Qualis={j['qualis']}"
        )
    print("  Top 5 congressos:")
    for c in payload["top_congressos"][:5]:
        print(f"    {c['publicacoes']:>3}x  {c['evento'][:60]}")


if __name__ == "__main__":
    main()
