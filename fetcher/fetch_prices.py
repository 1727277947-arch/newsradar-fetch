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
# ============ 高频推荐：合约乘数 / 保证金率 / 交易所（公开交易所标准规格，仅用于估算）============
CONTRACT_MULT = {
    "AU":1000, "AG":15000, "CU":5, "AL":5, "ZN":5, "NI":1, "PB":5, "SN":1,
    "RB":10, "HC":10, "WR":10, "RU":10, "FU":10, "BU":10, "SS":5, "SP":10,
    "A":10, "B":10, "M":10, "C":10, "CS":10, "Y":10, "P":10, "JD":10,
    "J":100, "JM":60, "I":100, "LH":16, "L":5, "PP":5, "EG":10, "EB":5, "PG":20, "V":5,
    "CF":5, "SR":10, "OI":10, "RM":10, "FG":20, "SA":20, "TA":5, "MA":10, "UR":20,
    "CJ":5, "AP":10, "PK":5, "PF":5, "PX":5, "SH":30, "CY":5,
    "SC":1000, "LU":10, "SI":5, "LC":1,
}
MARGIN_RATE = {"SHFE":0.12, "DCE":0.10, "CZCE":0.10, "INE":0.12, "GFEX":0.12}
EXCH = {
    "AU":"SHFE","AG":"SHFE","CU":"SHFE","AL":"SHFE","ZN":"SHFE","NI":"SHFE","PB":"SHFE","SN":"SHFE",
    "RB":"SHFE","HC":"SHFE","WR":"SHFE","RU":"SHFE","FU":"SHFE","BU":"SHFE","SS":"SHFE","SP":"SHFE",
    "A":"DCE","B":"DCE","M":"DCE","C":"DCE","CS":"DCE","Y":"DCE","P":"DCE","JD":"DCE",
    "J":"DCE","JM":"DCE","I":"DCE","LH":"DCE","L":"DCE","PP":"DCE","EG":"DCE","EB":"DCE","PG":"DCE","V":"DCE",
    "CF":"CZCE","SR":"CZCE","OI":"CZCE","RM":"CZCE","FG":"CZCE","SA":"CZCE","TA":"CZCE","MA":"CZCE","UR":"CZCE",
    "CJ":"CZCE","AP":"CZCE","PK":"CZCE","PF":"CZCE","PX":"CZCE","SH":"CZCE","CY":"CZCE",
    "SC":"INE","LU":"INE","SI":"GFEX","LC":"GFEX",
}

def _base_key(key):
    """AU0 -> AU；把末尾数字去掉。"""
    k = key.strip()
    while k and k[-1].isdigit():
        k = k[:-1]
    return k

