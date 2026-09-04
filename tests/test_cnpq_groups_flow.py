from unittest.mock import MagicMock, patch

from src.flows.cnpq.groups import build_cnpq_sync_summary, get_groups_to_sync


def test_build_cnpq_sync_summary_reports_failed_groups():
    summary = build_cnpq_sync_summary(
        [
            {"success": True, "group_id": 1, "group_name": "Ok", "url": "http://ok"},
            {
                "success": False,
                "group_id": 2,
                "group_name": "Broken",
                "url": "http://broken",
            },
        ]
    )

    assert summary["total_groups"] == 2
    assert summary["success_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["warnings"] == [
        {
            "source": "cnpq",
            "severity": "warning",
            "code": "cnpq_group_sync_failed",
            "count": 1,
            "examples": [
                {
                    "group_id": 2,
                    "group_name": "Broken",
                    "url": "http://broken",
                }
            ],
            "message": "CNPq sync failed for 1 group(s); inspect URLs or portal availability.",
        }
    ]


def test_get_groups_to_sync_returns_valid_and_invalid_keys_when_no_campus_matches():
    # The flow does to_sync["valid"] / to_sync["invalid"]; when campus matches
    # nothing the task must still return that dict shape, not a bare list
    # (which crashed the weekly EtL with "TypeError: list indices must be
    # integers or slices, not str").
    fake_campus = MagicMock()
    fake_campus.get_all.return_value = [
        MagicMock(name="Vila Velha", id=1),
        MagicMock(name="Vitória", id=2),
    ]
    with (
        patch("src.flows.cnpq.groups.get_run_logger", return_value=MagicMock()),
        patch("src.flows.cnpq.groups.CampusController", return_value=fake_campus),
        patch("src.flows.cnpq.groups.ResearchGroupController"),
    ):
        result = get_groups_to_sync.fn(campus_name="Serra")

    assert result == {"valid": [], "invalid": []}
