# -*- coding: utf-8 -*-
import importlib.util
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("daily_health", ROOT / "fetcher" / "daily_health.py")
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)

NOW = datetime(2026, 11, 4, 12, 40)


def price_data(minutes_old, **overrides):
    updated = NOW - timedelta(minutes=minutes_old)
    data = {
        "updated_at": updated.strftime("%Y-%m-%dT%H:%M:%S"),
        "prices": [],
        "daily_pick": {},
        "afternoon_pick": {},
        "hf_picks": [],
        "hf_pool": [],
    }
    data.update(overrides)
    return data


def utc_stamp(local_dt):
    return (local_dt - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")


def runs_payload(rows):
    return {
        "workflow_runs": [
            {
                "run_started_at": utc_stamp(started),
                "conclusion": conclusion,
                "html_url": "https://example.test/run/%d" % idx,
            }
            for idx, (started, conclusion) in enumerate(rows)
        ]
    }


def planned_successes(now=NOW, omit=(), extra=()):
    rows = []
    window_start = now - timedelta(hours=24)
    for day_offset in (1, 0):
        for slot in health.PLANNED_SLOTS:
            plan = health._slot_time(now, slot, day_offset)
            if window_start <= plan <= now and plan not in omit:
                rows.append((plan, "success"))
    rows.extend(extra)
    return sorted(rows)


def test_intraday_freshness_boundary_covers_two_hour_interval():
    assert health.check_freshness(price_data(120), NOW) == []
    issues = health.check_freshness(price_data(151), NOW)
    assert len(issues) == 1
    assert "盘中阈值 150 分钟" in issues[0]["evidence"]


def test_late_runs_and_single_fallback_gap_are_not_anomalies():
    rows = [
        (datetime(2026, 11, 3, 14, 20), "success"),
        (datetime(2026, 11, 3, 19, 18), "success"),  # 18:00 晚 78 分钟
        (datetime(2026, 11, 3, 20, 56), "success"),
        (datetime(2026, 11, 3, 22, 57), "success"),
        (datetime(2026, 11, 4, 0, 45), "success"),
        (datetime(2026, 11, 4, 2, 56), "success"),   # 02:00 晚 56 分钟
        (datetime(2026, 11, 4, 4, 40), "success"),
        (datetime(2026, 11, 4, 6, 59), "success"),
        (datetime(2026, 11, 4, 8, 40), "success"),
        (datetime(2026, 11, 4, 10, 56), "success"),  # 10:00 晚 56 分钟
    ]
    issues, notes = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T10:56:00"
    )
    assert issues == []
    assert any("晚 78 分钟" in note for note in notes)
    assert any("单次计划未命中" in note for note in notes)


def test_failed_runs_are_not_counted_as_successful_slots():
    rows = [
        (datetime(2026, 11, 4, 10, 0), "failure"),
        (datetime(2026, 11, 4, 10, 56), "timed_out"),
        (datetime(2026, 11, 4, 11, 43), "startup_failure"),
    ]
    issues, _ = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T08:00:00"
    )
    items = {issue["item"] for issue in issues}
    assert "抓取失败" in items
    assert "连续漏档" in items


def test_pending_latest_slot_is_not_a_miss():
    rows = planned_successes(
        omit={datetime(2026, 11, 4, 11, 43)}
    )
    issues, notes = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T12:13:00"
    )
    assert not any(issue["item"] == "连续漏档" for issue in issues)
    assert not any("11-04 11:43" in note for note in notes)


def test_one_successful_run_cannot_cover_multiple_plan_slots():
    omitted = {
        datetime(2026, 11, 4, 2, 0),
        datetime(2026, 11, 4, 3, 37),
        datetime(2026, 11, 4, 4, 0),
        datetime(2026, 11, 4, 4, 12),
    }
    rows = planned_successes(
        omit=omitted,
        extra=[(datetime(2026, 11, 4, 4, 30), "success")],
    )
    issues, _ = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T11:43:00"
    )
    missed = [issue for issue in issues if issue["item"] == "连续漏档"]
    assert len(missed) == 1
    assert "11-04 02:00 至 11-04 04:00 连续 3 个计划触发点" in missed[0]["evidence"]


def test_consecutive_misses_and_unresolved_failure_are_both_reported():
    rows = planned_successes(
        omit={
            datetime(2026, 11, 4, 3, 37),
            datetime(2026, 11, 4, 4, 0),
            datetime(2026, 11, 4, 4, 12),
        },
        extra=[(datetime(2026, 11, 4, 12, 20), "failure")],
    )
    issues, _ = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T11:43:00"
    )
    items = {issue["item"] for issue in issues}
    assert {"连续漏档", "抓取失败"} <= items


