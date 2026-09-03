from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from platform import system
from typing import Callable, Dict, List

from loguru import logger
from prefect import flow, task

from src.core.logic.lattes_generators import LattesConfigGenerator, LattesListGenerator
from src.notifications.telegram import telegram_flow_state_handlers

LATTES_ID_RE = re.compile(r"(?<!\d)\d{16}(?!\d)")
DEFAULT_LATTES_PREFETCH_WORKERS = 3
LATTES_PLAYWRIGHT_NAV_TIMEOUT_MS = 50_000
LATTES_PREFETCH_ENABLED_ENV = "HORIZON_LATTES_PREFETCH"
LATTES_PREFETCH_WORKERS_ENV = "HORIZON_LATTES_DOWNLOAD_WORKERS"
# scriptLattes.baixaCVLattes retries timeouts/connection-resets *forever*
# (a `continue` that never increments its attempt counter), so a flaky
# lattes.cnpq.br hangs the whole phase. Bound the retries per CV so a stuck
# curriculum fails fast and is skipped by prefetch_lattes_cache.
LATTES_DOWNLOAD_MAX_ATTEMPTS_ENV = "HORIZON_LATTES_DOWNLOAD_MAX_ATTEMPTS"
LATTES_DOWNLOAD_RETRY_SLEEP_S_ENV = "HORIZON_LATTES_DOWNLOAD_RETRY_SLEEP_S"
DEFAULT_LATTES_DOWNLOAD_MAX_ATTEMPTS = 2
DEFAULT_LATTES_DOWNLOAD_RETRY_SLEEP_S = 30
LattesDownloader = Callable[[str, str], None]


class ScriptLattesRuntimeError(RuntimeError):
    """Raised when the local browser runtime cannot support scriptLattes."""


# from research_domain_lib.repository.researcher_repository import ResearcherRepository

# Mocking repository access for standalone flow execution if needed,
# but in real scenario this should inject the repo.
# For now, I'll assume we can get data.
# Since I cannot easily instantiate the real repository without DB connection in this "one-shot" agent,
# I'll create a task that *would* fetch from DB, but for now returns mock data or tries to use the repo if available.


def clean_lattes_json_output(output_dir: str) -> int:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    removed_count = 0
    for json_file in output_path.glob("*.json"):
        json_file.unlink()
        removed_count += 1

    return removed_count


def is_lattes_prefetch_enabled() -> bool:
    value = os.environ.get(LATTES_PREFETCH_ENABLED_ENV)
    if value is None:
        return True

    return value.strip().lower() not in {"0", "false", "no", "off"}


def get_lattes_prefetch_workers() -> int:
    value = os.environ.get(LATTES_PREFETCH_WORKERS_ENV)
    if not value:
        return DEFAULT_LATTES_PREFETCH_WORKERS

    try:
        workers = int(value)
    except ValueError as exc:
        raise ValueError(f"{LATTES_PREFETCH_WORKERS_ENV} must be an integer") from exc

    if workers < 1:
        raise ValueError(f"{LATTES_PREFETCH_WORKERS_ENV} must be >= 1")

    return workers


def get_lattes_download_max_attempts() -> int:
    value = os.environ.get(LATTES_DOWNLOAD_MAX_ATTEMPTS_ENV)
    if not value:
        return DEFAULT_LATTES_DOWNLOAD_MAX_ATTEMPTS
    try:
        attempts = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{LATTES_DOWNLOAD_MAX_ATTEMPTS_ENV} must be an integer"
        ) from exc
    if attempts < 1:
        raise ValueError(f"{LATTES_DOWNLOAD_MAX_ATTEMPTS_ENV} must be >= 1")
    return attempts


