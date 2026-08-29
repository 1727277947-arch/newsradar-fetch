# -*- coding: utf-8 -*-
"""
fetch_prices.py - 大宗商品报价抓取（现货 vs 期货 比对）
数据源:
  - api.gold-api.com        国际贵金属(金/银/铂/钯) + 铜 (伦敦现货)
  - oilprice.com/oil-price-charts/   国际能源期货
  - hq.sinajs.cn (新浪)     国内商品期货（贵金属/基本金属/黑色系/农产品/化工/能源）
  - www.100ppi.com (生意社) 国内商品现货
输出: prices.json
  国内品种尽量同时给出 spot(现货) 与 future(期货)，并计算 basis(基差=现货-期货) 与 basis_pct。
  category: 贵金属/基本金属/黑色系/农产品/化工/能源; market: 国际/国内
用法: python fetch_prices.py [输出路径, 默认 ./output/prices.json]
"""
import json, re, ssl, sys, os, time
import urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
TIMEOUT = 15
TODAY = time.strftime("%Y-%m-%d")

# ---- 国内商品期货 (新浪): symbol -> (中文名, 单位, 分类) ----
DOMESTIC = [
    # 贵金属
    ("nf_AU0", "沪金", "元/克",   "贵金属"),
    ("nf_AG0", "沪银", "元/千克", "贵金属"),
    # 基本金属
    ("nf_CU0", "沪铜", "元/吨",   "基本金属"),
    ("nf_AL0", "沪铝", "元/吨",   "基本金属"),
    ("nf_ZN0", "沪锌", "元/吨",   "基本金属"),
    ("nf_NI0", "沪镍", "元/吨",   "基本金属"),
    ("nf_PB0", "沪铅", "元/吨",   "基本金属"),
    ("nf_SN0", "沪锡", "元/吨",   "基本金属"),
    # 黑色系
    ("nf_RB0", "螺纹钢", "元/吨", "黑色系"),
    ("nf_HC0", "热卷",   "元/吨", "黑色系"),
    ("nf_I0",  "铁矿石", "元/吨", "黑色系"),
    ("nf_J0",  "焦炭",   "元/吨", "黑色系"),
    ("nf_JM0", "焦煤",   "元/吨", "黑色系"),
    # 农产品
    ("nf_A0",  "豆一",   "元/吨", "农产品"),
    ("nf_M0",  "豆粕",   "元/吨", "农产品"),
    ("nf_C0",  "玉米",   "元/吨", "农产品"),
    ("nf_Y0",  "豆油",   "元/吨", "农产品"),
    ("nf_P0",  "棕榈油", "元/吨", "农产品"),
    ("nf_CF0", "郑棉",   "元/吨", "农产品"),
    ("nf_SR0", "郑糖",   "元/吨", "农产品"),
    ("nf_OI0", "菜油",   "元/吨", "农产品"),
    ("nf_LH0", "生猪",   "元/吨", "农产品"),
    ("nf_JD0", "鸡蛋",   "元/500千克", "农产品"),
    ("nf_CJ0", "红枣",   "元/吨", "农产品"),
    ("nf_AP0", "苹果",   "元/吨", "农产品"),
    ("nf_PK0", "花生",   "元/吨", "农产品"),
    ("nf_CS0", "玉米淀粉", "元/吨", "农产品"),
    # 化工 / 能源化工
    ("nf_TA0", "PTA",    "元/吨", "化工"),
    ("nf_MA0", "甲醇",   "元/吨", "化工"),
    ("nf_EG0", "乙二醇", "元/吨", "化工"),
    ("nf_PP0", "聚丙烯", "元/吨", "化工"),
    ("nf_L0",  "塑料",   "元/吨", "化工"),
    ("nf_V0",  "PVC",    "元/吨", "化工"),
    ("nf_EB0", "苯乙烯", "元/吨", "化工"),
    ("nf_UR0", "尿素",   "元/吨", "化工"),
    ("nf_FG0", "玻璃",   "元/吨", "化工"),
    ("nf_SA0", "纯碱",   "元/吨", "化工"),
    ("nf_BU0", "沥青",   "元/吨", "能源"),
    ("nf_FU0", "燃料油", "元/吨", "能源"),
    ("nf_PG0", "液化气", "元/吨", "能源"),
    # 黑色系补充
    ("nf_SF0", "硅铁", "元/吨", "黑色系"),
    ("nf_SM0", "锰硅", "元/吨", "黑色系"),
    ("nf_SS0", "不锈钢", "元/吨", "黑色系"),
    ("nf_WR0", "线材", "元/吨", "黑色系"),
    # 农产品补充
    ("nf_RU0", "橡胶", "元/吨", "农产品"),
    ("nf_RM0", "菜粕", "元/吨", "农产品"),
    ("nf_CY0", "棉纱", "元/吨", "农产品"),
    ("nf_B0",  "豆二", "元/吨", "农产品"),
    # 能源补充
    ("nf_SC0", "上海原油", "元/桶", "能源"),
    ("nf_LU0", "低硫燃料油", "元/吨", "能源"),
    # 化工补充
    ("nf_PF0", "短纤", "元/吨", "化工"),
    ("nf_PX0", "对二甲苯", "元/吨", "化工"),
    ("nf_SH0", "烧碱", "元/吨", "化工"),
    ("nf_SP0", "纸浆", "元/吨", "化工"),
    # 新能源金属(有色)
    ("nf_SI0", "工业硅", "元/吨", "基本金属"),
    ("nf_LC0", "碳酸锂", "元/吨", "基本金属"),
]