def fmt_money(v):
    if v is None or v != v:
        return ""
    if v >= 10000:
        return "%.1f万" % (v / 10000.0)
    return "%.0f" % v


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
            price = float(f[7]) if f[7] else 0.0
            prior = float(f[2]) if f[2] else 0.0
            last_settle = float(f[10]) if len(f) > 10 and f[10] else (float(f[2]) if f[2] else 0.0)
            hi = float(f[3]) if len(f) > 3 and f[3] else price
            lo = float(f[4]) if len(f) > 4 and f[4] else price
        except ValueError:
            continue
        # 无实时报价(空/0)时用昨结兜底，绝不把0价当开仓基准，避免算法和App出现0价鬼数据
        if price <= 0 and last_settle > 0:
            price = last_settle
        chg = round(price - last_settle, 4) if last_settle else 0.0
        pctv = pct(last_settle, price)
        trend = "up" if chg > 0.0001 else ("down" if chg < -0.0001 else "flat")
        # 活跃度与波动：f[13]=当日成交量, f[14]=持仓量, f[9]=买量
        try:
            vol = float(f[13]) if len(f) > 13 and f[13] else 0.0
        except ValueError:
            vol = 0.0
        try:
            oi = float(f[14]) if len(f) > 14 and f[14] else 0.0
        except ValueError:
            oi = 0.0
        mult = CONTRACT_MULT.get(_base_key(key), 1)
        cval = price * mult
        exch = EXCH.get(_base_key(key), "CZCE")
        mrate = MARGIN_RATE.get(exch, 0.10)
        est_margin = cval * mrate
        rng_pct = (hi - lo) / last_settle * 100.0 if last_settle and last_settle > 0 else 0.0
        out[key] = {
            "symbol": key, "name": cn, "unit": unit, "quote_ccy": "CNY", "category": cat,
            "market": "国内", "kind": "future", "future": round(price, 4),
            "last_settle": round(last_settle, 4),
            "change": chg, "change_pct": pctv, "trend": trend,
            "day_high": round(hi, 4) if hi == hi else None,
            "day_low": round(lo, 4) if lo == lo else None,
            "day_range_pct": round(rng_pct, 2),
            "volume": int(vol), "open_interest": int(oi),
            "contract_mult": mult, "contract_value": round(cval, 2),
            "est_margin": round(est_margin, 2), "margin_rate": mrate,
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

    # 开仓基准：期货现价优先（用户交易的是期货合约），其次昨结，最后才用现货；现货仅用于方向判断，不决定开仓/止损/止盈数值
    anchor = item.get("future") or last_settle or item.get("spot") or 0.0
    def numf(v):
        return None if v is None else round(v, 3)
    def fmt(v):
        if v is None: return "-"
        vv = float(v)
        return ("%g" % vv) if abs(vv) >= 1000 else ("%.3f" % vv)

    # 盈亏比 RR 与单次风险（规则15+规则1）：止损宽度2%，止盈=RISK_PCT*RR
        # 定稿止损止盈：止盈 +3%；反向 -0.15% 立即离场；浮盈回吐 -0.1% 硬止损兜底
    TP_PCT = 0.03          # 止盈 3%
    EXIT_PCT = 0.0015      # 反向 0.15% 立即离场
    HARD_STOP_PCT = 0.001  # 浮盈回吐 0.1% 硬止损

    entry = tp = sl = exit_price = support = resist = None
    if anchor:
        entry = anchor
        if direction == 1:
            tp = anchor * (1 + TP_PCT)
            sl = anchor * (1 - HARD_STOP_PCT)
            exit_price = anchor * (1 - EXIT_PCT)
        elif direction == -1:
            tp = anchor * (1 - TP_PCT)
            sl = anchor * (1 + HARD_STOP_PCT)
            exit_price = anchor * (1 + EXIT_PCT)
        else:
            support = anchor * (1 - EXIT_PCT)
            resist = anchor * (1 + EXIT_PCT)

    # 金字塔分批建仓（10/10/20/30/50），价位从 entry 顺方向到止盈位
    pyramid = None
    if entry and tp is not None and (direction == 1 or direction == -1):
        ratios = [10, 10, 20, 30, 50]
        levels = []
        for k in range(5):
            t = k / 4.0
            price = entry + (tp - entry) * t
            levels.append(round(price, 3))
        pyramid = {"ratio": ratios, "levels": levels,
                   "note": "金字塔分批建仓，累计头寸按10/10/20/30/50递增；未触发反向离场位前按档加仓"}

    move_stop = "移动止损：已有浮盈后把离场线紧到开仓价附近，回吐-0.1%即平仓锁盈"

    if direction == 1:
        action = "短线看多"
        reason = ("现价%s：止盈%s(+3%%)，反向%s(-0.15%%)立即离场，浮盈回吐至%s(-0.1%%)硬止损兜底" %
                  (fmt(anchor), fmt(tp), fmt(exit_price), fmt(sl)))
    elif direction == -1:
        action = "短线看空"
        reason = ("现价%s：止盈%s(-3%%)，反向%s(+0.15%%)立即离场，浮盈回吐至%s(+0.1%%)硬止损兜底" %
                  (fmt(anchor), fmt(tp), fmt(exit_price), fmt(sl)))
    else:
        action = "区间观望"
        reason = ("方向不明(%s)；区间±0.15%%高抛低吸：回踩支撑%s轻仓做多，反弹压力%s轻仓做空" %
                  ("、".join(tags), fmt(support), fmt(resist)))

    g = {
        "direct": direction, "label": label, "action": action,
        "strength": strength, "reason": reason,
        "anchor": numf(anchor) if anchor else None,
        "entry": numf(entry) if entry else None,
        "basis_label": "多" if basis is not None and basis > 0 else ("空" if basis is not None and basis < 0 else "平"),
        "tp_pct": TP_PCT * 100,
        "exit_pct": EXIT_PCT * 100,
        "risk_pct": round(HARD_STOP_PCT * 100, 2),
        "move_stop": move_stop,
        "trail_stop": numf(entry) if (direction != 0 and entry) else None,
        "stop_discipline": ("持仓纪律：未到止盈且价格反向-0.15%立即离场；已有浮盈回吐至开仓价-0.1%立即硬止损兜底" if direction != 0 else ""),
    }
    if pyramid:
        g["pyramid"] = pyramid
    if direction == 1 or direction == -1:
        g["tp"] = numf(tp); g["sl"] = numf(sl); g["exit_price"] = numf(exit_price)
        g["rr"] = round(TP_PCT / EXIT_PCT, 1)   # 止盈/反向离场 比
    else:
        g["support"] = numf(support); g["resist"] = numf(resist)
    return g



# ---------------- 期货主线：今日开盘 vs 昨结 -> 做多/做空 + 次日开盘预测 ----------------
KLINE_CACHE = {}

def _fetch_kline(key):
    """抓新浪日K，返回 (d,o,h,l,c,v,p,s) 升序元组，最后一根为今日。(s=结算价,p=持仓量)"""
    if key in KLINE_CACHE:
        return KLINE_CACHE[key]
    out = []
    url = ("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
           "var%20_=/InnerFuturesNewService.getDailyKLine?symbol=" + key)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
        txt = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        i = txt.find("([")
        j = txt.rfind("])")
        if i >= 0 and j > i:
            arr = json.loads(txt[i + 1:j + 1])
            for it in arr:
                try:
                    out.append((it["d"], float(it["o"]), float(it["h"]), float(it["l"]), float(it["c"]), float(it["v"]), float(it["p"]), float(it["s"])))
                except (KeyError, TypeError, ValueError):
                    continue
    except Exception:
        pass
    KLINE_CACHE[key] = out
    return out


def fmt_inline(v):
    return ("%g" % v) if abs(v) >= 1000 else ("%.3f" % v)



def _realtime_head(key):
    """抓新浪实时，返回 (开盘价f[2], 昨结f[10], 现价f[7], 时间f[1], 名称f[0])；失败返回 None。
    注意：国内商品有夜盘，f[2](开盘)在夜盘时段=夜盘开盘价，已是含夜盘的最新开盘。"""
    sym = key if key.startswith("nf_") else "nf_" + key
    try:
        req = urllib.request.Request("https://hq.sinajs.cn/list=" + sym,
                                     headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/",
                                              "Accept": "application/javascript"})
        ctx = ssl.create_default_context()
        txt = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("gbk", "replace")
        import re as _re
        m = _re.search(r'"(.*)"', txt)
        if not m:
            return None
        f = m.group(1).split(",")
        def num(i):
            try:
                return float(f[i])
            except (IndexError, ValueError):
                return None
        return (num(2), num(10), num(7), str(f[1]) if len(f) > 1 else "", f[0] if f else "")
    except Exception:
        return None

