from overnight import limits


def test_parse_usage_full_payload():
    usage = limits.parse_usage({
        "five_hour": {"utilization": 12.5, "resets_at": "2026-07-16T04:00:00Z"},
        "seven_day": {"utilization": 61, "resets_at": "2026-07-19T00:00:00Z"},
    })
    assert usage.five_hour_pct == 12.5
    assert usage.five_hour_resets_at == "2026-07-16T04:00:00Z"
    assert usage.seven_day_pct == 61
    assert usage.seven_day_resets_at == "2026-07-19T00:00:00Z"


def test_parse_usage_missing_and_malformed_fields():
    usage = limits.parse_usage({})
    assert usage.five_hour_pct is None
    assert usage.seven_day_pct is None

    usage = limits.parse_usage({"five_hour": {"utilization": "not-a-number"}, "seven_day": "junk"})
    assert usage.five_hour_pct is None
    assert usage.seven_day_pct is None


def test_parse_usage_modern_limits_list():
    usage = limits.parse_usage({
        "five_hour": None,
        "seven_day": None,
        "limits": [
            {"kind": "session", "percent": 27.5, "resets_at": "2026-07-15T09:29:59Z"},
            {"kind": "weekly_scoped", "percent": 12, "resets_at": "2026-07-19T00:00:00Z",
             "scope": {"model": {"display_name": "Sonnet"}}},
            {"kind": "weekly_scoped", "percent": 44, "resets_at": "2026-07-19T00:00:00Z",
             "scope": {"model": {"display_name": "Fable"}}},
        ],
    })
    assert usage.five_hour_pct == 27.5
    assert usage.seven_day_pct == 44  # highest weekly scope wins
    assert usage.seven_day_resets_at == "2026-07-19T00:00:00Z"


def test_fetch_usage_returns_none_without_token(monkeypatch):
    monkeypatch.setattr(limits, "get_access_token", lambda: None)
    assert limits.fetch_usage() is None