# 生意社(100ppi) 现货页名称 -> 我的品种 key (用于现货/期货比对，仅取单位一致的品种)
SPOT_MAP = {
    "黄金": "AU0", "白银": "AG0",
    "铜": "CU0", "铝": "AL0", "锌": "ZN0", "铅": "PB0", "镍": "NI0", "锡": "SN0",
    "螺纹钢": "RB0", "热轧卷板": "HC0", "铁矿石": "I0", "焦炭": "J0", "焦煤": "JM0",
    "线材": "WR0", "不锈钢": "SS0", "硅铁": "SF0", "锰硅": "SM0",
    "豆一": "A0", "豆粕": "M0", "玉米": "C0", "豆油": "Y0", "棕榈油": "P0",
    "棉花": "CF0", "白糖": "SR0", "菜籽油OI": "OI0", "菜籽粕": "RM0",
    "天然橡胶": "RU0", "棉纱": "CY0",
    "PTA": "TA0", "甲醇MA": "MA0", "乙二醇": "EG0", "聚丙烯": "PP0", "聚乙烯": "L0",
    "聚氯乙烯": "V0", "苯乙烯": "EB0", "尿素": "UR0", "纯碱": "SA0",
    "涤纶短纤": "PF0", "PX": "PX0", "纸浆": "SP0",
    "石油沥青": "BU0", "燃料油": "FU0", "液化石油气": "PG0",
    "工业硅": "SI0", "碳酸锂": "LC0",
    "苹果": "AP0",
    # 现货单位与期货不一致，需换算后才能比对基差
    "生猪": "LH0", "鸡蛋": "JD0",
}

# 生意社现货单位换算系数(乘到元/吨或元/500千克，匹配期货单位)
SPOT_SCALE = {
    "生猪": 1000.0,   # 现货 元/公斤 -> 元/吨
    "鸡蛋": 500.0,    # 现货 元/公斤 -> 元/500千克
}