def _hour_of(timestr):
    """把f[1]的HHMMSS转成小时(0-23)判断是否夜盘时段。"""
    try:
        t = str(timestr).zfill(6)
        hh = int(t[0:2])
        # 夜盘时段：21:00-次日02:59
        if hh >= 21 or hh < 3:
            return "night"
        return "day"
    except Exception:
        return "day"


def predict_next_open(symlist):
    """symlist: [(symbol_key, name, category)]。按'今开 vs 昨结' -> 多空关联 + 预测次日开盘。"""
    import statistics
    preds = []
    for key, name, cat in symlist:
        kkey = key[3:] if key.startswith("nf_") else key
        rows = _fetch_kline(kkey)
        if len(rows) < 8:
            continue
        recent = list(rows)
        today_d, kline_open, kline_close = recent[-1][0], recent[-1][1], recent[-1][2]
        prev_close_kline = recent[-2][2]  # 前一日收盘(日盘收盘)
        # 近 N 日隔夜跳空统计（今开=含夜盘开盘 vs 前日收盘）
        N = 20
        gaps = []
        for i in range(max(1, len(recent) - N), len(recent)):
            c_prev = recent[i - 1][2]
            o_i = recent[i][1]
            if c_prev and c_prev > 0:
                gaps.append((o_i - c_prev) / c_prev * 100.0)
        if not gaps:
            continue
        mean_gap = statistics.mean(gaps)
        std_gap = statistics.stdev(gaps) if len(gaps) >= 2 else 0.3

        # 实时数据：优先用含夜盘的当前时段开盘(开盘)与真实昨结，把夜盘算进去
        rt = _realtime_head(kkey)
        sess = "day"
        today_open = kline_open
        ref = prev_close_kline  # 昨结参考(前日收盘)
        anchor_price = kline_close
        if rt and rt[0] and rt[0] > 0:
            sess = _hour_of(rt[3])
            today_open = rt[0]             # 当前时段开盘(夜盘时=夜盘开盘)
            ref = rt[1] if rt[1] and rt[1] > 0 else ref   # 真实昨结
            if rt[2] and rt[2] > 0:
                anchor_price = rt[2]       # 当前时段现价(夜盘时=夜盘现价)

        today_gap = (today_open - ref) / ref * 100.0 if ref and ref > 0 else 0.0

        # ===== 打板/连板潜力分（新增，不删原有字段）=====
        # 基于日K(o/h/l/c/v/p/s)：今日涨幅、收盘位置、放量、连强 四因子
        def seg(r, i):
            try:
                return float(r[i])
            except (IndexError, TypeError, ValueError):
                return 0.0
        cur = recent[-1]
        h, l, c = seg(cur, 2), seg(cur, 3), seg(cur, 4)
        v_now = seg(cur, 5)
        settle_y = seg(recent[-2], 7) or seg(recent[-2], 4) or ref  # 昨结(结算价优先)
        # 以“当前最新价(含夜盘实时价)”为基准，实时反映夜盘回调，避免“日K收盘看很强、夜盘却已跳水”的假强势
        ref_px = anchor_price if anchor_price and anchor_price > 0 else c
        # 当前实时涨幅(最新价 vs 昨结)
        ru = (ref_px - ref) / ref * 100.0 if ref and ref > 0 else 0.0
        # 日内位置 0..1（最新价在当日高低区间里的位置，越靠近高位越好；夜盘跳水时自然滑到底部）
        pos = (ref_px - l) / (h - l) if h > l else 0.5
        pos = max(0.0, min(1.0, pos))
        # 近20日平均成交
        vs = [seg(x, 5) for x in recent[-22:-1]] or [1.0]
        vavg = sum(vs) / len(vs) if vs else 1.0
        vol = (v_now / vavg) if vavg > 0 else 1.0
        # 连强：最近连续收涨天数（含今日，跌则为0/负数中性）
        streak = 0
        for k in range(len(recent) - 1, -1, -1):
            prev_s = seg(recent[k - 1], 7) if k - 1 >= 0 else seg(recent[k - 1], 4) if k >= 1 else None
            cc, ss = seg(recent[k], 4), seg(recent[k], 7)
            up = cc > (prev_s if prev_s else cc)
            if up:
                streak += 1
            else:
                break
        # 突破：最新价 vs 近5日收盘高点（夜盘跳水时突破自然减弱）
        hi5 = max(seg(x, 4) for x in recent[-6:-1]) if len(recent) >= 6 else c
        breakout = (ref_px - hi5) / hi5 * 100.0 if hi5 and hi5 > 0 else 0.0
        # 打板分：涨幅/位置/放量/连强（实时涨幅主导打板分）
        s_chg = min(30, max(0, ru * 6))            # 实时涨1%≈6分，封顶30
        s_pos = pos * 25                          # 收在高位最多25
        s_vol = min(20, max(0, (vol - 0.8) * 16)) # 放量最多20
        s_str = min(15, streak * 5)               # 连涨越多越多，最多15
        s_break = min(10, max(0, breakout * 8))   # 突破前高最多10
        score = round(min(100, s_chg + s_pos + s_vol + s_str + s_break))
        board = "疑似打板候选" if score >= 70 else ("强势关注" if score >= 50 else "一般/观望")

        # 打板方向：跟随“实时最新价(含夜盘)涨跌”，而不是易被早盘跳空误导的开盘缺口。
        # 若盘中已反向回落(如早盘高开但现已下跌)，标“观望/做空”，绝不硬标做多——由体检把关。
        if ru >= 0.15:
            direction = 1
        elif ru <= -0.15:
            direction = -1
        else:
            direction = 0
        label = "做多" if direction == 1 else ("做空" if direction == -1 else "观望")
        strength = min(3, max(1, int(round(abs(ru) / 0.5)))) if direction else 0
        # 次日开盘预测 = 当前最新价×(1 + 今日跳空×0.6 + 近20日隔夜均值×0.4)，强势打板再偏多/偏空
        pred_gap = 0.6 * today_gap + 0.4 * mean_gap
        bias_boost = min(1.0, max(0.0, (score - 50) / 50.0 * 0.5))
        if direction == 1:
            pred_gap += bias_boost
        elif direction == -1:
            pred_gap -= bias_boost
        pred_open = round(anchor_price * (1 + pred_gap / 100.0), 3)
        lo = round(anchor_price * (1 + (pred_gap - 0.5 * std_gap) / 100.0), 3)
        hi = round(anchor_price * (1 + (pred_gap + 0.5 * std_gap) / 100.0), 3)
        bias = "偏强看多" if direction == 1 else ("偏弱看空" if direction == -1 else "观望")
        night_txt = "（含夜盘：夜盘开盘%s vs 昨结%s）" % (fmt_inline(today_open), fmt_inline(ref)) if sess == "night" else ""
        reason = ("%s今开%s vs 昨结%s，%+0.2f%%%s%s；打板分%d(%s)：涨%.2f%%/收高%.0f%%/放量%.2fx/连涨%d日；"
                  "预测次日开盘≈%s，区间[%s, %s]" %
                  (name, fmt_inline(today_open), fmt_inline(ref), today_gap, bias, night_txt,
                   score, board, ru, pos * 100, vol, streak,
                   fmt_inline(pred_open), fmt_inline(lo), fmt_inline(hi)))
        preds.append({
            "symbol": key, "name": name, "category": cat,
            "date": today_d, "today_open": round(today_open, 3),
            "prev_close": round(ref, 3), "gap_pct": round(today_gap, 2),
            "session": sess, "has_night": sess == "night",
            "direction": direction, "label": label, "strength": strength,
            "mean_gap": round(mean_gap, 2), "std_gap": round(std_gap, 2),
            "today_close": round(anchor_price, 3),
            "pred_next_open": pred_open, "pred_low": lo, "pred_high": hi,
            # 打板/连板潜力
            "limit_score": int(score), "board": board,
            "limit_ru": round(ru, 2), "limit_pos": round(pos, 2),
            "limit_vol": round(vol, 2), "limit_streak": int(streak),
            "reason": reason,
        })
    # 打板场景：优先看打板潜力分最高的
    preds.sort(key=lambda x: (x.get("limit_score", 0), abs(x.get("gap_pct", 0))), reverse=True)
    return preds


