# Data Model: Weekly workflow without the snap Chromium

This feature changes no domain entity, table, export or identity rule. The
database rule version stays at 6 and no rebuild is needed.

The only "model" is the configuration of the weekly job:

| Item | Before | After |
|------|--------|-------|
| Step "Install Playwright Chromium" | `.venv/bin/python -m playwright install --with-deps chromium` | unchanged |
| Step "Install Chromium for Lattes (Selenium)" | `sudo apt-get update -qq` + `sudo apt-get install -y chromium-browser chromium-driver` | removed |
| Job env `CHROME_BINARY` | `/usr/bin/chromium-browser` | removed |
| Job env `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` | removed |
| Every other step and env entry | — | unchanged, same order |

Functions in `src/flows/lattes/download.py`:

| Function | Before | After |
|----------|--------|-------|
| `validate_script_lattes_runtime` | `(chromedriver_path="./chromedriver", chrome_binary=None) -> str`, both ignored | `() -> str`, same check of the Playwright Chromium, same errors |
| `patch_script_lattes_runtime` | `(chrome_binary=None) -> None`, ignored | `() -> None`, same patch |