ORDER = ["XAU","XAG","XPT","XPD","AU0","AG0",
         "HG","CU0","AL0","ZN0","NI0","PB0","SN0","SI0","LC0",
         "RB0","HC0","I0","J0","JM0","SF0","SM0","SS0","WR0",
         "WTI-Crude","Brent-Crude","Natural-Gas","Gasoline","Heating-Oil","FU0","BU0","SC0","LU0",
         "A0","B0","M0","RM0","C0","Y0","P0","CF0","SR0","OI0","RU0","CY0",
         "LH0","JD0","CJ0","AP0","PK0","CS0",
         "TA0","MA0","EG0","PP0","L0","V0","EB0","UR0","FG0","SA0","PG0","PF0","PX0","SH0","SP0"]


def https(url, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    ctx = ssl.create_default_context()
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx).read()
    except ssl.CertificateError:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx).read()


def enc(text):
    try:
        return text.decode("utf-8")
    except Exception:
        return text.decode("gbk", "replace")


def pct(prev, cur):
    try:
        if prev and prev > 0:
            return round((cur - prev) / prev * 100.0, 2)
    except Exception:
        pass
    return 0.0


# ---------------- 国际贵金属/铜 (现货) ----------------
def fetch_metals():
    out = []
    for sym, name, unit, cat in [("XAU","黄金","美元/盎司","贵金属"),
                                 ("XAG","白银","美元/盎司","贵金属"),
                                 ("XPT","铂金","美元/盎司","贵金属"),
                                 ("XPD","钯金","美元/盎司","贵金属"),
                                 ("HG","铜","美元/磅","基本金属")]:
        try:
            d = json.loads(enc(https("https://api.gold-api.com/price/" + sym)))
            price = float(d.get("price", 0.0) or 0.0)
            out.append({
                "symbol": sym, "name": name, "unit": unit, "quote_ccy": "USD",
                "category": cat, "market": "国际", "kind": "spot",
                "spot": round(price, 4), "future": None, "basis": None, "basis_pct": None,
                "change": 0.0, "change_pct": 0.0, "trend": "flat",
                "source": "gold-api.com(伦敦现货)", "note": "伦敦现货",
            })
        except Exception as e:
            print("[WARN] gold-api", sym, str(e)[:60])
            time.sleep(0.4)
    return out


# ---------------- 国际能源 (期货) ----------------
def fetch_energy():
    html_text = enc(https("https://oilprice.com/oil-price-charts/", "text/html"))
    out = []
    omp = {"WTI-Crude": ("WTI原油","美元/桶"), "Brent-Crude": ("布伦特原油","美元/桶"),
           "Natural-Gas": ("天然气","美元/百万英热"), "Gasoline": ("汽油","美元/加仑"),
           "Heating-Oil": ("取暖油","美元/加仑")}
    tr_pat = re.compile(r"<tr[^>]*data-name='([^']+)'[^>]*>.*?</tr>", re.S)
    row_pat = re.compile(
        r"<td class='last_price' data-price='([^']+)'>[^<]*</td>"
        r"<td[^>]*class='(?:change_up|change_down)[^']*'[^>]*>([^<]*)</td>"
        r"<td[^>]*class='(?:change_up|change_down)[^']*'[^>]*>([^<]*?)<%?", re.S)
    for tr in tr_pat.finditer(html_text):
        name = tr.group(1)
        if name not in omp:
            continue
        rr = row_pat.search(tr.group(0))
        if not rr:
            continue
        price = float(rr.group(1))
        try:
            chg = float(rr.group(2).strip())
            pctv = float(rr.group(3).strip().replace("%", ""))
        except ValueError:
            chg, pctv = 0.0, 0.0
        trend = "up" if chg > 0.0001 else ("down" if chg < -0.0001 else "flat")
        cn, unit = omp[name]
        out.append({
            "symbol": name, "name": cn, "unit": unit, "quote_ccy": "USD", "category": "能源",
            "market": "国际", "kind": "future", "spot": None, "future": round(price, 4),
            "basis": None, "basis_pct": None, "change": chg, "change_pct": pctv, "trend": trend,
            "source": "oilprice.com(期货)", "note": "期货价格(延迟)",
        })
    return out


