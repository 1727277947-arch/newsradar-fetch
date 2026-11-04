# -*- coding: utf-8 -*-
"""daily_health.py - 「心得」打板数据每日体检（只读，不改交易逻辑）

检查 6 项：
  1 新鲜度        prices.json 的 updated_at 距当前北京时间；盘中(08:00-23:00) >150 分钟、非盘中 >240 分钟 异常
  2 晨/午板自洽   ruleset3 起只有单向 plan：做多 entry>=price 且 sl<entry<tp；做空 entry<=price 且 tp<entry<sl；anchor == price；
                  回踩档 entry_alt 落在当日 [day_low, day_high]；午板在数据时间 <11:00 时为空属正常
  3 候选项要精    hf_picks 只含最精的一级（全部无 day_conflict；全带冲突时只保留一条）；条数 <= 5
  4 午板换标的    hf_pool 里存在与晨板不同品种时，afternoon_pick 不应与 daily_pick 同品种
  5 跨源冲突标注  cross_source_dev_pct > 2 的品种，其 pick 必须带「数据源冲突」前缀且 day_ma 为 null；
                  每行 basis 应约等于 (spot - last_settle)，误差 < 0.51
  6 定时漏档      对照 fetch.yml 的 cron 计划，查最近 24 小时的 workflow run；晚 30 分钟以上只提示，
                  单档漏跑由后续成功 run/数据新鲜度兜底，连续漏档、失败 run 或长期未更新才报异常

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
import re
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

FRESH_LIMIT_TRADING = 150     # 分钟；覆盖 2 小时间隔及 GitHub 常见排队延迟
FRESH_LIMIT_IDLE = 240        # 分钟
QUOTE_LIVE_MAX_AGE = 20       # 只允许用 20 分钟内的同一时点快照对比新浪实时价
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


def snapshot_age_minutes(data, now):
    """返回行情快照距 now 的分钟数；时间缺失或不可解析时返回 None。"""
    updated = parse_cn(data.get("updated_at"))
    if updated is None:
        return None
    return (now - updated).total_seconds() / 60.0


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
    age = snapshot_age_minutes(data, now)
    if age is None:
        return [anomaly("新鲜度", "prices.json 没有可解析的 updated_at",
                        "无法判断行情是否为最新，重算档位会落空",
                        "检查 fetch.yml 最近一次 run 是否失败")]
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


def check_quote_truth(data, row_index, now=None):
    """外部核验：拿「同一合约」的新浪报价复核我们发出去的现价与昨结算。

    这是本项目最容易出错的地方——历史上出过：
      · 用错合约（甲醇连续=MA2701，主力其实是 MA2611，差 13%）
      · 昨结算取了东财主连的 f60（那是前收，不是结算价）
      · 合约乘数写错（沪银 15000，应为 15），保证金放大 1000 倍
    仅靠“内部自洽”永远查不出来，所以这里必须对外部真实行情。"""
    issues = []
    rows = [r for r in (data.get("prices") or []) if isinstance(r, dict)]
    # ---- 1) 合约乘数/保证金合理性（用交易所公开规格做区间判断）----
    MARGIN_LO, MARGIN_HI = 500.0, 200000.0
    for r in rows:
        if r.get("market") != "国内":
            continue
        try:
            mult = float(r.get("contract_mult") or 0)
            mg = float(r.get("est_margin") or 0)
            fut = float(r.get("future") or 0)
        except (TypeError, ValueError):
            continue
        if mg and not (MARGIN_LO <= mg <= MARGIN_HI):
            issues.append(anomaly(
                "外部核验",
                "%s 一手保证金=%s 元，超出合理区间 [%s, %s]"
                % (r.get("name") or r.get("symbol"), fmt(mg), fmt(MARGIN_LO), fmt(MARGIN_HI)),
                "保证金算错会让“十万内能开几手”完全失真",
                "核对 CONTRACT_MULT 与 MARGIN_RATE（沪银应为 15 千克/手）",
            ))
        if mult > 1000 and r.get("name") not in ("沪金", "上海原油"):
            issues.append(anomaly(
                "外部核验",
                "%s 合约乘数=%s 明显偏大（现价 %s）" % (r.get("name") or r.get("symbol"), fmt(mult), fmt(fut)),
                "乘数量纲错误（元/千克写成元/克之类）会导致保证金整体放大",
                "按交易所规格改正 CONTRACT_MULT",
            ))
    # ---- 2) 逐合约向新浪复核现价与昨结算 ----
    # 现价是运行时数据，不能拿几十分钟前甚至几小时前的快照来对。否则正常的
    # 盘中波动会被当成“绑定错合约”。合约乘数/保证金检查仍在上面始终执行。
    age = snapshot_age_minutes(data, now or now_cn())
    if age is None or age > QUOTE_LIVE_MAX_AGE:
        return issues
    targets = []
    for r in rows:
        c = r.get("quote_contract")
        if c:
            targets.append((r.get("name") or c, c, r))
    if not targets:
        return issues
    syms = ["nf_" + c for _, c, _ in targets]
    live = {}
    try:
        for i in range(0, len(syms), 30):
            chunk = syms[i:i+30]
            req = urllib.request.Request("https://hq.sinajs.cn/list=" + ",".join(chunk),
                                         headers={"User-Agent": "Mozilla/5.0",
                                                  "Referer": "https://finance.sina.com.cn/"})
            txt = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "replace")
            for line in txt.splitlines():
                m = re.match(r'var hq_str_(\w+)="(.*)";', line.strip())
                if m and m.group(2):
                    live[m.group(1)] = m.group(2).split(",")
    except Exception as e:
        return issues + [anomaly(
            "外部核验", "取新浪逐合约行情失败：%s" % str(e)[:60],
            "现价/昨结算无法与外部对账", "检查运行环境到 hq.sinajs.cn 的网络")]
    if not live:
        return issues + [anomaly(
            "外部核验", "新浪逐合约行情返回为空",
            "现价/昨结算无法与外部对账", "稍后重试或检查 hq.sinajs.cn 可用性")]
    for name, c, r in targets:
        f = live.get("nf_" + c)
        if not f or len(f) < 11:
            continue
        try:
            ext_last = float(f[8]); ext_settle = float(f[10])
        except (ValueError, IndexError):
            continue
        if ext_settle <= 0:
            ext_settle = float(f[9]) if len(f) > 9 and f[9] else 0.0
        try:
            our_last = float(r.get("future") or 0); our_settle = float(r.get("last_settle") or 0)
        except (TypeError, ValueError):
            continue
        if our_last > 0 and ext_last > 0:
            d = abs(our_last - ext_last) / ext_last * 100.0
            if d > 0.5:
                issues.append(anomaly(
                    "外部核验",
                    "%s 现价 我们=%s 新浪(%s)=%s 偏差 %.2f%%" % (name, fmt(our_last), c, fmt(ext_last), d),
                    "推送的现价与外部行情对不上，进场价不可信",
                    "检查该合约的绑定/取数链路",
                ))
        if our_settle > 0 and ext_settle > 0:
            d = abs(our_settle - ext_settle) / ext_settle * 100.0
            if d > 0.5:
                issues.append(anomaly(
                    "外部核验",
                    "%s 昨结算 我们=%s 新浪(%s)=%s 偏差 %.2f%%" % (name, fmt(our_settle), c, fmt(ext_settle), d),
                    "昨结错会让涨跌幅/基差/方向判定整体偏",
                    "昨结算必须取该合约的结算价，不能用前收替代",
                ))
    return issues

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


# 主推档标签用于报告；单次未命中不直接报错，避免 GitHub 排队/丢一档造成每日噪音。
PRIMARY_GROUPS = [
    ("早盘打板", "03:37"),
    ("午后板", "11:43"),
    ("晚盘打板", "20:23"),
]
PRIMARY_SLOTS = {slot for _, slot in PRIMARY_GROUPS}
SCHEDULE_MATCH_WINDOW_MIN = 180  # 排队超过常见 56~78 分钟的延迟后仍可归属到原计划档
SCHEDULE_NOTE_MIN = 30
SCHEDULE_MISS_SLOT_LIMIT = 3     # 连续 3 个计划触发点都无成功 run，才升级为异常
FAILED_RUN_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "cancelled", "action_required"}


def _slot_time(now, slot, day_offset):
    hour, minute = (int(x) for x in slot.split(":"))
    return (now - timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def check_schedule(now, api_json=None, data_updated_at=None):
    """检查最近 24 小时的失败 run、延误和连续漏档。

    GitHub 的 schedule 本来就可能晚启动几十分钟，偶尔也会丢一个触发点。
    因此晚启动只提示；未命中的单档由后续成功 run 和 prices.json 的 updated_at
    兜底，只有连续多个计划点都没有成功 run 才升级为异常。
    """
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
        if started is not None and started <= now:
            runs.append((started, run.get("conclusion"), run.get("html_url")))
    if not runs:
        return [anomaly("定时漏档", "最近没有任何 fetch.yml run 记录",
                        "定时抓取整体未运行，数据必然过期",
                        "检查 workflow 是否被禁用、cron 是否被 GitHub 丢弃")], []

    issues = []
    notes = []
    window_start = now - timedelta(hours=24)
    successes = [r for r in runs if r[1] == "success"]
    failed = [r for r in runs if r[1] in FAILED_RUN_CONCLUSIONS]
    latest_success = max(successes, key=lambda r: r[0]) if successes else None

    # 失败后已经成功恢复的旧 run 不重复报；最后一次成功之后仍有失败，才是现实中尚未恢复的故障。
    unresolved_failed = [
        r for r in failed
        if latest_success is None or r[0] > latest_success[0]
    ]
    if unresolved_failed:
        last = max(unresolved_failed, key=lambda r: r[0])
        issues.append(anomaly(
            "抓取失败",
            "最近一次成功 run 之后仍有失败：%s 启动，conclusion=%s"
            % (last[0].strftime("%m-%d %H:%M"), last[1]),
            "该次抓取没有产出新数据；若没有后续成功 run，手机端会继续使用旧行情",
            "查看该 run 日志并手动重跑 fetch.yml；成功后本项会自然恢复",
        ))

    entries = []
    for slot in PLANNED_SLOTS:
        for day_offset in (1, 0):
            plan = _slot_time(now, slot, day_offset)
            if plan < window_start or plan > now:
                continue
            label = next((name for name, primary_slot in PRIMARY_GROUPS if primary_slot == slot),
                         "常规档")
            entries.append((plan, label))
    entries.sort()

    # 一次成功 run 只能归属一个计划点，且优先归属最近的前序档。
    # 否则一个晚启动 run 会同时“命中”03:37/04:00/04:12 等多个计划点，
    # 在长时间完全没运行时反而掩盖连续漏档。
    plan_hits = {}
    unassigned = list(range(len(entries)))
    for run in sorted(successes, key=lambda r: r[0]):
        candidates = [
            idx for idx in unassigned
            if entries[idx][0] <= run[0]
            <= entries[idx][0] + timedelta(minutes=SCHEDULE_MATCH_WINDOW_MIN)
        ]
        if not candidates:
            continue
        chosen = max(candidates, key=lambda idx: entries[idx][0])
        plan_hits[chosen] = run
        unassigned.remove(chosen)

    outcomes = []
    for idx, (plan, label) in enumerate(entries):
        hit = plan_hits.get(idx)
        if hit is None:
            deadline = plan + timedelta(minutes=SCHEDULE_MATCH_WINDOW_MIN)
            outcomes.append((plan, label, None, "pending" if deadline > now else "miss"))
            continue
        delay = (hit[0] - plan).total_seconds() / 60.0
        outcomes.append((plan, label, hit, "hit"))
        if delay > SCHEDULE_NOTE_MIN:
            notes.append(
                "%s 计划 %s，实际 %s 启动（晚 %.0f 分钟；该延迟仅提示，不计漏档）"
                % (label, plan.strftime("%m-%d %H:%M"), hit[0].strftime("%H:%M"), delay)
            )

    # 只把连续未命中升级为异常；中间只要有一个成功 run，就说明队列/数据仍有推进。
    miss_groups = []
    current = []
    for outcome in outcomes + [(None, "", None, "break")]:
        if outcome[3] == "miss":
            current.append(outcome[:2])
            continue
        if len(current) >= SCHEDULE_MISS_SLOT_LIMIT:
            miss_groups.append(current)
        elif current:
            notes.append(
                "单次计划未命中：%s；由后续成功 run/数据新鲜度兜底，本轮不单独报错"
                % "、".join(plan.strftime("%m-%d %H:%M") for plan, _ in current)
            )
        current = []

    for group in miss_groups:
        first = group[0][0]
        last = group[-1][0]
        labels = sorted({label for _, label in group})
        issues.append(anomaly(
            "连续漏档",
            "%s 至 %s 连续 %d 个计划触发点均无成功 run（%s；data updated_at=%s）"
            % (first.strftime("%m-%d %H:%M"), last.strftime("%m-%d %H:%M"), len(group),
               "、".join(labels), data_updated_at or "未知"),
            "连续多个触发点消失，数据无法按时刷新，手机端可能持续看到旧行情",
            "手动触发 fetch.yml 补跑，并检查该时段 GitHub Actions 队列与 workflow 状态",
        ))

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
    freshness_issues = check_freshness(data, now)
    auto_heal = None
    notes = []
    if dispatch_if_stale and freshness_issues:
        ok, detail = dispatch_fetch()
        if ok:
            auto_heal = "已自动触发补抓（%s），数据恢复中" % detail
            notes.append("行情快照超过新鲜度阈值，已触发补抓；等待下一次成功 run，本轮不重复标红")
        else:
            auto_heal = "自动补抓失败：%s" % detail
            issues += freshness_issues
            issues.append(anomaly(
                "自动补抓",
                auto_heal,
                "数据已过期且自动补抓未成功，手机端会继续使用旧行情",
                "检查 GITHUB_TOKEN 的 actions:write 权限、workflow_dispatch 开关和 API 状态",
            ))
    else:
        issues += freshness_issues
    issues += check_board_consistency(data, row_index, now)
    issues += check_pick_precision(data)
    issues += check_afternoon_switch(data)
    issues += check_cross_source(data, row_index)
    issues += check_quote_truth(data, row_index, now)
    quote_age = snapshot_age_minutes(data, now)
    if quote_age is not None and quote_age > QUOTE_LIVE_MAX_AGE:
        notes.append(
            "行情快照距体检 %.0f 分钟，已跳过新浪实时价对账，避免用不同时间点误判合约绑定"
            % quote_age
        )
    if not skip_schedule:
        sched_issues, sched_notes = check_schedule(now, data_updated_at=data.get("updated_at"))
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
