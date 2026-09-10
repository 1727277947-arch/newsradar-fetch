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
    "SC":1000, "LU":10, "SI":5, "LC":1, "SF":5, "SM":5,
}
MARGIN_RATE = {"SHFE":0.12, "DCE":0.10, "CZCE":0.10, "INE":0.12, "GFEX":0.12}
EXCH = {
    "AU":"SHFE","AG":"SHFE","CU":"SHFE","AL":"SHFE","ZN":"SHFE","NI":"SHFE","PB":"SHFE","SN":"SHFE",
    "RB":"SHFE","HC":"SHFE","WR":"SHFE","RU":"SHFE","FU":"SHFE","BU":"SHFE","SS":"SHFE","SP":"SHFE",
    "A":"DCE","B":"DCE","M":"DCE","C":"DCE","CS":"DCE","Y":"DCE","P":"DCE","JD":"DCE",
    "J":"DCE","JM":"DCE","I":"DCE","LH":"DCE","L":"DCE","PP":"DCE","EG":"DCE","EB":"DCE","PG":"DCE","V":"DCE",
    "CF":"CZCE","SR":"CZCE","OI":"CZCE","RM":"CZCE","FG":"CZCE","SA":"CZCE","TA":"CZCE","MA":"CZCE","UR":"CZCE",
    "CJ":"CZCE","AP":"CZCE","PK":"CZCE","PF":"CZCE","PX":"CZCE","SH":"CZCE","SF":"CZCE","SM":"CZCE","CY":"CZCE",
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


def _days_from(s):
    try:
        import datetime
        return datetime.date.fromisoformat(str(s).strip())
    except Exception:
        return None


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
# ---- 现货归属交易日记录：生意社滞后；宁缺不誊旧(写入 prices.json 透明标注) ----
SPOT_PAGE = {}

def fetch_spot_shensheng():
    ctx = ssl.create_default_context()
    out = {}
    # 从今天往前找最近有数据的交易日（生意社页面滞后一天）
    for back in range(0, 4):  # 只信任最近几个自然日；更旧宁缺(不拿旧现货冒充)
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
            SPOT_PAGE["date"] = day
            SPOT_PAGE["rows"] = len(out)
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
        # Li 日线方向（5/20/60）：多头排列只做多/空头只做空/缠绕禁交易；用上一根已收盘日K定向，不让当日实时污染
        def _cl(rr, ii):
            try:
                return float(rr[ii])
            except Exception:
                return None
        _hist = [_cl(x, 4) for x in recent[:-1] if _cl(x, 4)]
        _ht = _hist[-60:]
        if len(_ht) >= 60:
            ma5 = sum(_ht[-5:]) / 5.0
            ma20 = sum(_ht[-20:]) / 20.0
            ma60 = sum(_ht) / 60.0
            if ma5 > ma20 > ma60:
                day_bias = 'bull'
            elif ma5 < ma20 < ma60:
                day_bias = 'bear'
            else:
                day_bias = 'mix'
        else:
            ma5 = ma20 = ma60 = None
            day_bias = 'mix'
        today_d, kline_open, kline_close = recent[-1][0], recent[-1][1], recent[-1][4]  # (d,o,h,l,c,..) 第5列才是收盘
        prev_close_kline = recent[-2][4]  # 前一日收盘(第5列c; 此前误用[2]=h)
        # 近 N 日隔夜跳空统计（今开=含夜盘开盘 vs 前日收盘）
        N = 20
        gaps = []
        for i in range(max(1, len(recent) - N), len(recent)):
            c_prev = recent[i - 1][4]
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
        # 按品种波动自适应止损(ATR14 + 近60轮历史回测扫损率): 供同日多/空两套方案共用
        atrL = _atr_adaptive_stop(recent, 1, today_open)
        atrS = _atr_adaptive_stop(recent, -1, today_open)
        sl_long_pct = (atrL or {}).get('stop_pct')
        sl_short_pct = (atrS or {}).get('stop_pct')
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
            "day_ma": (round(ma5, 2), round(ma20, 2), round(ma60, 2)) if ma5 else None,
            "day_bias": day_bias,
            "atr": (atrL or atrS or {}).get("atr"),
            "sl_long_pct": sl_long_pct, "sl_short_pct": sl_short_pct,
            "hit_long": (atrL or {}).get("hit_rate"), "hit_short": (atrS or {}).get("hit_rate"),
            "stop_detail_long": atrL, "stop_detail_short": atrS,
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
        spot_as_of = str(SPOT_PAGE.get("date") or "")
        item["spot"] = sp
        # 透明标注现货归属日；陈旧丢弃(宁可 None 也绝不当天用旧现货)
        _a = _days_from(spot_as_of); _t = _days_from(today)
        if sp is not None and _a and _t:
            if (_t - _a).days < 0 or (_t - _a).days > 4:
                sp = None; item["spot"] = None; item["spot_stale"] = True
        item["spot_as_of"] = (spot_as_of if sp is not None else None)
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
def _open_dual(it, pp):
    """今开双轨元数据(不改选股/锁定)。O=真实今开(f46/f51今涨), P=现价。
做多: P>1.004*O 破开盘走强 break_a(ref=O)；0.996O<=P<=1.004O 回踩承接 dip_b(ref=O)；P<0.996O 跌破开盘当日放弃 drop。
做空镜像。缺 O/P -> None(pending)."""
    O=it.get("real_open"); P=it.get("future")
    if not O or not P:
        return None
    try:
        O=float(O); P=float(P)
    except Exception:
        return None
    if O<=0 or P<=0:
        return None
    direct=int(pp.get("direction") or 0)
    if direct==0:
        return None
    if direct>0:
        if P>=O*1.004: return {"st":"break_a","ref":round(O,2)}
        if P>=O*0.996: return {"st":"dip_b","ref":round(O,2)}
        return {"st":"drop","ref":None}
    else:
        if P<=O*0.996: return {"st":"break_a","ref":round(O,2)}
        if P<=O*1.004: return {"st":"dip_b","ref":round(O,2)}
        return {"st":"drop","ref":None}



def _mom_boost(pp, direct):
    """动量加成(评分用, 不改门与锚): 连板强度 limit_streak + 顺方向高开 gap_pct -> 0..0.17。仅在顺向正向加分, 不给反向计罚。"""
    st = int((pp.get('limit_streak') or 0) or 0)
    stN = min(max(st, 0), 4) / 4.0
    g = float((pp.get('gap_pct') or 0.0) or 0.0)
    gd = g if direct > 0 else (-g if direct < 0 else 0.0)
    gn = min(max(gd / 2.0, 0.0), 1.0)
    return 0.10 * stN + 0.07 * gn



def _kline_rows_for(sym):
    """取某主连的日K rows(方案C 午板重算 ATR 用); 无则返回空表。"""
    if not sym:
        return []
    key = sym[3:] if sym.startswith("nf_") else sym
    return _fetch_kline(key) or []



def _afternoon_plans(it, pp, rows):
    """午后板点位置算(方案C: 同品种, 但基准换成午后实时价, 不再照抄晨板的今开)。

    晨板以 real_open(今开)为进场基准; 午后行情已走出, 沿用今开会让"进场价"远离现价,
    实际无法成交。这里以午后最新价 future 为基准重算多/空双方案:
      - 取价方式保持"顺日线方向回踩现价承接"(多) / "跌破现价才空"(空, 条件式)
      - 止损仍用该品种 ATR 历史回测自适应(不写死%)
      - 止盈 2R 落袋, 并受当日真实板位约束
    返回 (long_plan, short_plan, meta); 数据不足返回 (None, None, None)。"""
    P = it.get("future")
    if not P:
        return (None, None, None)
    try:
        P = float(P)
    except Exception:
        return (None, None, None)
    if P <= 0:
        return (None, None, None)
    bup = float(it.get("board_up") or 0.0)
    bdn = float(it.get("board_down") or 0.0)
    sl_l = _atr_adaptive_stop(rows, 1, P)
    sl_s = _atr_adaptive_stop(rows, -1, P)
    if not sl_l or not sl_s:
        return (None, None, None)
    # 多单: 以现价承接进场
    e_l = P
    s_l = float(sl_l["stop"])
    r_l = e_l - s_l
    t_l = e_l + 2 * r_l
    if bup > 0:
        t_l = min(t_l, bup * 0.995)
    # 空单: 条件式, 跌破现价 0.1% 才成立
    e_s = P * (1 - 0.001)
    s_s = float(sl_s["stop"])
    r_s = s_s - e_s
    t_s = e_s - 2 * r_s
    if bdn > 0:
        t_s = max(t_s, bdn * 1.005)
    # 板位约束下 R 仍须为正, 否则该方向无可做空间
    long_plan = None
    if r_l > 0 and t_l > e_l:
        long_plan = {'entry': round(e_l, 3), 'sl': round(s_l, 3), 'tp': round(t_l, 3),
                     'sl_pct': round(float(sl_l["stop_pct"]), 2), 'rr': 2.0,
                     'basis': 'afternoon_last', 'k': sl_l["k"], 'hit_rate': sl_l["hit_rate"],
                     'note': '午后重算·现价承接做多; 止损ATR自适应, 2R落袋'}
    short_plan = None
    if r_s > 0 and t_s < e_s:
        short_plan = {'entry': round(e_s, 3), 'sl': round(s_s, 3), 'tp': round(t_s, 3),
                      'sl_pct': round(float(sl_s["stop_pct"]), 2), 'rr': 2.0,
                      'basis': 'afternoon_break', 'k': sl_s["k"], 'hit_rate': sl_s["hit_rate"],
                      'note': '午后重算·跌破现价才空(条件式); 止损ATR自适应, 2R落袋'}
    meta = {'basis_price': round(P, 3), 'atr': float(sl_l["atr"]),
            'long_k': sl_l["k"], 'short_k': sl_s["k"],
            'long_hit': sl_l["hit_rate"], 'short_hit': sl_s["hit_rate"]}
    return (long_plan, short_plan, meta)



def _atr_adaptive_stop(rows, direct, entry, lookback=60, atr_n=14, maxhit=0.25):
    """按品种自身波动定止损(不写死百分比): ATR=近atr_n日真实波幅(h-l)均值;
    在近lookback轮历史里回测不同止损系数k(k*ATR)的“被扫率”, 取被扫率<=maxhit的最小k。
    返回 dict(atr,k,stop,stop_pct,hit_rate,tested); 数据不足返回 None。entry=拟进场价。"""
    try:
        rr=[r for r in rows if len(r)>=5 and float(r[2])>0 and float(r[3])>0]
        if len(rr) < atr_n + 5:
            return None
        hist=rr[:-1]
        if len(hist) < atr_n + 5:
            return None
        def hl(x): return abs(float(x[2]) - float(x[3]))
        atr=sum(hl(x) for x in hist[-atr_n:]) / float(atr_n)
        if atr<=0 or not entry or float(entry)<=0:
            return None
        entry=float(entry)
        ks=[0.4,0.6,0.8,1.0,1.2,1.5,2.0]
        seg=hist[-lookback:]
        best=None
        for k in ks:
            hit=0; tot=0
            for x in seg:
                o=float(x[1]); h=float(x[2]); l=float(x[3])
                if o<=0 or h<=l: continue
                tot+=1
                dist=k*atr
                if direct>0:
                    if (o-dist) >= l: hit+=1
                else:
                    if (o+dist) <= h: hit+=1
            if tot<10: continue
            hr=hit/float(tot)
            rec={'k':k,'hit_rate':round(hr,3),'tested':tot}
            if hr<=maxhit:
                best=rec; break
            if best is None or hr<best['hit_rate']:
                best=rec
        if not best:
            return None
        k=best['k']; dist=k*atr
        stop=(entry-dist) if direct>0 else (entry+dist)
        return {'atr':round(atr,2),'k':k,'stop':round(stop,3),
                'stop_pct':round(dist/entry*100.0,2),'hit_rate':best['hit_rate'],'tested':best['tested']}
    except Exception:
        return None


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
        dayb = pp.get("day_bias") or "mix"
        if dayb == "mix" and direct != 0:
            continue    # day MA tangled -> no day trade (Li: skip, not chase)
        if direct == 1 and dayb == "bear":
            continue    # bear stacks: longs forbidden
        if direct == -1 and dayb == "bull":
            continue    # bull stacks: shorts forbidden
        if vol <= 0 or oi <= 0:         # 死水市场不沾手
            continue
        if not mg or mg <= 0:
            continue
        if rng < 1.0:                   # 当日波幅太小，没肉吃
            continue

        # real-board gate: without real up/down board price a candidate would be a guess;
        # once the price sits at/through the limit, no order can fill, so skip.
        _bup = it.get('board_up')
        _bdn = it.get('board_down')
        if not _bup or not _bdn:
            continue
        if direct == 1 and fut and fut >= _bup:
            continue
        if direct == -1 and fut and fut <= _bdn:
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
        score = min(1.0, 0.40 * rv + 0.25 * sz + 0.20 * dv + 0.15 * av + _mom_boost(pp, direct))
        # 具体每日打板点位：以实时最新价(anchor)为基准，沿用 止盈+3% / 反向-0.15%离场 / 浮盈回吐-0.1%硬止损
        anchor = float(pp.get("today_close") or fut or 0.0)
        if anchor <= 0:
            anchor = float(fut or 0.0)
        TP = 0.03; EXIT = 0.0015; HS = 0.001
        # (A) futures-only: if already chased far, give reentry instead of chasing top; spot=trend only
        pc_a = float(pp.get('prev_close') or 0.0)
        op_a = float(pp.get('today_open') or 0.0)
        RALLY_END_MA = 1.6
        if pc_a > 0 and op_a > 0:
            if direct == 1 and (anchor - pc_a) / pc_a * 100.0 >= RALLY_END_MA and op_a < anchor:
                anchor = op_a
            elif direct == -1 and (pc_a - anchor) / anchor * 100.0 >= RALLY_END_MA and op_a > anchor:
                anchor = op_a
        if direct == 1:
            tp = anchor * (1 + TP); sl = anchor * (1 - HS); ex = anchor * (1 - EXIT); lev = "追强做多"
        else:
            tp = anchor * (1 - TP); sl = anchor * (1 + HS); ex = anchor * (1 + EXIT); lev = "追跌做空"
        # 同日双方案(仅该打板品种): 一个多单一个空单; 止损按品种ATR历史回测自适应(不写死%), 止盈2R落袋(+板位约束)
        _ro = float(it.get('real_open') or op_a or anchor or 0.0)
        _ulp = float(pp.get('sl_long_pct') or 0.8)
        _usp = float(pp.get('sl_short_pct') or 0.8)
        _bup = float(it.get('board_up') or 0.0)
        _bdn = float(it.get('board_down') or 0.0)
        if _ro > 0:
            _e_l = _ro
            _s_l = _e_l * (1 - _ulp / 100.0)
            _r_l = _e_l - _s_l
            _t_l = _e_l + 2 * _r_l
            if _bup > 0: _t_l = min(_t_l, _bup * 0.995)
            long_plan = {'entry': round(_e_l, 3), 'sl': round(_s_l, 3), 'tp': round(_t_l, 3),
                         'sl_pct': round(_ulp, 2), 'rr': 2.0, 'basis': 'real_open',
                         'note': '顺日线多·回踩今开承接; 止损ATR自适应, 2R落袋'}
            _e_s = _ro * (1 - 0.001)
            _s_s = _e_s * (1 + _usp / 100.0)
            _r_s = _s_s - _e_s
            _t_s = _e_s - 2 * _r_s
            if _bdn > 0: _t_s = max(_t_s, _bdn * 1.005)
            short_plan = {'entry': round(_e_s, 3), 'sl': round(_s_s, 3), 'tp': round(_t_s, 3),
                          'sl_pct': round(_usp, 2), 'rr': 2.0, 'basis': 'break_real_open',
                          'note': '跌破今开才空(条件式); 止损ATR自适应, 2R落袋'}
        else:
            long_plan = None; short_plan = None
        picks.append({
            "symbol": sym, "name": it.get("name"), "category": it.get("category"),
            "unit": it.get("unit"), "price": round(fut, 3),
            "direct": direct, "dir_label": pp.get("label", "做多" if direct > 0 else "做空"),
            "day_range_pct": round(rng, 2), "limit_score": ls,
            "board": pp.get("board", "一般/观望"),
            "dual": _open_dual(it, pp),
            "long_plan": long_plan, "short_plan": short_plan,
            "real_open": it.get("real_open"),
            "day_bias": pp.get("day_bias") or "mix",
            "day_ma": pp.get("day_ma"),
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



def _audit_futures(items):
    rows = 0
    zh = chr(0x56fd) + chr(0x5185)
    for it in items:
        if it.get('market') != zh:
            continue
        fut = it.get('future'); sett = it.get('last_settle')
        if not fut or not sett:
            continue
        mult = it.get('contract_mult'); rate = it.get('margin_rate'); mg = it.get('est_margin')
        exp = None
        if mult and rate and float(fut) > 0 and float(mult) > 0 and float(rate) > 0:
            exp = round(float(fut) * float(mult) * float(rate), 2)
        ok = (mg is not None and exp is not None and abs(mg - exp) <= 0.01 + abs(exp) * 1e-6)
        pct = it.get('change_pct'); hi = it.get('day_high'); lo = it.get('day_low')
        def g(v):
            return ('%g' % v) if isinstance(v, (int, float)) else '-'
        pcts = ('%g%%' % pct) if isinstance(pct, (int, float)) else '-'
        line = '  ' + str(it.get('name')) + str(it.get('symbol'))
        line += ' | settle=' + g(sett) + ' last=' + g(fut) + ' chgPct=' + pcts
        line += ' | high=' + g(hi) + ' low=' + g(lo)
        line += ' | mult=' + str(mult) + ' rate=' + str(rate)
        line += ' | margin/lot=' + g(mg) + ' (recalc=' + g(exp) + ') ' + ('OK' if ok else 'MISMATCH')
        print(line)
        if ok:
            rows += 1
    print('audited futures rows consistent =', rows)

def _fetch_em_boards():
    """real board_up/board_down (eastmoney main-continuous) for the five tracked mains; no-ID cloud source"""
    import time as _t
    HOSTS = ["https://push2delay.eastmoney.com", "https://push2delay2.eastmoney.com", "https://push2.eastmoney.com"]
    HDRS = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Connection": "close"}
    EM = {"LC0": ("225", "lcm"), "SI0": ("225", "sim"), "SF0": ("115", "SFM"), "SM0": ("115", "SMM"), "MA0": ("115", "MAM")}
    out = {}
    for k0, (mkt, code) in EM.items():
        got = None
        last_err = ""
        for _round in range(2):
            if got:
                break
            for host in HOSTS:
                if got:
                    break
                q = "%s/api/qt/stock/get?secid=%s.%s&fields=f43,f51,f52,f46,f170&fltt=2" % (host, mkt, code)
                try:
                    req = urllib.request.Request(q, headers=HDRS)
                    d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")).get("data") or {}
                    up = d.get("f51"); dn = d.get("f52"); last = d.get("f43"); opn = d.get("f46")
                    if up and dn and last:
                        got = {"board_up": float(up), "board_down": float(dn), "latest": float(last), "real_open": (float(opn) if opn else None)}
                    else:
                        last_err = "%s empty(f43=%s f51=%s f52=%s)" % (host.split("//")[1], last, up, dn)
                except Exception as e:
                    last_err = "%s %s" % (host.split("//")[1], str(e)[:40])
                    _t.sleep(1.0)
            if not got:
                _t.sleep(2.0)
        out[k0] = got
        if not got:
            print("[WARN] em board miss %s %s: %s" % (k0, code, last_err))
        _t.sleep(2.0)
    return out
def _merge_em_boards(items, boards):
    bmap = {}
    for it in items:
        s = it.get("symbol")
        if s and s in boards:
            b = boards[s]
            if b:
                it["board_up"] = b["board_up"]
                it["board_down"] = b["board_down"]
                it["real_open"] = b.get("real_open")
    return items
if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "output", "prices.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    items = build(out_path)
    if os.environ.get('NR_AUDIT') == '1':
        _audit_futures(items)

    # 期货主线：今日开盘 vs 昨结 -> 多空关联 + 次日开盘预测
    symlist = [(s, name, cat) for s, name, _, cat in DOMESTIC]
    try:
        predictions = predict_next_open(symlist)
    except Exception as e:
        predictions = []
        print("[WARN] predict_next_open:", str(e)[:70])

    # real daily limit boards (eastmoney multi-node), fetched once before picks
    try:
        _em = _fetch_em_boards()
        if isinstance(_em, dict):
            items = _merge_em_boards(items, _em)
            print('em boards merged:', {k: _em.get(k) for k in _em})
    except Exception as e:
        print('[WARN] _fetch_em_boards:', str(e)[:80])

    hf_picks = build_hf_picks(items, predictions)

    # ---- dual-board: independent time windows, never cross-contaminate ----
    BJT = int(time.strftime("%H"))          # run.sh exports TZ=Asia/Shanghai
    now_date = time.strftime("%Y-%m-%d")
    prev = {}
    try:
        _pf = os.path.join(BASE, "..", "data", "prices.json")
        if os.path.exists(_pf):
            with open(_pf, encoding="utf-8") as _fh:
                prev = json.load(_fh)
    except Exception:
        prev = {}
    _pm = prev.get("daily_pick") or {}
    _pa = prev.get("afternoon_pick") or {}
    prev_date = _pm.get("date") or ""
    morning_locked = (prev_date == now_date)
    empty = {"name": "", "symbol": ""}

    if BJT < 10:                                  # morning / early-session window
        morning_pick = hf_picks[0] if hf_picks else (_pm or empty)
        afternoon_recompute = False
    else:                                         # afternoon / later-session window
        morning_pick = _pm if _pm.get("symbol") else (hf_picks[0] if hf_picks else empty)
        if not morning_locked and not morning_pick.get("name"):
            morning_pick = hf_picks[0] if hf_picks else empty
            morning_locked = True
        afternoon_recompute = True

    _msym = morning_pick.get("symbol") or morning_pick.get("name")
    # 方案C 午板重算所需的按品种索引
    _item_by_sym = {}
    for _it0 in items:
        _s0 = _it0.get("symbol")
        if _s0:
            _item_by_sym[_s0] = _it0
    _pred_by_sym = {}
    for _p0 in (predictions or []):
        _s0 = (_p0.get("symbol") or "")
        _pred_by_sym[_s0] = _p0
        if _s0.startswith("nf_"):
            _pred_by_sym[_s0[3:]] = _p0

    if afternoon_recompute:
        # 方案C: 优先选与晨板不同的品种(多一个机会); 池中若只剩晨板那一只,
        # 则仍盯同一品种, 但点位改用午后实时价重算 —— 不照抄晨板以"今开"为基准的价位。
        cand = [x for x in hf_picks if (x.get("symbol") or x.get("name")) != _msym]
        if cand:
            afternoon_pick = cand[0]
            afternoon_pick["plan_basis"] = "alt_symbol"
        elif hf_picks:
            # 同品种, 用午后实时价重算双方案
            afternoon_pick = dict(hf_picks[0])
            _asy = afternoon_pick.get("symbol") or afternoon_pick.get("name")
            _ait = _item_by_sym.get(_asy)
            _app = _pred_by_sym.get(_asy, {})
            _arows = _kline_rows_for(_asy)
            _pl, _ps, _pmeta = _afternoon_plans(_ait, _app, _arows) if (_ait and _arows) else (None, None, None)
            if _pl or _ps:
                afternoon_pick["long_plan"] = _pl
                afternoon_pick["short_plan"] = _ps
                afternoon_pick["plan_basis"] = "afternoon_last"
                afternoon_pick["afternoon_meta"] = _pmeta
                _ap = float((_pmeta or {}).get("basis_price") or 0.0)
                if _ap > 0:
                    # 锚点/止盈/离场/硬止损全部按午后价重算, 保持与盘面一致
                    _ad = int(_app.get("direction") or 0)
                    if _ad == 1:
                        _atp = _ap * 1.03; _aex = _ap * (1 - 0.0015); _asl = _ap * (1 - 0.001)
                    elif _ad == -1:
                        _atp = _ap * 0.97; _aex = _ap * (1 + 0.0015); _asl = _ap * (1 + 0.001)
                    else:
                        _atp = _aex = _asl = 0.0
                    afternoon_pick["anchor"] = round(_ap, 3)
                    afternoon_pick["price"] = round(_ap, 3)
                    if _atp: afternoon_pick["tp"] = round(_atp, 3)
                    if _aex: afternoon_pick["exit_price"] = round(_aex, 3)
                    if _asl: afternoon_pick["sl"] = round(_asl, 3)
                    afternoon_pick["reason"] = ("午后重算 · 方向%s · 现价%s: 进场≈%s, 止盈%s, 反向%s离场, 硬止损%s" % (
                        _app.get("label", ""),
                        ("%g" % _ap) if _ap >= 1000 else ("%.3f" % _ap),
                        ("%g" % _ap) if _ap >= 1000 else ("%.3f" % _ap),
                        ("%g" % _atp) if _atp >= 1000 else ("%.3f" % _atp),
                        ("%g" % _aex) if _aex >= 1000 else ("%.3f" % _aex),
                        ("%g" % _asl) if _asl >= 1000 else ("%.3f" % _asl)))
            else:
                # 拿不到午后价/ATR -> 宁可留空, 也不照抄晨板价位充数
                afternoon_pick = dict(empty)
                afternoon_pick["plan_basis"] = "unavailable"
        else:
            afternoon_pick = empty
    else:
        afternoon_pick = _pa if ((_pa.get("date") == now_date) and (_pa.get("symbol") or _pa.get("name"))) else empty
        if _msym and afternoon_pick.get("symbol") == _msym and afternoon_pick.get("plan_basis") != "afternoon_last":
            alt = [x for x in hf_picks if x.get("symbol") != _msym]
            afternoon_pick = alt[0] if alt else afternoon_pick
        # 方案C: 午后板盯同一品种, 但点位用午后实时价重算(不再照抄晨板以今开为基准的价位)。
        # 仍优先选一只与晨板不同的品种(多一个机会); 若池中无第二只, 则同品种走"午后重算"。
    # 内参卡整流：晨/午只要本地缺 day_bias/day_ma 就从同标的 hf 行补（唯添元数据，不改变选股锁定逻辑）
    if hf_picks:
        bmap = { (x.get('symbol') or x.get('name')): x for x in hf_picks }
        for _p in (morning_pick, afternoon_pick):
            _sym = _p.get('symbol') or _p.get('name')
            _fa = bmap.get(_sym) or {}
            if _fa and not _p.get('day_bias'):
                _p['day_bias'] = _fa.get('day_bias') or 'mix'
                _p['day_ma'] = _fa.get('day_ma')
    today_s = now_date
    obj = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "spot_meta": {
            "policy": "stale_never_fill",
            "spot_page_used": (SPOT_PAGE.get("date") or None),
            "note": "现货归属日见各品种 spot_as_of；缺失 None 即当日/最近已收盘昨日现货未取到，宁缺不誊旧"
        },
        "prices": items,
        "predictions": predictions,
        "hf_picks": hf_picks,
        "daily_pick": {"date": today_s, "session": "morning", **morning_pick},
        "afternoon_pick": {"date": today_s, "session": "afternoon", **afternoon_pick},
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