# ---------------- 国内期货 (新浪) ----------------
def fetch_domestic_futures():
    syms = ",".join(s for s, _, _, _ in DOMESTIC)
    req = urllib.request.Request(
        "https://hq.sinajs.cn/list=" + syms,
        headers={"User-Agent": UA, "Accept": "application/javascript",
                 "Referer": "https://finance.sina.com.cn/"})
    ctx = ssl.create_default_context()
    text = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx).read()
    text = text.decode("gbk", "replace")
    out = {}
    tmp = re.compile(r"hq_str_(\w+)=\"([^\"]*)\"")
    for m in tmp.finditer(text):
        sid = m.group(1)
        f = m.group(2).split(",")
        if len(f) < 15 or not f[7]:
            continue
        key = sid[3:]  # nf_AU0 -> AU0
        entry = next((e for e in DOMESTIC if e[0] == sid), None)
        if not entry:
            continue
        _, cn, unit, cat = entry
        try:
            price = float(f[7])
            prior = float(f[2]) if f[2] else 0.0
            last_settle = float(f[2]) if f[2] else 0.0
        except ValueError:
            continue
        chg = round(price - prior, 4) if prior else 0.0
        pctv = pct(prior, price)
        trend = "up" if chg > 0.0001 else ("down" if chg < -0.0001 else "flat")
        out[key] = {
            "symbol": key, "name": cn, "unit": unit, "quote_ccy": "CNY", "category": cat,
            "market": "国内", "kind": "future", "future": round(price, 4),
            "last_settle": round(last_settle, 4),
            "change": chg, "change_pct": pctv, "trend": trend,
            "source": "新浪财经(期货)", "note": "国内期货",
        }
    return out


# ---------------- 国内现货 (生意社 100ppi) ----------------
def fetch_spot_shensheng():
    ctx = ssl.create_default_context()
    out = {}
    # 从今天往前找最近有数据的交易日（生意社页面滞后一天）
    for back in range(0, 8):
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() - back * 86400))
        try:
            req = urllib.request.Request(
                "https://www.100ppi.com/sf2/day-" + day + ".html",
                headers={"User-Agent": UA, "Accept": "text/html"})
            b = urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx).read().decode("utf-8", "replace")
        except Exception:
            continue
        rows = re.findall(r"<tr align=\"center\".*?</tr>", b, re.S)
        if not rows:
            continue
        out.clear()
        for r in rows:
            cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").replace("&amp;", "&").strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if len(cells) < 2:
                continue
            name = cells[0]
            try:
                price = float(cells[1])
            except ValueError:
                continue
            spot_key = SPOT_MAP.get(name)
            if spot_key:
                scale = SPOT_SCALE.get(name, 1.0)
                out[spot_key] = round(price * scale, 4)
        if out:
            break
    return out