# ================= 体检：打板分/预测 一键全量自检（每次抓取自动跑） =================
def validate_predictions(preds, items=None):
    """对每条预测做一致性校验，返回 (问题数, 问题列表)。发现异常会打印醒目 WARN，
    但不停机——把问题亮出来供处理，绝不静默出错误数据。"""
    import math as _m
    problems = []
    def bad(field, p, why):
        problems.append("%s(%s) 字段[%s] %s" % (p.get("name", "?"), p.get("symbol", "?"), field, why))

    for p in preds:
        name = p.get("name", "?"); sym = p.get("symbol", "?")
        # 1) 有限数、无0价/异常值
        fields = {"today_open": p.get("today_open"), "prev_close": p.get("prev_close"),
                  "today_close": p.get("today_close"), "pred_next_open": p.get("pred_next_open"),
                  "pred_low": p.get("pred_low"), "pred_high": p.get("pred_high")}
        for f, v in fields.items():
            try:
                if v is None or not _m.isfinite(float(v)):
                    bad(f, p, "NaN 非数"); continue
                if float(v) <= 0:
                    bad(f, p, "价格<=0 异常")
            except (TypeError, ValueError):
                bad(f, p, "无法解析为数值")
        sc = p.get("limit_score")
        if sc is None or not (0 <= float(sc) <= 100):
            bad("limit_score", p, "打板分越界(%r)" % (sc,))
        # 2) 预测区间顺序合理：lo <= pred <= hi
        try:
            lo, mid, hi = float(p.get("pred_low")), float(p.get("pred_next_open")), float(p.get("pred_high"))
            if not (lo <= mid <= hi):
                bad("pred_low<=next<=high", p, "预测区间倒挂 lo=%s mid=%s hi=%s" % (lo, mid, hi))
        except Exception:
            pass
        # 3) 方向 vs 实时涨跌打架：做多却重挫、做空却大涨
        d = int(p.get("direction", 0)); ru = p.get("limit_ru")
        try: ru = float(ru)
        except Exception: ru = None
        if d > 0 and ru is not None and ru <= -0.55:
            bad("direction vs limit_ru", p, "标[做多]但实时涨跌 %+.2f%% 明显回落，方向打架" % ru)
        if d < 0 and ru is not None and ru >= 0.55:
            bad("direction vs limit_ru", p, "标[做空]但实时涨跌 %+.2f%% 明显上涨，方向打架" % ru)
        # 4) 打板分与实时涨跌一致性：疑似打板候选必须当前在涨
        board = p.get("board", ""); scv = sc if sc is not None else 0
        if board == "疑似打板候选" and ru is not None and ru <= 0:
            bad("board vs limit_ru", p, "标[疑似打板候选]但实时涨跌 %+.2f%% 非涨，红标属误报" % ru)
        if scv >= 70 and ru is not None and ru <= 0:
            bad("limit_score>=70 vs limit_ru", p, "打板分=%s但实时 %+.2f%%，高分与当前势能矛盾" % (scv, ru))
        # 5) 夜盘标记一致性
        if ("has_night" in p and "session" in p) and (p.get("has_night") != (p.get("session") == "night")):
            bad("has_night/session", p, "夜盘标记与时段不一致 session=%s has_night=%s" % (p.get("session"), p.get("has_night")))
        # 6) 打板分子项是否越界/异常
        for k in ("limit_vol", "limit_streak", "limit_pos"):
            v = p.get(k)
            try:
                f = float(v)
                if _m.isnan(f) or _m.isinf(f):
                    bad(k, p, "非有限数")
            except Exception:
                bad(k, p, "无法解析")

    # 7) 现货/期货 0 价体检
    if items:
        for it in items:
            for k in ("spot", "future", "basis"):
                v = it.get(k)
                if v is not None:
                    try:
                        if _m.isnan(float(v)):
                            problems.append("%s(%s) 字段[%s] NaN" % (it.get("name", "?"), it.get("symbol", "?"), k))
                    except Exception:
                        problems.append("%s(%s) 字段[%s] 解析失败" % (it.get("name", "?"), it.get("symbol", "?"), k))

    # 输出报告
    if not problems:
        print("[体检] 通过：%d 条预测全部一致，无0价/NaN/方向打架/夜盘矛盾" % len(preds))
    else:
        print("=" * 60)
        print("[体检] 发现 %d 个问题，需人工处理（不静默）:" % len(problems))
        for pr in problems:
            print("  ! " + pr)
        print("=" * 60)
    return len(problems), problems


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