def test_three_consecutive_unmatched_slots_still_fail():
    rows = [
        (datetime(2026, 11, 4, 5, 10), "success"),
        (datetime(2026, 11, 4, 9, 20), "success"),
    ]
    issues, notes = health.check_schedule(
        NOW, api_json=runs_payload(rows), data_updated_at="2026-11-04T09:20:00"
    )
    missed = [issue for issue in issues if issue["item"] == "连续漏档"]
    assert missed
    match = re.search(r"连续 (\d+) 个计划触发点", missed[0]["evidence"])
    assert match and int(match.group(1)) >= 3

    # 连续漏档区间之外仍可能有独立的单档提示；这类提示不能覆盖或稀释
    # 已经上报的连续漏档。
    bounds = re.search(
        r"(\d{2}-\d{2} \d{2}:\d{2}) 至 (\d{2}-\d{2} \d{2}:\d{2})",
        missed[0]["evidence"],
    )
    assert bounds
    missed_start, missed_end = (
        datetime.strptime("2026-" + value, "%Y-%m-%d %H:%M")
        for value in bounds.groups()
    )
    single_slots = []
    for note in notes:
        if "单次计划未命中：" not in note:
            continue
        listing = note.split("单次计划未命中：", 1)[1].split("；", 1)[0]
        single_slots.extend(
            datetime.strptime("2026-" + value, "%Y-%m-%d %H:%M")
            for value in re.findall(r"\d{2}-\d{2} \d{2}:\d{2}", listing)
        )
    assert single_slots
    assert all(not (missed_start <= value <= missed_end) for value in single_slots)


def test_successful_dispatch_holds_freshness_alarm_for_one_run():
    stale = price_data(180)
    with (
        mock.patch.object(health, "dispatch_fetch", return_value=(True, "HTTP 204")),
        mock.patch.object(health, "check_board_consistency", return_value=[]),
        mock.patch.object(health, "check_pick_precision", return_value=[]),
        mock.patch.object(health, "check_afternoon_switch", return_value=[]),
        mock.patch.object(health, "check_cross_source", return_value=[]),
        mock.patch.object(health, "check_quote_truth", return_value=[]),
    ):
        report = health.build_report(
            stale, "test", NOW, skip_schedule=True, dispatch_if_stale=True
        )
    assert report["ok"]
    assert report["auto_heal"].startswith("已自动触发补抓")


def test_failed_dispatch_still_reports_stale_and_dispatch_failure():
    stale = price_data(180)
    with (
        mock.patch.object(health, "dispatch_fetch", return_value=(False, "HTTP 403")),
        mock.patch.object(health, "check_board_consistency", return_value=[]),
        mock.patch.object(health, "check_pick_precision", return_value=[]),
        mock.patch.object(health, "check_afternoon_switch", return_value=[]),
        mock.patch.object(health, "check_cross_source", return_value=[]),
        mock.patch.object(health, "check_quote_truth", return_value=[]),
    ):
        report = health.build_report(
            stale, "test", NOW, skip_schedule=True, dispatch_if_stale=True
        )
    items = {issue["item"] for issue in report["anomalies"]}
    assert {"新鲜度", "自动补抓"} <= items


def test_old_snapshot_skips_live_quote_comparison():
    data = price_data(
        60,
        prices=[{
            "name": "碳酸锂",
            "market": "国内",
            "quote_contract": "LC2701",
            "future": 89160,
            "last_settle": 89980,
            "contract_mult": 1,
            "est_margin": 10442.4,
        }],
    )
    with mock.patch.object(
        health.urllib.request, "urlopen", side_effect=AssertionError("network must not run")
    ):
        assert health.check_quote_truth(data, {}, NOW) == []


def test_fresh_same_contract_price_mismatch_still_fails():
    data = price_data(
        5,
        prices=[{
            "name": "碳酸锂",
            "market": "国内",
            "quote_contract": "LC2701",
            "future": 90000,
            "last_settle": 90000,
            "contract_mult": 1,
            "est_margin": 10000,
        }],
    )
    text = 'var hq_str_nf_LC2701="0,0,0,0,0,0,0,0,95000,0,90000,0";\n'

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return text.encode("gbk")

    with mock.patch.object(health.urllib.request, "urlopen", return_value=Response()):
        issues = health.check_quote_truth(data, {}, NOW)
    assert any("现价" in issue["evidence"] and "偏差" in issue["evidence"] for issue in issues)


def test_margin_and_contract_multiplier_checks_always_run():
    data = price_data(
        60,
        prices=[{
            "name": "测试合约",
            "market": "国内",
            "quote_contract": "",
            "future": 100,
            "contract_mult": 2000,
            "est_margin": 1,
        }],
    )
    issues = health.check_quote_truth(data, {}, NOW)
    assert any("保证金" in issue["evidence"] for issue in issues)
    assert any("合约乘数" in issue["evidence"] for issue in issues)