def compute_guide(item):
    """每日购买策略：把28条期货买卖纪律量化为止损/止盈/风控的具体数值。

    纪律->数值落地：
      - 规则1/单次风险<=资本1/3：止损宽度固定 risk_pct（默认2%），仓位自行控制在该范围内
      - 规则15/盈亏比：止盈距离/止损距离 >=3:1（信号越强 RR 越高，可达5:1、8:1）
      - 规则20/金字塔加仓：按 10/10/20/30/50 累计头寸，给出5档分批建仓价位
      - 规则4/10/16/移动止损：盈利后止损上移至成本价附近保护利润
      - 规则5/18/19/25/顺势、不猜顶底、不逆市：方向仅由现货基差+昨日动量判定
    """
    if item.get("market") != "国内":
        return None
    last_settle = item.get("last_settle") or item.get("future") or 0.0
    basis = item.get("basis_pct")          # 现货 vs 昨结
    yc = item.get("yesterday_chg")         # 昨日涨跌%（隔日）
    score = 0
    tags = []
    # 1) 现货升贴水（现货 - 昨结）：主导方向
    if basis is not None and abs(basis) <= 20:
        if basis >= 0.8: score += 2; tags.append("现货升水%.1f%%" % basis)
        elif basis >= 0.3: score += 1; tags.append("现货小幅升水%.1f%%" % basis)
        elif basis <= -0.8: score -= 2; tags.append("现货贴水%.1f%%" % basis)
        elif basis <= -0.3: score -= 1; tags.append("现货小幅贴水%.1f%%" % basis)
        else: tags.append("期现基本持平")
    else:
        tags.append("缺现货参考")
    # 2) 昨日收盘动量：方向辅助
    if yc is not None:
        if yc >= 0.8: score += 1; tags.append("昨日上涨%.1f%%" % yc)
        elif yc <= -0.8: score -= 1; tags.append("昨日下跌%.1f%%" % yc)
    direction = 1 if score >= 2 else (-1 if score <= -2 else 0)
    label = "做多" if direction == 1 else ("做空" if direction == -1 else "观望")
    strength = abs(score)

    anchor = item.get("spot") or last_settle or 0.0
    def numf(v):
        return None if v is None else round(v, 3)
    def fmt(v):
        if v is None: return "-"
        vv = float(v)
        return ("%g" % vv) if abs(vv) >= 1000 else ("%.3f" % vv)

    # 盈亏比 RR 与单次风险（规则15+规则1）：止损宽度2%，止盈=RISK_PCT*RR
    RISK_PCT = 0.02
    RR = 3
    if strength >= 4: RR = 4
    if strength >= 5: RR = 5
    if strength >= 6: RR = 8      # 高盈亏比 8:1

    entry = tp = sl = support = resist = None
    if anchor:
        entry = anchor
        if direction == 1:
            sl = anchor * (1 - RISK_PCT)
            tp = anchor * (1 + RISK_PCT * RR)
        elif direction == -1:
            sl = anchor * (1 + RISK_PCT)
            tp = anchor * (1 - RISK_PCT * RR)
        else:
            support = anchor * (1 - RISK_PCT * 1.5)
            resist = anchor * (1 + RISK_PCT * 1.5)

    # 金字塔分批建仓：5档累计头寸 10/10/20/30/50（规则20），价位从 entry 顺方向到 tp 均分
    pyramid = None
    if entry and tp is not None and (direction == 1 or direction == -1):
        ratios = [10, 10, 20, 30, 50]
        levels = []
        for k in range(5):
            t = k / 4.0
            price = entry + (tp - entry) * t
            levels.append(round(price, 3))
        pyramid = {"ratio": ratios, "levels": levels,
                   "note": "金字塔分批建仓，累计头寸按10/10/20/30/50递增；回撤至支撑/跌破止损则停止加仓"}

    move_stop = "盈利后将止损上移至开仓成本附近，保护账面利润（移动止损，不平仓）"

    if direction == 1:
        action = "短线看多"
        reason = ("现价%s，盈亏比1:%d(止盈%s/止损%s)，单次风险≤1/3资本；顺势做多：开仓%s，止盈%s，止损%s" %
                  (fmt(anchor), RR, fmt(tp), fmt(sl), fmt(entry), fmt(tp), fmt(sl)))
    elif direction == -1:
        action = "短线看空"
        reason = ("现价%s，盈亏比1:%d(止盈%s/止损%s)，单次风险≤1/3资本；顺势做空：开仓%s，止盈%s，止损%s" %
                  (fmt(anchor), RR, fmt(tp), fmt(sl), fmt(entry), fmt(tp), fmt(sl)))
    else:
        action = "区间观望"
        reason = ("方向不明(%s)；回踩支撑%s附近轻仓做多，反弹压力%s附近轻仓做空，盈亏比≥3:1" %
                  ("、".join(tags), fmt(support), fmt(resist)))

    g = {
        "direct": direction, "label": label, "action": action,
        "strength": strength, "reason": reason,
        "anchor": numf(anchor) if anchor else None,
        "entry": numf(entry) if entry else None,
        "basis_label": "多" if basis is not None and basis > 0 else ("空" if basis is not None and basis < 0 else "平"),
        "rr": RR,
        "risk_pct": round(RISK_PCT * 100, 1),
        "move_stop": move_stop,
    }
    if pyramid:
        g["pyramid"] = pyramid
    if direction == 1 or direction == -1:
        g["tp"] = numf(tp); g["sl"] = numf(sl)
    else:
        g["support"] = numf(support); g["resist"] = numf(resist)
    return g