def get_lattes_download_retry_sleep_s() -> int:
    value = os.environ.get(LATTES_DOWNLOAD_RETRY_SLEEP_S_ENV)
    if not value:
        return DEFAULT_LATTES_DOWNLOAD_RETRY_SLEEP_S
    try:
        sleep_s = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{LATTES_DOWNLOAD_RETRY_SLEEP_S_ENV} must be an integer"
        ) from exc
    if sleep_s < 0:
        raise ValueError(f"{LATTES_DOWNLOAD_RETRY_SLEEP_S_ENV} must be >= 0")
    return sleep_s


def collect_lattes_ids_from_list(list_path: str) -> List[str]:
    ids = []
    for line in Path(list_path).read_text().splitlines():
        match = LATTES_ID_RE.search(line)
        if match:
            ids.append(match.group(0))
    return ids


def _check_playwright_chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


def _read_command_version(command: List[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, check=False, text=True)
    except OSError:
        return ""

    return "\n".join(part for part in [result.stdout, result.stderr] if part)


def _major_version(version_output: str) -> str:
    match = re.search(r"\b(\d{2,3})\.\d+", version_output)
    return match.group(1) if match else ""


def _candidate_chrome_binaries(chrome_binary: str | None = None) -> List[str]:
    candidates = []
    if chrome_binary:
        candidates.append(chrome_binary)

    env_binary = os.environ.get("CHROME_BINARY")
    if env_binary and env_binary not in candidates:
        candidates.append(env_binary)

    for command in [
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "chromium",
        "chromium-browser",
    ]:
        path = shutil.which(command)
        if path and path not in candidates:
            candidates.append(path)

    return candidates


def validate_script_lattes_runtime(
    chromedriver_path: str = "./chromedriver", chrome_binary: str | None = None
) -> str:
    """Validate that Playwright Chromium is available for scriptLattes."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        raise ScriptLattesRuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    if not _check_playwright_chromium():
        raise ScriptLattesRuntimeError(
            "Playwright Chromium is not installed. Run: playwright install chromium"
        )

    return "playwright-chromium"


def patch_script_lattes_runtime(chrome_binary: str | None = None) -> None:
    try:
        import scriptLattes.baixaLattes as baixa_lattes
    except ImportError as exc:
        raise ScriptLattesRuntimeError(
            "scriptLattes is not installed."
        ) from exc

    if getattr(baixa_lattes, "_horizon_runtime_patched", False):
        return

    def get_data(id_lattes, diretorio):
        rob = baixa_lattes.LattesRobot(results_dir=diretorio)
        print(
            f"Baixando CV Lattes: {id_lattes}. "
            "Este processo pode demorar alguns segundos."
        )
        rob.load_codes(id_lattes)
        rob.check_downloaded_cvs()

        try:
            rob.create_browser()
            rob.context.set_default_navigation_timeout(
                LATTES_PLAYWRIGHT_NAV_TIMEOUT_MS
            )
            rob.collect_html_cvs(0, None)
        finally:
            if getattr(rob, "browser", None):
                rob.browser.close()
            if getattr(rob, "playwright", None):
                rob.playwright.stop()

    baixa_lattes.__get_data = get_data

    def bounded_baixa_cv_lattes(id_lattes: str, diretorio: str) -> None:
        """Bounded replacement for ``baixaCVLattes``.

        The stock implementation wants forever on timeouts/connection-resets
        (its ``continue`` never counts up), which stalls the phase against a
        flaky ``lattes.cnpq.br``. Cap attempts so a stuck CV raises and is
        skipped by ``prefetch_lattes_cache``.
        """
        max_attempts = get_lattes_download_max_attempts()
        retry_sleep_s = get_lattes_download_retry_sleep_s()
        timeout_type = baixa_lattes.PlaywrightTimeoutError or Exception
        for attempt in range(1, max_attempts + 1):
            destino = os.path.join(diretorio, id_lattes)
            if os.path.exists(destino):
                return
            try:
                baixa_lattes.__get_data(id_lattes, diretorio)
            except timeout_type:
                if attempt >= max_attempts:
                    raise
                logger.warning(
                    f"Lattes {id_lattes} navigation timeout (attempt "
                    f"{attempt}/{max_attempts}), retrying in {retry_sleep_s}s."
                )
                time.sleep(retry_sleep_s)
                continue
            except Exception as exc:
                text = str(exc)
                if "ERR_CONNECTION_REFUSED" in text or "ERR_CONNECTION_RESET" in text:
                    if attempt >= max_attempts:
                        raise
                    logger.warning(
                        f"Lattes {id_lattes} connection error (attempt "
                        f"{attempt}/{max_attempts}), retrying in {retry_sleep_s}s."
                    )
                    time.sleep(retry_sleep_s)
                    continue
                raise
            if os.path.exists(destino):
                return
            if attempt >= max_attempts:
                raise ScriptLattesRuntimeError(
                    f"scriptLattes did not create the cache file for Lattes ID "
                    f"{id_lattes}"
                )

    baixa_lattes.baixaCVLattes = bounded_baixa_cv_lattes
    baixa_lattes._horizon_runtime_patched = True


def _script_lattes_downloader(lattes_id: str, cache_dir: str) -> None:
    import scriptLattes.baixaLattes as baixa_lattes

    baixa_lattes.baixaCVLattes(lattes_id, cache_dir)


def _download_lattes_to_cache(
    lattes_id: str, cache_dir: str, downloader: LattesDownloader
) -> None:
    downloader(lattes_id, cache_dir)

    cached_file = Path(cache_dir) / lattes_id
    if not cached_file.exists():
        raise ScriptLattesRuntimeError(
            f"scriptLattes did not create the cache file for Lattes ID {lattes_id}"
        )


def prefetch_lattes_cache(
    lattes_ids: List[str],
    cache_dir: str,
    max_workers: int = DEFAULT_LATTES_PREFETCH_WORKERS,
    downloader: LattesDownloader | None = None,
) -> List[str]:
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    seen_ids = set()
    missing_ids = []
    for lattes_id in lattes_ids:
        if lattes_id in seen_ids:
            continue
        seen_ids.add(lattes_id)

        if not (cache_path / lattes_id).exists():
            missing_ids.append(lattes_id)

    if not missing_ids:
        logger.info(f"All {len(seen_ids)} Lattes curricula are already cached.")
        return []

    if downloader is None:
        patch_script_lattes_runtime()
        downloader = _script_lattes_downloader

    worker_count = min(max_workers, len(missing_ids))
    logger.info(
        f"Prefetching {len(missing_ids)} missing Lattes curricula into "
        f"{cache_dir} with {worker_count} worker(s)."
    )

    if worker_count == 1:
        failed_ids = []
        for lattes_id in missing_ids:
            try:
                _download_lattes_to_cache(lattes_id, str(cache_path), downloader)
            except Exception as exc:
                logger.warning(f"Failed to download Lattes {lattes_id}, skipping: {exc}")
                failed_ids.append(lattes_id)
        if failed_ids:
            logger.warning(f"Skipped {len(failed_ids)} curricula due to download errors: {failed_ids}")
        return [lid for lid in missing_ids if lid not in failed_ids]

    failed_ids = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _download_lattes_to_cache, lattes_id, str(cache_path), downloader
            ): lattes_id
            for lattes_id in missing_ids
        }
        for future in as_completed(futures):
            lattes_id = futures[future]
            try:
                future.result()
            except Exception as exc:
                logger.warning(f"Failed to download Lattes {lattes_id}, skipping: {exc}")
                failed_ids.append(lattes_id)

    if failed_ids:
        logger.warning(f"Skipped {len(failed_ids)} curricula due to download errors: {failed_ids}")

    return [lid for lid in missing_ids if lid not in failed_ids]


@task
def get_researchers_from_db() -> List[Dict]:
    """
    Fetches researchers from the database.
    For this implementation, we will mock the return to ensure the flow runs
    without needing a live DB connection if the environment isn't fully set up for it,
    BUT the goal is to use the DB.
    Equality, let's try to mock it for the 'mock process' requested.
    """
    # In a real scenario:
    # repo = ResearcherRepository(db_session)
    # return repo.get_all()

    # Mock return for the scope of this task 
    return [
        {"name": "Adilson Ribeiro Prado", "lattes_id": "3085491325255749"},
        {"name": "Adriana Padua Lovatte", "lattes_id": "7017732650864488"},
        {"name": "Adrianna Machado Meneguelli", "lattes_id": "5918972460759215"},
        {"name": "Adriano Marcio Sgrancio", "lattes_id": "6083976036911793"},
        {"name": "Alessandra Aguiar Vilarinho", "lattes_id": "7835886986453798"},
        {"name": "Alessandro Bermudes Gomes", "lattes_id": "4784366298051203"},
        {"name": "Alexander Jeferson Nassau Borges", "lattes_id": "5991774940350065"},
        {"name": "Alextian Bartholomeu Liberato", "lattes_id": "5443992982789294"},
        {"name": "Amarildo Mendes Lemos", "lattes_id": "9267167998031136"},
        {"name": "Ana Paula Klauck", "lattes_id": "2598750363094867"},
        {"name": "Augusto Cesar Machado Ramos", "lattes_id": "5802598567613054"},
        {"name": "Avelino Forechi Silva", "lattes_id": "9532091674793623"},
        {"name": "Bene Régis Figueiredo", "lattes_id": "2338034865356198"},
        {"name": "Bruno Cardoso Coutinho", "lattes_id": "8843799612871667"},
        {"name": "Bruno Ramos Gonzaga", "lattes_id": "2837721944606164"},
        {"name": "Carlos Lins Borges Azevedo", "lattes_id": "4748688094924740"},
        {"name": "Cassius Zanetti Resende", "lattes_id": "4261626566157032"},
        {"name": "Celio Proliciano Maioli", "lattes_id": "9321190078824486"},
        {"name": "Cristina Klippel Dominicini", "lattes_id": "7853087416950443"},
        {"name": "Daniel Cruz Cavalieri", "lattes_id": "9583314331960942"},
        {"name": "Daniel Ribeiro Trindade", "lattes_id": "5449301218431564"},
        {"name": "Danilo de Paula e Silva", "lattes_id": "9470331518728833"},
        {"name": "Dárcio Leitão Quintas", "lattes_id": "8017989819517663"},
        {"name": "Dennia Lúcia Goldner Schrock", "lattes_id": "6434498876583164"},
        {"name": "Dirceu Soares Júnior", "lattes_id": "5471356042256233"},
        {"name": "Edilson Luiz do Nascimento", "lattes_id": "7888526444943028"},
        {"name": "Eduardo Max Amaro Amaral", "lattes_id": "2192730100034417"},
        {"name": "Eduardo Peixoto Costa Rocha", "lattes_id": "8617069437130629"},
        {"name": "Eglalciane de Lyrio Tongo Castro", "lattes_id": "1286695973576604"},
        {"name": "Elika Capucho Delazare", "lattes_id": "1989148534910367"},
        {"name": "Elizangela Campos da Rosa Broetto", "lattes_id": "8401553194266093"},
        {"name": "Elton Siqueira Moura", "lattes_id": "7923759097083335"},
        {"name": "Emerson Atilio Birchler", "lattes_id": "6630084362240387"},
        {"name": "Emilene Coco dos Santos", "lattes_id": "1659053731594758"},
        {"name": "Emmanuel Marques Silva", "lattes_id": "8050663713027392"},
        {"name": "Ernani Leite Ribeiro Filho", "lattes_id": "8533403769344054"},
        {"name": "Fabiano Borges Ruy", "lattes_id": "2532510759040199"},
        {"name": "Fábio de Oliveira Lima", "lattes_id": "1245001920023849"},
        {"name": "Felipe Frechiani de Oliveira", "lattes_id": "1403241645360917"},
        {"name": "Fidelis Zanetti de Castro", "lattes_id": "2373180848461397"},
        {"name": "Filipe Wall Mutz", "lattes_id": "3123292310632540"},
        {"name": "Flavio Barcelos Braz da Silva", "lattes_id": "0082588377275398"},
        {"name": "Flávio Garcia Pereira", "lattes_id": "3794041743196202"},
        {"name": "Flávio Giraldeli Bianca", "lattes_id": "2045931062434335"},
        {"name": "Flávio Lopes da Silva", "lattes_id": "9857186681773709"},
        {"name": "Francisco de Assis Boldt", "lattes_id": "0385991152092556"},
        {"name": "Francisco José Casarim Rapchan", "lattes_id": "1844100532565640"},
        {"name": "Gabriel Tozatto Zago", "lattes_id": "8771088249434104"},
        {"name": "Geovane de Araujo Ceolin", "lattes_id": "2097843909201655"},
        {"name": "Geraldo Simonetti Bello", "lattes_id": "2171535044272850"},
        {"name": "Germana Sagrillo Moro", "lattes_id": "8223626264677830"},
        {"name": "Geruza Ferreira Martins", "lattes_id": "8819106413417445"},
        {"name": "Gilberto Neves Sudré Filho", "lattes_id": "7036261180355869"},
        {"name": "Gilmar Luiz Vassoler", "lattes_id": "4324881751736449"},
        {"name": "Giovani Freire Azeredo", "lattes_id": "0401735286340193"},
        {"name": "Giovani Zanetti Neto", "lattes_id": "2040429017342187"},
        {"name": "Guilherme Vicente Curcio", "lattes_id": "9252806100301931"},
        {"name": "Gustavo Maia de Almeida", "lattes_id": "2650921349694794"},
        {"name": "Helder Vago", "lattes_id": "5882342046354572"},
        {"name": "Hilário Tomaz Alves de Oliveira", "lattes_id": "8980213630090119"},
        {"name": "Hilario Seibel Junior", "lattes_id": "8155773475663050"},
        {"name": "Jefferson Oliveira Andrade", "lattes_id": "7138275599443632"},
        {"name": "Jefferson Ribeiro de Lima", "lattes_id": "8645994745413313"},
        {"name": "João Paulo Andrade Almeida", "lattes_id": "4332944687727598"},
        {"name": "João Vitor Ferreira Duque", "lattes_id": "4157383685655204"},
        {"name": "José Claudio Valbuza", "lattes_id": "4082164411182167"},
        {"name": "José Geraldo das Neves Orlandi", "lattes_id": "7801373864813681"},
        {"name": "Karin Satie Komati", "lattes_id": "9860697624155451"},
        {"name": "Kelly Assis de Souza Gazolli", "lattes_id": "0343732414150447"},
        {"name": "Kelly Pecinalli Dias", "lattes_id": "6420688575610064"},
        {"name": "Leandro Colombi Resendo", "lattes_id": "8108487234297364"},
        {"name": "Leandro Melo de Sá", "lattes_id": "8305654290439217"},
        {"name": "Leandro Vianna Silva Souza", "lattes_id": "6111852466319151"},
        {"name": "Leonardo Aguiar do Amaral", "lattes_id": "3747190706760201"},
        {"name": "Leonardo Azevedo Scardua", "lattes_id": "3651077981942079"},
        {"name": "Leonardo Matiazzi Corrêa", "lattes_id": "1879691887687737"},
        {"name": "Lucas Poubel Timm do Carmo", "lattes_id": "0811802207240146"},
        {"name": "Luciano Alves de Souza", "lattes_id": "1092573631336131"},
        {"name": "Luiz Alberto Pinto", "lattes_id": "3550111932609658"},
        {"name": "Maikon Chaider Silva Scaldaferro", "lattes_id": "5909044646841082"},
        {"name": "Marcelo Franco de Almeida", "lattes_id": "3326528545654268"},
        {"name": "Marco Antonio de Souza Leite Cuadros", "lattes_id": "8629256330944049"},
        {"name": "Marcos Paulo Kohler Caldas", "lattes_id": "6499650719150590"},
        {"name": "Marcos Simão Guimarães", "lattes_id": "1309219372857869"},
        {"name": "Marta Talitha Carvalho Freire Mendes", "lattes_id": "3770740577508464"},
        {"name": "Mateus Conrad Barcellos da Costa", "lattes_id": "9244741653857997"},
        {"name": "Maxwell Eduardo Monteiro", "lattes_id": "8831352516689445"},
        {"name": "Milainy Ludmila Santos Goulart", "lattes_id": "4538755343018125"},
        {"name": "Moises Savedra Omena", "lattes_id": "0059221043399777"},
        {"name": "Monalessa Perini Barcellos", "lattes_id": "8826584877205264"},
        {"name": "Nauvia Maria Cancelieri", "lattes_id": "7515984919866826"},
        {"name": "Pablo Rodrigues Muniz", "lattes_id": "4404912914498937"},
        {"name": "Paulo Cezar Camargo Guedes", "lattes_id": "5710836199570315"},
        {"name": "Paulo Sergio dos Santos Junior", "lattes_id": "8400407353673370"},
        {"name": "Rafael Emerick Zape de Oliveira", "lattes_id": "8365543719828195"},
        {"name": "Rafael Peixoto Derenzi Vivacqua", "lattes_id": "9741308000396752"},
        {"name": "Raphael Magalhães Gomes Moreira", "lattes_id": "6358999333136028"},
        {"name": "Reginaldo Barbosa Nunes", "lattes_id": "0301147577506989"},
        {"name": "Reginaldo Corteletti", "lattes_id": "3373905719716652"},
        {"name": "Renata Gomes de Jesus", "lattes_id": "1386809028095357"},
        {"name": "Renato Tannure Rotta de Almeida", "lattes_id": "6927212610032092"},
        {"name": "Renner Sartório Camargo", "lattes_id": "3539297708118726"},
        {"name": "Ricardo Ramos Costa", "lattes_id": "3570729284909193"},
        {"name": "Richard Junior Manuel Godinez Tello", "lattes_id": "3966230569744918"},
        {"name": "Rodrigo Fernandes Calhau", "lattes_id": "5553396597490044"},
        {"name": "Rodrigo Varejão Andreão", "lattes_id": "5589662366089944"},
        {"name": "Rogério Passos do Amaral Pereira", "lattes_id": "2592658166362342"},
        {"name": "Ronaldo Aparecida Marques", "lattes_id": "2269276436108008"},
        {"name": "Rosiane Ribeiro Rocha", "lattes_id": "7769380471199102"},
        {"name": "Rosilene de Sá Ribeiro", "lattes_id": "1985806708983534"},
        {"name": "Sâmela Pedrada Cardoso", "lattes_id": "4586755132358194"},
        {"name": "Saul da Silva Munareto", "lattes_id": "1484609457358730"},
        {"name": "Sebastiao Alves Carneiro", "lattes_id": "3789212516519179"},
        {"name": "Sérgio Nery Simões", "lattes_id": "0723238551725187"},
        {"name": "Tatiane Policário Chagas", "lattes_id": "1744803991048846"},
        {"name": "Thiago Chieppe Saquetto", "lattes_id": "4442796313166334"},
        {"name": "Thiago Meireles Paixão", "lattes_id": "2961730349897943"},
        {"name": "Vantuil Manoel Thebas", "lattes_id": "4206334178739043"},
        {"name": "Victorio Albani de Carvalho", "lattes_id": "6035323365313300"},
        {"name": "Vinicius Moura Marques", "lattes_id": "7513722036411244"},
        {"name": "Vinícius Secchin de Melo", "lattes_id": "0449903748898289"},
        {"name": "Vitor Faiçal Campana", "lattes_id": "4448287274372321"},
        {"name": "Wagner Kirmse Caldas", "lattes_id": "1629043689973681"},
        {"name": "Wagner Scopel Falcão", "lattes_id": "2924845095994521"},
        {"name": "Wallas Gusmão Thomas", "lattes_id": "7656611629494754"},
        {"name": "Érika de Andrade Silva Leal", "lattes_id": "5048394550720569"},
    ]


@task
def generate_config(output_dir: str, list_path: str, cache_dir: str) -> str:
    config_gen = LattesConfigGenerator()
    config_path = os.path.abspath("lattes.config")
    config_gen.generate(config_path, output_dir, list_path, cache_dir=cache_dir)
    return config_path


@task
def generate_list(researchers: List[Dict]) -> str:
    list_gen = LattesListGenerator()
    list_path = os.path.abspath(os.path.join("data", "lattes_run", "lattes.list"))
    os.makedirs(os.path.dirname(list_path), exist_ok=True)
    list_gen.generate_from_db(list_path, researchers)
    return list_path


@task
def run_script_lattes_real(config_path: str):
    try:
        from scriptLattes.run import executar_scriptLattes

        patch_script_lattes_runtime()
        logger.info(f"Starting real scriptLattes execution with config: {config_path}")
        # Run with somente_json=True since we are an ETL pipeline
        executar_scriptLattes(config_path, somente_json=True)
        logger.info("Real scriptLattes execution finished.")
    except ImportError:
        logger.error("scriptLattes library not found. Please install it.")
        raise
    except Exception as e:
        logger.error(f"scriptLattes execution failed: {e}")
        raise


@flow(name="Download Lattes Curricula", **telegram_flow_state_handlers())
def download_lattes_flow():
    base_dir = os.path.abspath("data")
    output_dir = os.path.join(base_dir, "lattes_json")
    cache_dir = os.path.abspath("cache")

    override_list_path = os.path.abspath("data/lattes_run/lattes.list")

    if os.path.exists(override_list_path):
        logger.info(f"Using override list file: {override_list_path}")
        list_path = override_list_path
    else:
        logger.info("Using DB researchers for list generation.")
        researchers = get_researchers_from_db()
        list_path = generate_list(researchers)

    lattes_ids = collect_lattes_ids_from_list(list_path)
    if not lattes_ids:
        raise ValueError(f"No valid 16-digit Lattes IDs found in {list_path}")
    logger.info(f"Preparing to download {len(lattes_ids)} Lattes curricula.")

    validate_script_lattes_runtime()
    logger.info("Playwright Chromium runtime validated for scriptLattes.")

    removed_jsons = clean_lattes_json_output(output_dir)
    if removed_jsons:
        logger.info(
            f"Removed {removed_jsons} stale Lattes JSON files from {output_dir}"
        )

    effective_list_path = list_path
    if is_lattes_prefetch_enabled():
        prefetch_lattes_cache(
            lattes_ids,
            cache_dir,
            max_workers=get_lattes_prefetch_workers(),
        )
        cache_path = Path(cache_dir)
        failed_ids = {lid for lid in lattes_ids if not (cache_path / lid).exists()}
        if failed_ids:
            tmp_list = os.path.abspath("lattes_effective.list")
            with open(tmp_list, "w") as f:
                for line in Path(list_path).read_text().splitlines():
                    match = LATTES_ID_RE.search(line)
                    if match and match.group(0) in failed_ids:
                        continue
                    f.write(line + "\n")
            effective_list_path = tmp_list
            logger.info(f"Excluded {len(failed_ids)} failed IDs from scriptLattes run: {failed_ids}")
    else:
        logger.info(f"Lattes cache prefetch disabled by {LATTES_PREFETCH_ENABLED_ENV}.")

    config_path = generate_config(output_dir, effective_list_path, cache_dir)
    run_script_lattes_real(config_path)


if __name__ == "__main__":
    download_lattes_flow()
