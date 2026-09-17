import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class LattesProject:
    name: str
    start_year: Optional[int]
    end_year: Optional[int]
    status: str
    description: str
    nature: str
    type_name: str  # "Research Project", "Extension Project", "Development Project"
    role: str  # "Coordenador", "Integrante"


class LattesParser:
    """
    Parses Lattes JSON structure to extract projects and articles.
    """

    def normalize_title(self, title: Optional[str]) -> str:
        """
        Normalizes a title for comparison (lowercase, no accents, no special chars).
        """
        if not title:
            return ""
        # Accents and case
        nfkd_form = unicodedata.normalize("NFKD", title)
        only_ascii = nfkd_form.encode("ASCII", "ignore").decode("ASCII")
        # Remove special characters and multiple spaces
        clean = re.sub(r"[^a-zA-Z0-9\s]", " ", only_ascii).lower()
        return " ".join(clean.split())

    def parse_research_projects(self, data: Dict) -> List[Dict]:
        return self._parse_generic_projects(
            data, "projetos_pesquisa", "Research Project"
        )

    def parse_extension_projects(self, data: Dict) -> List[Dict]:
        return self._parse_generic_projects(
            data, "projetos_extensao", "Extension Project"
        )

    def parse_development_projects(self, json_data: dict) -> List[Dict[str, Any]]:
        """Parses 'projetos_desenvolvimento' from JSON."""
        return self._parse_generic_projects(
            json_data, "projetos_desenvolvimento", "Development Project"
        )

    def parse_articles(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'artigos_periodicos' from JSON."""
        biblio = data.get("producao_bibliografica", {})
        items = biblio.get("artigos_periodicos", [])
        parsed = []
        for item in items:
            title = item.get("titulo")
            parsed.append(
                {
                    "title": title,
                    "normalized_title": self.normalize_title(title),
                    "year": (
                        int(item["ano"]) if str(item.get("ano", "")).isdigit() else None
                    ),
                    "journal_conference": item.get("revista"),
                    "volume": item.get("volume"),
                    "pages": item.get("paginas"),
                    "doi": item.get("doi"),
                    "authors_str": item.get("autores"),
                    "type": "Journal",  # lib expectation
                }
            )
        return parsed

    def parse_conference_papers(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'trabalhos_completos_congressos' from JSON."""
        biblio = data.get("producao_bibliografica", {})
        items = biblio.get("trabalhos_completos_congressos", [])
        parsed = []
        for item in items:
            title = item.get("titulo")
            parsed.append(
                {
                    "title": title,
                    "normalized_title": self.normalize_title(title),
                    "year": (
                        int(item["ano"]) if str(item.get("ano", "")).isdigit() else None
                    ),
                    "journal_conference": item.get("evento"),
                    "pages": item.get("paginas"),
                    "authors_str": item.get("autores"),
                    "type": "Conference Event",  # lib expectation
                }
            )
        return parsed

    def parse_personal_info(self, data: Dict) -> Dict[str, Any]:
        """
        Extracts personal info (name, resume, etc) from JSON.
        """
        info = data.get("informacoes_pessoais", {})
        return {
            "name": info.get("nome_completo") or data.get("nome") or data.get("name"),
            "resume": info.get("texto_resumo"),
            "lattes_id": info.get("id_lattes"),
            "citation_names": info.get("nome_citacoes"),
            "cnpq_url": info.get("url"),
        }

    def parse_academic_education(self, json_data: dict) -> List[Dict[str, Any]]:
        """Parses 'formacao_academica' from JSON."""
        items = json_data.get("formacao_academica", [])
        if not items:
            return []

        parsed_items = []
        for item in items:
            try:
                # Extract degree code/name
                # Some JSONs have 'tipo': 'Doutorado em Informática'
                # Others might have 'nome_pt' or 'degree'
                degree = item.get("nome_pt") or item.get("degree")
                course_name = item.get("nome_curso_ingles")

                if not degree:
                    tipo = item.get("tipo", "")
                    if " em " in tipo:
                        parts = tipo.split(" em ", 1)
                        degree = parts[0]
                        course_name = parts[1] if not course_name else course_name
                    else:
                        degree = tipo or "Unknown"

                # Extract years
                start_year = None
                if item.get("ano_inicio"):
                    try:
                        start_year = int(item["ano_inicio"])
                    except ValueError:
                        pass

                end_year = None
                if item.get("ano_conclusao") or item.get("ano_fim"):
                    val = item.get("ano_conclusao") or item.get("ano_fim")
                    try:
                        end_year = int(val)
                    except ValueError:
                        pass

                # Extract institution
                institution = item.get("nome_instituicao") or item.get("institution")

                # Fallback course name
                if not course_name:
                    course_name = degree

                # Extract Description and Thesis Title
                description = item.get("descricao")
                thesis_title = None

                if description:
                    # Description is sometimes a list in legacy formats, but usually a string in JSON
                    # If it's a list, join it? The sample shows it as string inside list in other fields,
                    # but for `formacao_academica` strict schema isn't fully clear.
                    # Assuming string as per recent observation
                    # "descricao": "Título: From Continuous ... , Ano..."

                    # Regex to find title
                    # Pattern: Título: (.*?)(,|Ano de|$)
                    # Adjust regex to capture until comma or known delimeters
                    match = re.search(
                        r"Título:\s*(.+?)(?:, Ano|,\s*Orientador|\.|$)",
                        description,
                        re.IGNORECASE,
                    )
                    if match:
                        thesis_title = match.group(1).strip()

                parsed_items.append(
                    {
                        "degree": degree,
                        "institution": institution,
                        "course_name": course_name,
                        "start_year": start_year,
                        "end_year": end_year,
                        "description": description,
                        "thesis_title": thesis_title,
                    }
                )
            except Exception as e:
                logger.warning(f"Error parsing education item: {e}")
                continue

        return parsed_items

    def _to_int(self, value: Any) -> Optional[int]:
        """Coerces a Lattes year-ish value to int, tolerating strings/None/'Atual'."""
        if value is None:
            return None
        s = str(value).strip()
        return int(s) if s.isdigit() else None

    def parse_awards(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'premios_titulos' (awards and titles) from JSON.

        Maps to the `awards` entity (title, year).
        """
        items = data.get("premios_titulos") or []
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("descricao") or item.get("titulo") or "").strip()
            if not title:
                continue
            parsed.append({"title": title[:255], "year": self._to_int(item.get("ano"))})
        return parsed

    def parse_languages(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'idiomas' (language proficiencies) from JSON.

        Maps to the `languages` + `proficiencies` entities.
        """
        items = data.get("idiomas") or []
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("nome") or item.get("idioma") or "").strip()
            if not name:
                continue
            parsed.append(
                {
                    "language": name,
                    "comprehension": (item.get("compreende") or None),
                    "speaking": (item.get("fala") or None),
                    "reading": (item.get("le") or None),
                    "writing": (item.get("escreve") or None),
                }
            )
        return parsed

    def parse_professional_activities(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'atuacao_profissional' from JSON.

        Maps to the `professional_activities` entity. `ano_fim` == 'Atual'
        marks a current bond (end_year left null, current=True).
        """
        items = data.get("atuacao_profissional") or []
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            institution = (
                item.get("instituicao") or item.get("instituicao_nome") or ""
            ).strip()
            if not institution:
                continue
            end_raw = item.get("ano_fim")
            is_current = isinstance(end_raw, str) and end_raw.strip().lower() in (
                "atual",
                "atualmente",
            )
            parsed.append(
                {
                    "institution": institution[:500],
                    "institution_name": (item.get("instituicao_nome") or None),
                    "institution_acronym": (item.get("instituicao_sigla") or None),
                    "institution_country": (item.get("instituicao_pais") or None),
                    "period": (item.get("periodo") or None),
                    "start_year": self._to_int(item.get("ano_inicio")),
                    "end_year": None if is_current else self._to_int(end_raw),
                    "bond": (item.get("vinculo") or None),
                    "classification": (item.get("enquadramento") or None),
                    "work_regime": (item.get("regime") or None),
                    "role_function": (item.get("cargo_funcao") or None),
                    "activity_type": (item.get("tipo") or None),
                    "current": is_current,
                }
            )
        return parsed

    def parse_technical_productions(self, data: Dict) -> List[Dict[str, Any]]:
        """Parses 'producao_tecnica' and 'patentes_registros' from JSON.

        Both are dicts of category -> list of items; maps to the generic
        `research_productions` entity, with the Lattes category kept as
        `production_type` (e.g. 'softwares_sem_patente', 'patentes').
        """
        parsed = []
        for section_key in ("producao_tecnica", "patentes_registros"):
            section = data.get(section_key) or {}
            if not isinstance(section, dict):
                continue
            for category, items in section.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    title = (item.get("titulo") or "").strip()
                    if not title:
                        continue
                    parsed.append(
                        {
                            "title": title,
                            "normalized_title": self.normalize_title(title),
                            "year": self._to_int(item.get("ano")),
                            "authors_str": item.get("autores"),
                            "institution": (item.get("instituicao") or None),
                            "production_type": category,
                        }
                    )
        return parsed

    def _parse_generic_projects(
        self, data: Dict, projects_key: str, type_name: str
    ) -> List[Dict]:
        parsed_projects = []
        projects_list = data.get(projects_key, [])

        for p in projects_list:
            name = p.get("name") or p.get("nome")
            start_year_str = p.get("ano_inicio")
            end_year_str = p.get("ano_conclusao")

            start_year = (
                int(start_year_str)
                if start_year_str and start_year_str.isdigit()
                else None
            )

            end_year = None
            if end_year_str and end_year_str.isdigit():
                end_year = int(end_year_str)

            # Status Inference
            status = "Concluded"
            if end_year_str and end_year_str.lower() == "atual":
                status = "Active"
                end_year = None
            elif end_year:
                if date(end_year, 12, 31) >= date.today():
                    status = "Active"

            # Description Cleaning
            # Description is often a list with one string containing "Descrição: ... Situação: ... Natureza: ..."
            raw_desc_list = p.get("descricao", [])
            full_desc_str = (
                " ".join(raw_desc_list)
                if isinstance(raw_desc_list, list)
                else str(raw_desc_list)
            )

            description = self._clean_description(full_desc_str)

            # Role extraction (self-role for the owner of the CV)
            # We don't have the Researcher ID here easily without context,
            # but usually the first member or looking for "Coordenador" match?
            # Actually, the JSON often lists "integrantes" with names and roles.
            # For this MVP, we will extract the members list as metadata if needed,
            # but the key is to return the Project definition.

            parsed_projects.append(
                {
                    "name": name,
                    "start_year": start_year,
                    "end_year": end_year,
                    "status": status,
                    "description": description,
                    "initiative_type_name": type_name,
                    "raw_members": p.get("integrantes", []),
                    "raw_sponsors": p.get("financiadores", []),
                }
            )

        return parsed_projects

    def _clean_description(self, text: str) -> str:
        """
        Removes metadata prefix/suffix from description.
        Input: "Descrição: O projeto... Situação: Em andamento; Natureza: Pesquisa..."
        Output: "O projeto..."
        """
        if not text:
            return ""

        # Remove literal "Descrição:" prefix
        clean = re.sub(r"^Descrição:\s*", "", text, flags=re.IGNORECASE)

        # Remove Metadata suffix starting with "Situação:" or "Natureza:"
        # We split by these keys and take the first part
        split_markers = ["Situação:", "Natureza:", "Alunos envolvidos:", "Integrantes:"]

        for marker in split_markers:
            if marker in clean:
                clean = clean.split(marker)[0]

        return clean.strip().rstrip(".")

    def parse_advisorships(self, data: Dict) -> List[Dict[str, Any]]:
        """
        Parses advisorships from JSON.
        Supports both direct 'orientacoes' dict (scriptLattes style) and 'dados_complementares' list (generic style).
        """
        advisorships = []

        # Strategy A: Top-level 'orientacoes' dict (Nested types)
        if "orientacoes" in data and isinstance(data["orientacoes"], dict):
            sections = {"concluidas": "Concluded", "em_andamento": "In Progress"}

            for section_key, status in sections.items():
                section_data = data["orientacoes"].get(section_key, {})
                if isinstance(section_data, dict):
                    for type_key, items in section_data.items():
                        if isinstance(items, list):
                            parsed = self._parse_items(
                                items, status=status, default_type=type_key
                            )
                            advisorships.extend(parsed)

            return advisorships

        # Strategy B: 'dados_complementares' flat lists (Fallback)
        # 1. Concluded
        concluded = self._parse_generic_advisorships(
            data, "orientacoes_concluidas", status="Concluded"
        )
        advisorships.extend(concluded)

        # 2. In Progress
        in_progress = self._parse_generic_advisorships(
            data, "orientacoes_em_andamento", status="In Progress"
        )
        advisorships.extend(in_progress)

        return advisorships

    def _parse_items(
        self, items: List[Dict], status: str, default_type: str = ""
    ) -> List[Dict]:
        """
        Parses a list of advisorship items from the 'orientacoes' dict structure.
        """
        parsed = []
        for item in items:
            title = item.get("titulo")
            # Try specific keys first, then generic
            student_name = item.get("orientando") or item.get("nome_do_orientado")

            start_year_str = item.get("ano_inicio")
            end_year_str = item.get("ano_conclusao") or item.get("ano")
            start_year = (
                int(start_year_str)
                if start_year_str and str(start_year_str).isdigit()
                else None
            )
            end_year = (
                int(end_year_str)
                if end_year_str and str(end_year_str).isdigit()
                else None
            )
            year = end_year or start_year

            institution = item.get("instituicao") or item.get("nome_instituicao")

            # Map type_key to canonical
            nature = (item.get("natureza") or item.get("tipo_trabalho") or "").lower()
            tipo = item.get("tipo", "").lower()
            def_type_lower = default_type.lower()

            # Combine all for search
            text_search = f"{nature} {tipo} {def_type_lower}"

            canonical_type = "Advisorship"
            if "mestrado" in text_search:
                canonical_type = "Master's Thesis"
            elif "doutorado" in text_search:
                canonical_type = "PhD Thesis"
            elif (
                "iniciacao_cientifica" in text_search
                or "iniciação científica" in text_search
            ):
                canonical_type = "Scientific Initiation"
            elif (
                "conclusão de curso" in text_search
                or "tcc" in text_search
                or "graduacao" in text_search
            ):
                canonical_type = "Undergraduate Thesis"
            elif "pos_doutorado" in text_search or "pós-doutorado" in text_search:
                canonical_type = "Post-Doctorate"
            elif "especializacao" in text_search or "especialização" in text_search:
                canonical_type = "Specialization"
            elif "outras" in text_search or "outros" in text_search:
                canonical_type = "Advisorship"

            if title and student_name:
                parsed.append(
                    {
                        "title": title,
                        "normalized_title": self.normalize_title(title),
                        "student_name": student_name,
                        "year": year,
                        "start_year": start_year,
                        "end_year": end_year,
                        "institution": institution,
                        "type": canonical_type,
                        "status": status,
                        "nature": nature,
                    }
                )
        return parsed

    def _parse_generic_advisorships(
        self, data: Dict, key: str, status: str
    ) -> List[Dict]:
        """
        Helper to parse specific advisorship sections.
        """
        section = data.get("dados_complementares", {}).get(key, [])
        parsed = []

        # Mapping of Lattes types to Canonical types
        # This mapping might need refinement based on exact Lattes strings
        type_map = {
            "dissertacao_de_mestrado": "Master's Thesis",
            "tese_de_doutorado": "PhD Thesis",
            "monografia_de_conclusao_de_curso_aperfeicoamento_e_especializacao": "Specialization",
            "trabalho_de_conclusao_de_curso_graduacao": "Undergraduate Thesis",
            "iniciacao_cientifica": "Scientific Initiation",
            "supervisao_de_pos_doutorado": "Post-Doc Supervision",
        }

        for item in section:
            # Type extraction logic can be complex in Lattes.
            # Usually the key name in the list dictates the type if it's a list of specific objects,
            # but in the JSON export, they are often flattened.
            # We look for specific known keys or 'natureza'.

            nature = (item.get("natureza") or item.get("tipo_trabalho", "")).lower()
            tipo = item.get(
                "tipo", ""
            ).lower()  # Sometimes 'tipo' holds "MESTRADO", "DOUTORADO"

            canonical_type = "Advisorship"

            # Simple heuristic for type
            if "mestrado" in nature or "mestrado" in tipo:
                canonical_type = "Master's Thesis"
            elif "doutorado" in nature or "doutorado" in tipo:
                canonical_type = "PhD Thesis"
            elif "iniciação científica" in nature or "iniciacao_cientifica" in nature:
                canonical_type = "Scientific Initiation"
            elif "conclusão de curso" in nature or "graduacao" in nature:
                canonical_type = "Undergraduate Thesis"
            elif "pós-doutorado" in nature or "pos_doutorado" in nature:
                canonical_type = "Post-Doc Supervision"

            # Extract common fields
            title = item.get("titulo")
            student_name = item.get("orientando") or item.get("nome_do_orientado")

            start_year_str = item.get("ano_inicio")
            end_year_str = item.get("ano_conclusao") or item.get("ano")
            start_year = (
                int(start_year_str)
                if start_year_str and str(start_year_str).isdigit()
                else None
            )
            end_year = (
                int(end_year_str)
                if end_year_str and str(end_year_str).isdigit()
                else None
            )
            year = end_year or start_year

            institution = item.get("instituicao") or item.get("nome_instituicao")

            if title and student_name:
                parsed.append(
                    {
                        "title": title,
                        "normalized_title": self.normalize_title(title),
                        "student_name": student_name,
                        "year": year,
                        "start_year": start_year,
                        "end_year": end_year,
                        "institution": institution,
                        "type": canonical_type,
                        "status": status,
                        "nature": nature,
                    }
                )

        return parsed