def build(out_path):
    items = []

    # 国际现货金属
    try:
        items += fetch_metals()
    except Exception as e:
        print("[WARN] metals:", str(e)[:70])

    # 国内期货(新浪)
    fut = {}
    try:
        fut = fetch_domestic_futures()
    except Exception as e:
        print("[WARN] domestic futures:", str(e)[:70])

    # 国内现货(生意社)
    spot = {}
    try:
        spot = fetch_spot_shensheng()
    except Exception as e:
        print("[WARN] domestic spot:", str(e)[:70])

    # 昨日结算快照：用于跨日计算“昨日涨跌”（对比昨日结算 vs 前日结算）
    state_path = os.path.join(BASE, "output", "prices_state.json")
    prev_state = {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            ps = json.load(f)
            prev_state = ps if isinstance(ps, dict) else {}
    except Exception:
        pass
    prev_date = str(prev_state.pop("_date", ""))
    today = time.strftime("%Y-%m-%d")

    for key, fut_item in fut.items():
        sp = spot.get(key)
        item = dict(fut_item)
        item["spot"] = sp
        # 基差用“现货 vs 昨日结算”衡量，更能反映昨日收盘后现货对今日的引领
        last_settle = fut_item.get("last_settle") or fut_item.get("future") or 0.0
        if sp and last_settle:
            item["basis"] = round(sp - last_settle, 2)
            item["basis_pct"] = pct(last_settle, sp)
            item["kind"] = "both"
            item["note"] = "现货vs昨日结算(基差)"
            item["source"] = "新浪财经+生意社"
        else:
            item["basis"] = None
            item["basis_pct"] = None
            item["note"] = "国内期货(现货未取到)"
        # 昨日涨跌：本次昨结 vs 上次跨日快照中的昨结（仅跨日计算）
        item["yesterday_chg"] = None
        if prev_date and prev_date != today and key in prev_state:
            pv = prev_state[key]
            try:
                pv = float(pv)
                if pv and last_settle:
                    item["yesterday_chg"] = round((last_settle - pv) / pv * 100.0, 2)
            except (TypeError, ValueError):
                pass
        items.append(item)

    # 保存本次昨结快照（含日期）
    new_state = {"_date": today}
    for key, fit in fut.items():
        v = fit.get("last_settle")
        if v:
            new_state[key] = v
    try:
        import os as _os
        _os.makedirs(_os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False)
    except Exception:
        pass

    # 国际能源期货
    try:
        items += fetch_energy()
    except Exception as e:
        print("[WARN] energy:", str(e)[:70])

    items.sort(key=lambda x: ORDER.index(x["symbol"]) if x["symbol"] in ORDER else 999)
    for it in items:
        g = compute_guide(it)
        if g:
            it["guide"] = g
    return items


TRADING_RULES = [
    {"no": 1, "text": "将投机资本分成3份，每次买卖所冒风险不应超过资本的1/3；"},
    {"no": 2, "text": "小心使用止损盘，减低每次出错可能导致的损失；"},
    {"no": 3, "text": "不可过量买卖；限制亏损、放大利润，吃肉吃到底！"},
    {"no": 4, "text": "避免反胜为败：入市后已有利可图时，应将止损盘逐步上移（移动止损），以免因市势反转而引致损失；"},
    {"no": 5, "text": "不可逆市买卖；市势不明朗时，宁可袖手旁观；"},
    {"no": 6, "text": "犹豫不决，不宜入市；"},
    {"no": 7, "text": "买卖疏落而不活跃的市场绝不沾手；"},
    {"no": 8, "text": "只可买卖两至三种商品期货。太多难于兼顾，太少则风险过于集中，两者均不适当；"},
    {"no": 9, "text": "避免限价买卖，否则可能因小失大；"},
    {"no": 10, "text": "入市之后不可随意平仓，可利用止损保障账面利润；"},
    {"no": 11, "text": "考虑将部分资金调走，以备不时之需；"},
    {"no": 12, "text": "不可为蝇头小利而随便入市买卖；"},
    {"no": 13, "text": "不可以加死码：第一注出现亏损即表示入市错误，若强行增仓拉低成本，可能积小错成大错，智者不为；"},
    {"no": 14, "text": "入市之后不可因缺乏耐性等候而胡乱平仓；"},
    {"no": 15, "text": "胜少负多的买卖方式，要设置合理的盈亏比：正常3比1，高盈亏比8比1。切戒；"},
    {"no": 16, "text": "入市之后不可取消止损，只可顺势调整，不可反向调整；"},
    {"no": 17, "text": "买卖次数不宜过于频密：多做多错，且佣金与价位损失会减低获利机会；"},
    {"no": 18, "text": "顺势买卖，顺势而为而不逆势而行；"},
    {"no": 19, "text": "不可贪低买入，亦不可因价高沽空，一切应以趋势而定（不去猜测顶底，让市场证明，不可追涨杀跌）；"},
    {"no": 20, "text": "在适当时候以金字塔式增加持仓数量（加仓比例10%、10%、20%、30%、50%），如商品以活跃成交量突破阻力位；"},
    {"no": 21, "text": "选择升势凌厉的商品期货作为金字塔式买入对象，抛空则反其道而行；"},
    {"no": 22, "text": "买卖错误应即时平仓，切忌买卖其他合约做等仓用途，要敢于认错（市场不会因你亏损而怜悯，也不会因你盈利而夸奖）；"},
    {"no": 23, "text": "不可随便由盈利仓转入亏损仓；每次买卖都要详细策划、理由充分、不违背既定规则；"},
    {"no": 24, "text": "买卖得心应手时请勿随意加码，此时最容易出错；"},
    {"no": 25, "text": "切莫预测市势的顶或底，应由市场自行决定；"},
    {"no": 26, "text": "不可轻信他人意见，除非确信对方的市场知识更高、有值得学习之处；"},
    {"no": 27, "text": "买卖出现亏损时，减低注码；"},
    {"no": 28, "text": "入市错误、出市错误固然不妙；入市正确而出市错误亦会减少获利机会；"},
]
TRADING_RULES_SUMMARY = '上述28条期货买卖规则，乃经十年投机买卖归纳出的戒条，具有实战效用。每次买卖出现亏损时，可检阅这28条规则，看看犯了哪一条，引以为戒。'

if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "output", "prices.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    items = build(out_path)
    obj = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "quote_ccy": "USD/CNY",
        "note": "大宗商品现货/期货参考报价; 国内品种尽量给出现货(生意社)与期货(新浪)及基差(现货-期货), 供参考不作为交易依据",
        "groups": ["贵金属", "基本金属", "黑色系", "能源", "农产品", "化工"],
        "prices": items,
        "trading_rules": TRADING_RULES,
        "rules_summary": TRADING_RULES_SUMMARY,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    both = sum(1 for x in items if x["kind"] == "both")
    domestic = sum(1 for x in items if x["market"] == "国内")
    print("完成: 共 %d 个品种(国内 %d / 国际 %d, 现货期货双价 %d) -> %s" % (
        len(items), domestic, len(items) - domestic, both, out_path))
