"""Spec 020: the assign_horizon_ids Prefect flow end to end."""

import json
import sqlite3

from src.flows.maintenance.horizon_ids import assign_horizon_ids_flow
from tests.test_horizon_id_assigner import _build


def test_flow_assigns_ids_and_writes_the_report(tmp_path, monkeypatch):
    for var in (
        "HORIZON_TELEGRAM_BOT_TOKEN",
        "HORIZON_TELEGRAM_CHAT_ID",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.setenv(var, "")
    # The default history paths (snapshot, published zip) are relative: keep
    # the repository's own files out of the test.
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "flow.db"
    _build(db, order_seed=3)
    # The flow must also work on a database the migrations never touched.
    con = sqlite3.connect(db)
    con.execute("DROP TABLE horizon_ids")
    con.execute("DELETE FROM schema_migrations WHERE id = '0002_horizon_ids'")
    con.commit()
    con.close()

    report_dir = tmp_path / "reports"
    state = assign_horizon_ids_flow(
        database_url=f"sqlite:///{db}", report_dir=str(report_dir), return_state=True
    )
    assert state.is_completed()

    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM horizon_ids").fetchone()[0] > 0
    con.close()
    report = json.loads((report_dir / "horizon_ids_report.json").read_text())
    assert report["counts"]["person"] == {"lattes_id": 1, "name": 3}
    assert report["rule_version"] == 1