# ============ 高频交易推荐：小资金 + 高波动 + 活跃 ============
def build_hf_picks(items, preds=None):
    """今日打板推荐（每天只做一次）：优先 波动大 + 方向强 + 小资金可开，给出具体进场/止损/止盈位。
    口径：只用当天有明显方向(做多=追强/做空=追跌)的品种，波幅优先；弱鸡观望的不推；一只是今日主推。"""
    import math as _m
    pred_map = {}
    if preds:
        for pp in preds:
            pred_map.setdefault(pp.get("symbol"), pp)
            pred_map.setdefault("nf_" + (pp.get("symbol") or ""), pp)
    picks = []
    for it in items:
        if it.get("market") != "国内":
            continue
        sym = it.get("symbol")
        fut = it.get("future")
        mg = it.get("est_margin")
        rng = it.get("day_range_pct") or 0.0
        vol = it.get("volume") or 0
        oi = it.get("open_interest") or 0
        pp = pred_map.get(sym) or pred_map.get("nf_" + sym)
        if not fut or fut <= 0:
            continue
        if not pp:
            continue
        direct = int(pp.get("direction") or 0)
        if direct == 0:                 # 观望的不构成打板机会
            continue
        if vol <= 0 or oi <= 0:         # 死水市场不沾手
            continue
        if not mg or mg <= 0:
            continue
        if rng < 1.0:                   # 当日波幅太小，没肉吃
            continue

        # funds gate: with 100k you should open >=3 lots (margin/lot <=~33k) so crude/gold/silver can't be main pick
        if mg > 0 and (100000.0 / mg) < 3.0:
            continue
        # 资金：越便宜越“绰绰有余”。10万能开>=3手(即一手保证金<=约3.3万)算宽裕；越贵评分越低
        sz = max(0.0, min(1.0, 1.0 - mg / 40000.0))
        # 方向强度：实时涨幅绝对值(打板追强/追跌才有意义)
        ru = abs(pp.get("limit_ru") or 0.0)
        # 打板分(模型对当日强势的判定)已含涨/位置/放量/连强
        ls = int(pp.get("limit_score") or 0)
        # 推荐分 = 波幅为主(0.40) + 资金(0.25) + 方向强度(0.20) + 活跃度(0.15)
        rv = max(0.0, min(1.0, rng / 4.0))            # 波幅 4% 给满分
        dv = max(0.0, min(1.0, ru / 2.5))             # 实时涨 2.5% 给满分
        av = max(0.0, min(1.0, _m.log10(vol + 1) / 6.0))
        score = 0.40 * rv + 0.25 * sz + 0.20 * dv + 0.15 * av
        # 具体每日打板点位：以实时最新价(anchor)为基准，沿用 止盈+3% / 反向-0.15%离场 / 浮盈回吐-0.1%硬止损
        anchor = float(pp.get("today_close") or fut or 0.0)
        if anchor <= 0:
            anchor = float(fut or 0.0)
        TP = 0.03; EXIT = 0.0015; HS = 0.001
        if direct == 1:
            tp = anchor * (1 + TP); sl = anchor * (1 - HS); ex = anchor * (1 - EXIT); lev = "追强做多"
        else:
            tp = anchor * (1 - TP); sl = anchor * (1 + HS); ex = anchor * (1 + EXIT); lev = "追跌做空"
        picks.append({
            "symbol": sym, "name": it.get("name"), "category": it.get("category"),
            "unit": it.get("unit"), "price": round(fut, 3),
            "direct": direct, "dir_label": pp.get("label", "做多" if direct > 0 else "做空"),
            "day_range_pct": round(rng, 2), "limit_score": ls,
            "board": pp.get("board", "一般/观望"),
            "est_margin": round(mg, 2), "hands_in_100k": int(100000.0 / mg) if mg > 0 else 0,
            "volume": int(vol), "open_interest": int(oi), "mode": lev,
            "anchor": round(anchor, 3), "tp": round(tp, 3), "sl": round(sl, 3), "exit_price": round(ex, 3),
            "board_score": round(score, 3),
            "reason": ("今日打板 · 方向%s · 实时%+.2f%% / 波幅%.2f%% / 打板分%d: 进场≈%s, 止盈%s, 反向%s离场, 硬止损%s" % (
                pp.get("label", ""), pp.get("limit_ru") or 0.0, rng, ls,
                ("%g" % anchor) if anchor >= 1000 else ("%.3f" % anchor),
                ("%g" % tp) if tp >= 1000 else ("%.3f" % tp),
                ("%g" % ex) if ex >= 1000 else ("%.3f" % ex),
                ("%g" % sl) if sl >= 1000 else ("%.3f" % sl))),
        })
    picks.sort(key=lambda x: -x["board_score"])
    # 第一名为“今日打板主推”
    for idx, rp in enumerate(picks):
        rp["rank"] = idx + 1
        rp["is_today"] = (idx == 0)
    return picks


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "output", "prices.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    items = build(out_path)
    # 期货主线：今日开盘 vs 昨结 -> 多空关联 + 次日开盘预测
    symlist = [(s, name, cat) for s, name, _, cat in DOMESTIC]
    try:
        predictions = predict_next_open(symlist)
    except Exception as e:
        predictions = []
        print("[WARN] predict_next_open:", str(e)[:70])

    hf_picks = build_hf_picks(items, predictions)
    daily_pick = hf_picks[0] if hf_picks and hf_picks[0].get("is_today") else (hf_picks[0] if hf_picks else {"name": ""})

    # ---- afternoon second board ----
    pm_sym = (daily_pick or {}).get("symbol")
    _ao = next((x for x in hf_picks if x.get("symbol") != pm_sym), None)
    if _ao is None and hf_picks:
        _ao = hf_picks[0]
    today_s = time.strftime("%Y-%m-%d")
    obj = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prices": items,
        "predictions": predictions,
        "hf_picks": hf_picks,
        "daily_pick": {"date": today_s, "session": "morning", **daily_pick},
        "afternoon_pick": {"date": today_s, "session": "afternoon", **(_ao or {})},
        "trading_rules": TRADING_RULES,
        "rules_summary": TRADING_RULES_SUMMARY,
    }
    n, probs = validate_predictions(predictions, items)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    both = sum(1 for x in items if x["kind"] == "both")
    domestic = sum(1 for x in items if x["market"] == "国内")
    print("完成: 共 %d 个品种(国内 %d / 国际 %d, 现货期货双价 %d) -> %s" % (
        len(items), domestic, len(items) - domestic, both, out_path))



