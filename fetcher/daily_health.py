# -*- coding: utf-8 -*-
"""daily_health.py - 「心得」打板数据每日体检（只读，不改交易逻辑）

检查 6 项：
  1 新鲜度        prices.json 的 updated_at 距当前北京时间；盘中(08:00-23:00) >75 分钟、非盘中 >240 分钟 异常
  2 晨/午板自洽   ruleset3 起只有单向 plan：做多 entry>=price 且 sl<entry<tp；做空 entry<=price 且 tp<entry<sl；anchor == price；
                  回踩档 entry_alt 落在当日 [day_low, day_high]；午板在数据时间 <11:00 时为空属正常
  3 候选项要精    hf_picks 只含最精的一级（全部无 day_conflict；全带冲突时只保留一条）；条数 <= 5
  4 午板换标的    hf_pool 里存在与晨板不同品种时，afternoon_pick 不应与 daily_pick 同品种
  5 跨源冲突标注  cross_source_dev_pct > 2 的品种，其 pick 必须带「数据源冲突」前缀且 day_ma 为 null；
                  每行 basis 应约等于 (spot - last_settle)，误差 < 0.51
  6 定时漏档      对照 fetch.yml 的 cron 计划，查最近 24 小时的 workflow run：漏档，或比计划晚 30 分钟以上

输出：
  data/health.json   最新报告 + 历史（供手机端/仓库查看）
  data/run_log.json  追加一条「体检」日志（App「运行日志」页可直接看到）

退出码：0=全部正常（保持安静）；1=发现异常（workflow 变红，触发 GitHub 通知）
用法：
  python3 fetcher/daily_health.py
  python3 fetcher/daily_health.py --prices-from-origin --out data/health.json --run-log data/run_log.json
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    CN = ZoneInfo("Asia/Shanghai")
except Exception:  # 极端环境下没有 tzdata 时退化为 UTC+8 固定偏移
    CN = timezone(timedelta(hours=8))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("HEALTH_REPO", "1727277947-arch/newsradar-fetch")
WORKFLOW_FILE = os.environ.get("HEALTH_WORKFLOW", "fetch.yml")

# fetch.yml 里的计划时刻（北京时间），与 workflow 中的 cron 注释一致
PLANNED_SLOTS = [
    "00:07", "02:00", "03:37", "04:00", "04:12", "06:00", "08:00", "10:00",
    "11:43", "12:00", "12:13", "14:00", "18:00", "20:00", "20:23", "20:53", "22:00",
]

FRESH_LIMIT_TRADING = 75      # 分钟
FRESH_LIMIT_IDLE = 240        # 分钟
SLOT_TOLERANCE = 30           # 分钟
SPOT_DEV_LIMIT = 2.0          # cross_source_dev_pct 阈值
BASIS_TOLERANCE = 0.51
EPS = 0.011                   # 浮点比较容差


def now_cn():
    return datetime.now(CN).replace(tzinfo=None)


def parse_cn(text):
    """解析 prices.json 里的 'YYYY-MM-DDTHH:MM:SS'（北京时间，无时区）"""
    if not text:
        return None
    text = str(text).strip().replace("Z", "").replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


def load_prices(path, from_origin=False):
    """读 prices.json：优先 origin/main（线上真实数据），失败再退回本地文件。"""
    if from_origin:
        try:
            out = subprocess.run(
                ["git", "show", "origin/main:%s" % os.path.relpath(path, BASE).replace(os.sep, "/")],
                cwd=BASE, capture_output=True, check=True, timeout=120,
            )
            return json.loads(out.stdout.decode("utf-8-sig")), "origin/main"
        except Exception as exc:  # noqa: BLE001
            print("[health] git show origin/main 失败(%s)，退回本地文件" % exc)
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh), "local"


def http_json(url, timeout=30):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "newsradar-health")
    req.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


def anomaly(item, evidence, impact, action):
    return {"item": item, "evidence": evidence, "impact": impact, "action": action}


def check_freshness(data, now):
    updated = parse_cn(data.get("updated_at"))
    if updated is None:
        return [anomaly("新鲜度", "prices.json 没有可解析的 updated_at",
                        "无法判断行情是否为最新，重算档位会落空",
                        "检查 fetch.yml 最近一次 run 是否失败")]
    age = (now - updated).total_seconds() / 60.0
    trading = 8 <= now.hour < 23
    limit = FRESH_LIMIT_TRADING if trading else FRESH_LIMIT_IDLE
    if age > limit:
        return [anomaly(
            "新鲜度",
            "updated_at=%s，距今 %.0f 分钟（%s阈值 %d 分钟）"
            % (data.get("updated_at"), age, "盘中" if trading else "非盘中", limit),
            "手机端看到的是旧行情，打板进场价会失真",
            "手动触发 fetch.yml 重跑，并查看上一次 run 的失败源",
        )]
    return []


def check_board_consistency(data, row_index, now):
    issues = []
    # 午板要等“午后重算”跑过才会有。判断基准必须用数据快照自己的生成时间，
    # 而不是体检的运行时间——体检经常被 GitHub 延迟到 09:xx 才跑，用运行时间会天天误报。
    _upd = parse_cn(data.get("updated_at"))
    _data_hour = (_upd or now).hour
    for slot, label in (("daily_pick", "晨板"), ("afternoon_pick", "午板")):
        pick = data.get(slot)
        # 空壳（只有 date/session/ruleset，没有品种）也要当作“缺失”
        if not isinstance(pick, dict) or not pick or not (pick.get("name") or pick.get("symbol")):
            # 午板由“午后重算”生成，北京 10:00 之后才会有；早上为空是正常状态，
            # 否则每天 07:40 那次体检都会误报两条。
            if slot == "afternoon_pick" and _data_hour < 11:
                continue
            issues.append(anomaly(
                "板面自洽",
                "%s(%s) 缺失" % (label, slot),
                "该场次没有可推送的打板标的",
                "检查 fetch_prices.py 的选取逻辑与上游数据源",
            ))
            continue
        price = pick.get("price")
        anchor = pick.get("anchor")
        name = "%s %s" % (label, pick.get("name") or pick.get("symbol"))

        plan = pick.get("plan")
        if isinstance(plan, dict) and plan.get("entry") is not None:
            # ruleset 3 之后：只出一个方向，进场/止损/止盈都在 plan 里
            direct = plan.get("dir")
            entry = plan.get("entry")
            sl = plan.get("sl")
            tp = plan.get("tp")
            if price is None:
                issues.append(anomaly(
                    "板面自洽", "%s 缺少 price（plan.entry=%s）" % (name, fmt(entry)),
                    "没有现价基准，进场是否可达无法判断",
                    "检查该品种实时行情抓取",
                ))
            elif direct == "short":
                bad = []
                if entry > price + EPS:
                    bad.append("做空进场 %s 高于现价 %s" % (fmt(entry), fmt(price)))
                if sl is not None and sl < price - EPS:
                    bad.append("止损 %s 低于现价 %s（方向反了）" % (fmt(sl), fmt(price)))
                if tp is not None and tp > price + EPS:
                    bad.append("止盈 %s 高于现价 %s（方向反了）" % (fmt(tp), fmt(price)))
                if bad:
                    issues.append(anomaly(
                        "板面自洽", "%s %s" % (name, "；".join(bad)),
                        "方向与价格结构自相矛盾，照单下单可能立刻反向",
                        "核对 ATR/确认位计算，必要时降级为观望",
                    ))
            elif direct == "long":
                bad = []
                if entry < price - EPS:
                    bad.append("做多进场 %s 低于现价 %s" % (fmt(entry), fmt(price)))
                if sl is not None and sl > price + EPS:
                    bad.append("止损 %s 高于现价 %s（方向反了）" % (fmt(sl), fmt(price)))
                if tp is not None and tp < price - EPS:
                    bad.append("止盈 %s 低于现价 %s（方向反了）" % (fmt(tp), fmt(price)))
                if bad:
                    issues.append(anomaly(
                        "板面自洽", "%s %s" % (name, "；".join(bad)),
                        "方向与价格结构自相矛盾，照单下单可能立刻反向",
                        "核对 ATR/确认位计算，必要时降级为观望",
                    ))
            else:
                issues.append(anomaly(
                    "板面自洽", "%s plan.dir=%s 不是 long/short" % (name, fmt(direct)),
                    "无法判断该按哪个方向推送",
                    "检查 plan 生成时的方向字段",
                ))
        else:
            # ruleset 3 起，多空双轨已删除，只应存在 plan；缺 plan 即无法执行
            issues.append(anomaly(
                "板面自洽",
                "%s 缺少 plan（方向/进场/止损/止盈），price=%s" % (name, fmt(price)),
                "没有可执行的进场方案，无法照单下单",
                "检查该品种 ATR 计算与 plan 生成（fetch_prices.build_hf_picks）",
            ))
        if price is not None and (anchor is None or abs(anchor - price) > EPS):

            issues.append(anomaly(
                "板面自洽",
                "%s anchor=%s 与 price=%s 不一致" % (name, fmt(anchor), fmt(price)),
                "锚点被改写会让回踩/追强两档错位",
                "检查 anchor 赋值链路（spot/future/last_settle 优先序）",
            ))

        pullback = pick.get("pullback")
        row = row_index.get(pick.get("symbol")) or {}
        if pullback is not None:
            low, high = row.get("day_low"), row.get("day_high")
            if low is None or high is None:
                issues.append(anomaly(
                    "板面自洽",
                    "%s pullback=%s，但缺少当日 day_low/day_high" % (name, fmt(pullback)),
                    "回踩档是否可达无法核验",
                    "检查该品种当日行情抓取是否成功",
                ))
            elif not (low - EPS <= pullback <= high + EPS):
                issues.append(anomaly(
                    "板面自洽",
                    "%s pullback=%s 不在当日区间 [%s, %s]"
                    % (name, fmt(pullback), fmt(low), fmt(high)),
                    "回踩档当天不可能成交，等于给了个假计划",
                    "把 pullback 夹到当日区间内或直接置 null",
                ))
    return issues


def check_pick_precision(data):
    picks = [p for p in (data.get("hf_picks") or []) if isinstance(p, dict)]
    if not picks:
        return []
    issues = []
    clean = [p for p in picks if p.get("tier") == 1 and not p.get("day_conflict")]
    if len(picks) > 5:
        issues.append(anomaly(
            "候选项精度",
            "hf_picks 共 %d 条（上限 5）：%s" % (len(picks), "、".join(p.get("name") or "?" for p in picks)),
            "候选列表过长，盯盘时等于没有重点",
            "只保留最精一级，其余降到 hf_pool 备选",
        ))
    if clean:
        mixed = [p for p in picks if p.get("tier") != 1 or p.get("day_conflict")]
        if mixed:
            issues.append(anomaly(
                "候选项精度",
                "hf_picks 已有一级候选(%s)，却混入 %s"
                % ("、".join(p.get("name") or "?" for p in clean),
                   "、".join("%s(tier%s)" % (p.get("name") or "?", p.get("tier")) for p in mixed)),
                "一级候选被低级别稀释，推送顺序失去意义",
                "hf_picks 仅保留一级候选，低级别留在 hf_pool",
            ))
    elif len(picks) > 1:
        issues.append(anomaly(
            "候选项精度",
            "全部候选都带 day_conflict（%s），应只保留一条，实际 %d 条"
            % ("、".join(p.get("name") or "?" for p in picks), len(picks)),
            "无干净候选时给多条，等于让用户自己挑冲突标的",
            "无一级候选时只保留唯一一条观察级提示",
        ))
    return issues


def check_afternoon_switch(data):
    daily = data.get("daily_pick") or {}
    afternoon = data.get("afternoon_pick") or {}
    pool = [p for p in (data.get("hf_pool") or []) if isinstance(p, dict)]
    if not daily.get("symbol") or not afternoon.get("symbol"):
        return []
    others = [p for p in pool if p.get("symbol") and p.get("symbol") != daily.get("symbol")]
    if others and afternoon.get("symbol") == daily.get("symbol"):
        return [anomaly(
            "午板换标的",
            "池中还有第二只(%s)，但 afternoon_pick 仍与晨板同品种 %s"
            % ("、".join(p.get("name") or "?" for p in others), daily.get("name") or daily.get("symbol")),
            "午后板没有换标的，等于重复推送同一个进场价",
            "检查午后选取时的池过滤与 tier 排序",
        )]
    return []


def check_cross_source(data, row_index):
    issues = []
    picks = []
    for slot in ("daily_pick", "afternoon_pick"):
        pick = data.get(slot)
        if isinstance(pick, dict) and pick.get("symbol"):
            picks.append((slot, pick))
    for pick in (data.get("hf_picks") or []):
        if isinstance(pick, dict) and pick.get("symbol"):
            picks.append(("hf_picks", pick))

    flagged = [
        row for row in (data.get("prices") or [])
        if isinstance(row, dict) and isinstance(row.get("cross_source_dev_pct"), (int, float))
        and row["cross_source_dev_pct"] > SPOT_DEV_LIMIT
    ]
    for row in flagged:
        symbol = row.get("symbol")
        for slot, pick in picks:
            if pick.get("symbol") != symbol:
                continue
            conflict = pick.get("day_conflict") or ""
            if "数据源冲突" not in conflict or pick.get("day_ma") is not None:
                issues.append(anomaly(
                    "跨源冲突标注",
                    "%s 偏离 %.1f%%（%s），但 %s/%s 的 day_conflict=%s、day_ma=%s"
                    % (row.get("name") or symbol, row["cross_source_dev_pct"],
                       row.get("source") or "多源", slot, pick.get("name") or symbol,
                       conflict or "(空)", fmt(pick.get("day_ma"))),
                    "源冲突品种被当成干净标的推送，进场价可能来自错源",
                    "补上「数据源冲突」前缀并把 day_ma 置 null",
                ))

    for row in (data.get("prices") or []):
        if not isinstance(row, dict):
            continue
        basis, spot, settle = row.get("basis"), row.get("spot"), row.get("last_settle")
        if None in (basis, spot, settle) or settle == 0:
            continue
        err = abs(basis - (spot - settle))
        if err > BASIS_TOLERANCE:
            issues.append(anomaly(
                "跨源冲突标注",
                "%s basis=%s 与 spot-last_settle=%.2f 相差 %.2f（阈值 %.2f）"
                % (row.get("name") or row.get("symbol"), fmt(basis), spot - settle, err, BASIS_TOLERANCE),
                "基差口径不一致，现货与期货可能来自不同交易日",
                "核对 spot_as_of 与 last_settle 的取数日",
            ))
    return issues


# 主推档（错过=手机端该场推送没有新数据）与常规更新档（错过=数据变旧，由「新鲜度」兜底）
PRIMARY_GROUPS = [
    ("早盘打板", "03:37"),
    ("午后板", "11:43"),
    ("晚盘打板", "20:23"),
]
REGULAR_SLOTS = ["00:07", "02:00", "06:00", "08:00", "10:00", "14:00", "18:00", "22:00"]
PRIMARY_DEADLINE_MIN = 60   # 主推档起 60 分钟内必须有 run（含 04:00/04:12 等兜底档）
PRIMARY_NOTE_MIN = 30       # 30~60 分钟属于 GitHub 排队延迟，只提示
REGULAR_DEADLINE_MIN = 90   # 常规档 90 分钟内要有 run
REGULAR_NOTE_MIN = 45


def _slot_time(now, slot, day_offset):
    hour, minute = (int(x) for x in slot.split(":"))
    return (now - timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def check_schedule(now, api_json=None):
    """对照 cron 计划，检查最近 24 小时是否漏档/明显延误。"""
    if api_json is None:
        try:
            api_json = http_json(
                "https://api.github.com/repos/%s/actions/workflows/%s/runs?per_page=100"
                % (REPO, WORKFLOW_FILE)
            )
        except Exception as exc:  # noqa: BLE001
            return [anomaly(
                "定时漏档",
                "无法读取 GitHub Actions run 列表：%s" % exc,
                "本项未能核验，漏档情况未知",
                "检查 GITHUB_TOKEN 权限（actions:read）后重跑体检",
            )], []

    runs = []
    for run in (api_json.get("workflow_runs") or []):
        stamp = run.get("run_started_at") or run.get("created_at")
        started = parse_iso_utc(stamp)
        if started is not None:
            runs.append((started, run.get("conclusion"), run.get("html_url")))
    if not runs:
        return [anomaly("定时漏档", "最近没有任何 fetch.yml run 记录",
                        "定时抓取整体未运行，数据必然过期",
                        "检查 workflow 是否被禁用、cron 是否被 GitHub 丢弃")], []

    issues = []
    notes = []
    window_start = now - timedelta(hours=24)

    def upcoming(slot_time, minutes, exclude_after=None):
        hits = [r for r in runs if slot_time <= r[0] <= slot_time + timedelta(minutes=minutes)]
        return min(hits, key=lambda r: r[0]) if hits else None

    def last_before(slot_time):
        earlier = [r for r in runs if r[0] < slot_time]
        return max(earlier, key=lambda r: r[0]) if earlier else None

    for label, slot in PRIMARY_GROUPS:
        for day_offset in (1, 0):
            plan = _slot_time(now, slot, day_offset)
            if plan < window_start or plan > now:
                continue
            hit = upcoming(plan, PRIMARY_DEADLINE_MIN)
            if hit is None:
                prev = last_before(plan)
                issues.append(anomaly(
                    "定时漏档",
                    "%s 计划 %s，但到 %s 仍没有任何 run（最近一次 %s）"
                    % (label, plan.strftime("%m-%d %H:%M"),
                       (plan + timedelta(minutes=PRIMARY_DEADLINE_MIN)).strftime("%H:%M"),
                       prev[0].strftime("%m-%d %H:%M") if prev else "无记录"),
                    "该场没有新数据，手机端这轮推送是旧行情（进场价可能已失效）",
                    "手动触发 fetch.yml 补跑；若反复出现需降低 cron 频率或改用兜底触发",
                ))
            else:
                delay = (hit[0] - plan).total_seconds() / 60.0
                if delay > PRIMARY_NOTE_MIN:
                    notes.append("%s 计划 %s，实际 %s 启动（晚 %.0f 分钟）"
                                 % (label, plan.strftime("%m-%d %H:%M"),
                                    hit[0].strftime("%H:%M"), delay))

    for slot in REGULAR_SLOTS:
        for day_offset in (1, 0):
            plan = _slot_time(now, slot, day_offset)
            if plan < window_start or plan > now:
                continue
            hit = upcoming(plan, REGULAR_DEADLINE_MIN)
            if hit is None:
                prev = last_before(plan)
                issues.append(anomaly(
                    "定时漏档",
                    "常规档 %s 起 %d 分钟内没有任何 run（最近一次 %s）"
                    % (plan.strftime("%m-%d %H:%M"), REGULAR_DEADLINE_MIN,
                       prev[0].strftime("%m-%d %H:%M") if prev else "无记录"),
                    "这一档整体丢失，期间数据不会刷新（数据变旧）",
                    "手动触发 fetch.yml 补跑，并观察该时段 GitHub 队列情况",
                ))
            else:
                delay = (hit[0] - plan).total_seconds() / 60.0
                if delay > REGULAR_NOTE_MIN:
                    notes.append("常规档 %s，实际 %s 启动（晚 %.0f 分钟）"
                                 % (plan.strftime("%m-%d %H:%M"), hit[0].strftime("%H:%M"), delay))

    return issues, sorted(set(notes))


def parse_iso_utc(text):
    """GitHub 的 created_at/run_started_at 是 UTC，转成北京时间（naive）。"""
    if not text:
        return None
    try:
        stamp = datetime.strptime(text.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return stamp + timedelta(hours=8)


def dispatch_fetch():
    """数据过期时顺手触发一次 fetch.yml（云端自愈），返回 (是否成功, 说明)。"""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token:
        return False, "没有可用的 GITHUB_TOKEN，跳过自动补抓"
    url = "https://api.github.com/repos/%s/actions/workflows/%s/dispatches" % (REPO, WORKFLOW_FILE)
    body = json.dumps({"ref": "main"}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "newsradar-health")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status in (201, 202, 204), "HTTP %s" % resp.status
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:160]
        except Exception:  # noqa: BLE001
            pass
        return False, "HTTP %s %s" % (exc.code, detail)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def build_report(data, source, now, skip_schedule=False, dispatch_if_stale=False):
    row_index = {
        row.get("symbol"): row
        for row in (data.get("prices") or [])
        if isinstance(row, dict) and row.get("symbol")
    }
    issues = []
    issues += check_freshness(data, now)
    auto_heal = None
    if dispatch_if_stale and any(issue["item"] == "新鲜度" for issue in issues):
        ok, detail = dispatch_fetch()
        auto_heal = "已自动触发补抓（%s）" % detail if ok else "自动补抓失败：%s" % detail
    issues += check_board_consistency(data, row_index, now)
    issues += check_pick_precision(data)
    issues += check_afternoon_switch(data)
    issues += check_cross_source(data, row_index)
    notes = []
    if not skip_schedule:
        sched_issues, sched_notes = check_schedule(now)
        issues += sched_issues
        notes += sched_notes
    return {
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "data_updated_at": data.get("updated_at"),
        "ok": not issues,
        "anomaly_count": len(issues),
        "anomalies": issues,
        "notes": notes,
        "auto_heal": auto_heal,
        "summary": "全部正常" if not issues else "发现 %d 项异常：%s" % (
            len(issues), "、".join(sorted({i["item"] for i in issues}))
        ),
    }


def write_report(report, out_path):
    history = []
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8-sig") as fh:
                old = json.load(fh)
            if isinstance(old, dict) and isinstance(old.get("history"), list):
                history = old["history"]
        except Exception:  # noqa: BLE001
            history = []
    entry = {k: report[k] for k in ("checked_at", "ok", "anomaly_count", "summary", "data_updated_at")}
    history = (history + [entry])[-90:]
    payload = dict(report)
    payload["history"] = history
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


def append_run_log(path, report):
    rows = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, list):
                rows = loaded
        except Exception:  # noqa: BLE001
            rows = []
    status = "体检 正常" if report["ok"] else "体检 异常 · %d 项" % report["anomaly_count"]
    rows.append({
        "time": report["checked_at"],
        "ts": report["checked_at"],
        "status": status,
        "articles_fetched": -1,
        "detail": report["summary"],
    })
    rows = rows[-60:]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)


def print_report(report):
    print("=" * 60)
    print("「心得」打板数据每日体检 · %s" % report["checked_at"])
    print("数据 updated_at: %s（来源 %s）" % (report["data_updated_at"], report["source"]))
    print("=" * 60)
    if report.get("auto_heal"):
        print(report["auto_heal"])
    if report["ok"]:
        print("全部正常，无需通知。")
        for note in report.get("notes") or []:
            print("提示：%s" % note)
        return
    print(report["summary"])
    print()
    for idx, issue in enumerate(report["anomalies"], 1):
        print("%d. 【%s】%s" % (idx, issue["item"], issue["evidence"]))
        print("   影响：%s" % issue["impact"])
        print("   建议：%s" % issue["action"])
    if report.get("notes"):
        print("\n提示（不算异常）：")
        for note in report["notes"]:
            print("- %s" % note)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", default=os.path.join(BASE, "data", "prices.json"))
    parser.add_argument("--prices-from-origin", action="store_true")
    parser.add_argument("--out", default=os.path.join(BASE, "data", "health.json"))
    parser.add_argument("--run-log", default=os.path.join(BASE, "data", "run_log.json"))
    parser.add_argument("--no-run-log", action="store_true")
    parser.add_argument("--skip-schedule", action="store_true", help="离线自检用：跳过 GitHub API 那一项")
    parser.add_argument("--dispatch-if-stale", action="store_true",
                        help="数据过期时顺手触发一次 fetch.yml 补抓（云端自愈）")
    parser.add_argument("--no-write", action="store_true", help="只打印，不落盘")
    args = parser.parse_args()

    data, source = load_prices(args.prices, args.prices_from_origin)
    report = build_report(data, source, now_cn(), skip_schedule=args.skip_schedule,
                          dispatch_if_stale=args.dispatch_if_stale)
    print_report(report)

    if not args.no_write:
        write_report(report, args.out)
        if not args.no_run_log:
            append_run_log(args.run_log, report)
        print("\n[health] 报告已写入 %s" % args.out)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("## 「心得」打板数据每日体检\n\n")
                fh.write("- 检查时间：%s（北京时间）\n" % report["checked_at"])
                fh.write("- 数据 updated_at：%s\n" % report["data_updated_at"])
                if report.get("auto_heal"):
                    fh.write("- 自愈动作：%s\n" % report["auto_heal"])
                fh.write("- 结论：%s\n\n" % report["summary"])
                for idx, issue in enumerate(report["anomalies"], 1):
                    fh.write("### %d. 【%s】\n%s\n\n- 影响：%s\n- 建议：%s\n\n"
                             % (idx, issue["item"], issue["evidence"], issue["impact"], issue["action"]))
                if report.get("notes"):
                    fh.write("### 提示（不算异常）\n")
                    for note in report["notes"]:
                        fh.write("- %s\n" % note)
                    fh.write("\n")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
