# -*- coding: utf-8 -*-
"""
clean_fetch.py - 定向抓取器（大宗商品全品种 + 国内财经）
只抓直接可打开原链接的真实源；国外财政/政治一概不要。
大宗商品按品种分类(贵金属/能源/基本金属/黑色系/农产品)；国内新闻单独保留。
国外新闻抓取后经 MyMemory 翻译为中文简述（title/summary），不保留原链接；
国内(中国新闻网财经)保留可直接打开的原链接。
用法: python clean_fetch.py [输出路径，默认 ./output/news.json]
"""
import json, re, ssl, time, hashlib, sys, os, html
import urllib.request, urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BASE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
TIMEOUT = 15
MAX_PER_SOURCE = 15
TIME_WINDOW_HOURS = 48

# ---- 只留：国际大宗商品行情源(会做品种白名单过滤) + 国内财经 ----
SOURCES = [
    {"name": "Mining.com",       "rss": "https://www.mining.com/feed/",                          "kind": "comm"},
    {"name": "Oilprice.com",     "rss": "https://oilprice.com/rss/main",                         "kind": "comm"},
    {"name": "Grainnet",         "rss": "https://www.grainnet.com/rss.xml",                      "kind": "comm"},
    {"name": "Nasdaq商品",       "rss": "https://www.nasdaq.com/feed/rssoutbound?category=commodities", "kind": "comm"},
    {"name": "NorthernMiner",    "rss": "https://www.northernminer.com/feed/",                   "kind": "comm"},
    {"name": "GrainCentral",    "rss": "https://www.graincentral.com/feed/",                    "kind": "comm"},
    {"name": "中国新闻网-财经", "rss": "http://www.chinanews.com.cn/rss/finance.xml",     "kind": "cn"},
    {"name": "中国新闻网-要闻", "rss": "https://www.chinanews.com.cn/rss/scroll-news.xml", "kind": "cn"},
    {"name": "中国新闻网-国内", "rss": "https://www.chinanews.com.cn/rss/china.xml",       "kind": "cn"},
    {"name": "中国新闻网-国际", "rss": "https://www.chinanews.com.cn/rss/world.xml",       "kind": "cn"},
]

# ---- 大宗商品全品种白名单（中文+英文关键词）----
COMMODITY_CATS = [
    ("贵金属",  ["黄金", "金价", "白银", "铂金", "钯金", "gold", "silver", "platinum", "palladium", "precious metal"]),
    ("能源",    ["原油", "石油", "油价", "wti", "布伦特", "brent", "天然气", "汽油", "燃料油", "oil", "crude", "gas", "petroleum", "energy price"]),
    ("基本金属", ["铜", "铝", "锌", "镍", "铅", "锡", "lme", "copper", "aluminum", "aluminium", "zinc", "nickel", "lead", "tin"]),
    ("黑色系",  ["铁矿石", "铁矿", "螺纹", "焦煤", "焦炭", "钢材", "钢铁", "iron ore", "steel", "coke", "futures steel"]),
    ("农产品",  ["大豆", "玉米", "小麦", "棉花", "白糖", "糖价", "豆粕", "菜粕", "棕榈油", "菜籽油", "生猪", "鸡蛋", "橡胶",
                "soybean", "soy", "corn", "wheat", "cotton", "sugar", "rubber", "grain", "palm oil", "coffee", "cocoa"]),
]
# 泛大宗商品/期货词：命中则归为"综合"


GENERIC_COMM = ["大宗商品", "商品期货", "期货", "commodity", "commodities", "futures", "inventor", "stockpile"]

# 英文商品术语 -> 中文关键字（用于国外新闻“只提取关键字”）
TERM_ZH = {
    # 贵金属
    "gold": "黄金", "silver": "白银", "platinum": "铂金", "palladium": "钯金",
    "precious metal": "贵金属", "bullion": "金条",
    # 能源
    "crude": "原油", "oil": "原油", "wti": "WTI油价", "brent": "布伦特油价",
    "petroleum": "石油", "gasoline": "汽油", "natural gas": "天然气", "gas": "天然气",
    "fuel": "燃料", "heating oil": "取暖油", "energy": "能源", "refinery": "炼厂",
    # 基本金属
    "copper": "铜", "aluminum": "铝", "aluminium": "铝", "zinc": "锌", "nickel": "镍",
    "lead": "铅", "tin": "锡", "lme": "伦敦金属交易所", "metal": "金属",
    # 黑色系
    "iron ore": "铁矿石", "steel": "钢材", "coke": "焦炭", "coal": "煤炭",
    "rebar": "螺纹钢", "hot rolled": "热卷", "iron": "生铁",
    # 农产品
    "soybean": "大豆", "soy": "大豆", "corn": "玉米", "wheat": "小麦", "cotton": "棉花",
    "sugar": "白糖", "rubber": "橡胶", "grain": "谷物", "palm oil": "棕榈油",
    "coffee": "咖啡", "cocoa": "可可", "meal": "豆粕", "oilseed": "油籽",
    # 价格/行情用语
    "price": "价", "prices": "价", "rises": "上涨", "rise": "上涨", "rally": "上涨",
    "gains": "走强", "gain": "走强", "climbs": "走高", "climb": "走高",
    "falls": "下跌", "fall": "下跌", "drop": "下跌", "slips": "回落", "slide": "下滑",
    "surge": "大涨", "jump": "跳涨", "tumble": "暴跌", "eases": "走软",
    "supply": "供应", "demand": "需求", "stock": "库存", "inventor": "库存",
    "output": "产量", "production": "产量", "exports": "出口", "imports": "进口",
    "shortage": "短缺", "glut": "过剩", "output cut": "减产", "strike": "罢工",
    "week": "周", "year high": "年内新高", "forecast": "预测", "outlook": "展望",
}

def extract_keywords(text, category):
    t = (text or "").lower()
    found = []
    for en, zh in TERM_ZH.items():
        if en in t and zh not in found:
            found.append(zh)
    if category and category not in found:
        found.insert(0, category)
    # 至少保留类别
    return found[:6]


def translate_zh(text, max_len=900, cache=None):
    """调用 MyMemory 免费翻译接口把英文(自动检测)译为简体中文；失败返回原串。"""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0]
    h = hashlib.md5(t.encode("utf-8")).hexdigest()
    if cache is not None and h in cache:
        return cache[h]
    try:
        import urllib.parse
        q = urllib.parse.quote(t)
        u = "https://api.mymemory.translated.net/get?q=" + q + "&langpair=en|zh-CN"
        req = urllib.request.Request(u, headers={"User-Agent": "NewsRadar/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        out = (d.get("responseData", {}) or {}).get("translatedText", "") or ""
        # MyMemory 有时把未翻译词保留原样并加 ***；清理
        out = re.sub(r"\*\*\*|&quot;|&amp;", "", out).strip()
        if out:
            if cache is not None:
                cache[h] = out
            return out
    except Exception:
        pass
    return t


def commodity_cat(title, summary):
    t = (title + " " + (summary or "")).lower()
    if is_noise_text(title, summary):
        return None
    for cat, kws in COMMODITY_CATS:
        if any(k in t for k in kws):
            return cat
    if any(k in t for k in GENERIC_COMM):
        return "综合"
    return None


# ---- 国内经济/政策/政治军事 白名单与黑名单 ----
CN_KEEP = ["经济", "金融", "财政", "货币", "央行", "银行", "利率", "汇率", "社保", "养老金",
           "证券", "股市", "A股", "上市", "融资", "债券", "基金", "期货", "商品", "大宗商品",
           "价格", "涨", "跌", "需求", "供应", "库存", "出口", "进口", "贸易", "关税", "海关",
           "发改委", "统计局", "工信部", "商务部", "财政部", "外汇", "逆回购", "降准", "降息",
           "CPI", "PPI", "GDP", "制造业", "工业", "基建", "消费", "投资", "房地产", "房地产",
           "政策", "会议", "发布", "举措", "发放", "贷款", "信贷", "产能", "能源", "电力", "煤炭",
           "钢铁", "石油", "大宗", "价格指数", "现货", "期货价格", "收评", "早盘", "午评",
           "外部", "关税", "中美", "进口", "出口贸易", "供应链", "补贴", "新能源", "光伏", "锂",
           "石油", "天然气", "化工", "农业", "粮食", "生猪", "玉米", "大豆", "棉", "糖",
           "国防", "军", "演习", "航母", "导弹", "军队", "外交", "外长", "元首", "会谈", "国际", "制裁",
           "战略", "规划", "目标", "经济工作", "会议"]
CN_DROP = ["家政", "保姆", "养老院", "婚恋", "相亲", "宠物", "萌娃", "萌宠", "母婴", "亲子",
           "手工艺", "非遗", "民俗", "景区", "旅游攻略", "美食探店", "菜谱", "外卖",
           "明星", "娱乐圈", "综艺", "电视剧", "电影", "演唱会", "游戏", "电竞", "直播带货",
           "球赛", "联赛", "积分榜", "转会", "健身房", "瑜伽", "美容", "整形", "养生",
           "中小学", "高考", "考研", "摇号", "垃圾分类", "物业", "停车位"]
CN_TOPIC_RULES = [
    ("金融政策", ["央行", "降准", "降息", "利率", "汇率", "货币", "财政", "债券", "证券", "A股", "股市", "上市", "融资", "基金", "逆回购", "贷款", "信贷", "外汇", "银行", "CPI", "PPI", "GDP"]),
    ("大宗商品", ["大宗商品", "商品期货", "期货", "现货", "原油", "石油", "天然气", "煤炭", "钢铁", "铜", "铝", "锌", "镍", "黄金", "白银", "大豆", "玉米", "小麦", "棉花", "糖", "猪肉", "生猪", "蛋价", "化工", "能源", "价格指数"]),
    ("产业经济", ["制造业", "工业", "基建", "消费", "投资", "房地产", "产能", "供应链", "新能源", "光伏", "锂", "汽车", "家电"]),
    ("贸易外经", ["贸易", "关税", "进出口", "出口", "进口", "海关", "中美", "外经", "国际", "制裁", "供应链"]),
    ("政治军事", ["国防", "军", "演习", "航母", "导弹", "军队", "外交", "外长", "元首", "会谈"]),
]


def cn_fin(t):
    """判断国内条目是否属于经济/政策/政治军事（丢弃泛生活/无关）。"""
    if is_noise_text(t, ""):
        return False
    tl = t.lower()
    for w in CN_DROP:
        if w in tl:
            return False
    hits = sum(1 for w in CN_KEEP if w in tl)
    return hits >= 1


def cn_topic(title):
    for topic, kws in CN_TOPIC_RULES:
        if any(k in title for k in kws):
            return "国内/" + topic
    return "国内/财经"


def clean_cn_summary(s):
    """去掉导语样板/广告尾巴，尽量只留正文。"""
    s = s or ""
    # 去掉常见导语前缀
    s = re.sub(r"^(原标题[:：]?\s*)|^(原标题：)", "", s)
    s = re.sub(r"^中新网[^\s（(]*[\s（(]*", "", s)
    s = re.sub(r"^\S+记者[^)]*\)", "", s)
    # 去掉“扫描/长按/下载/点击”类广告尾巴
    s = re.split(r"(长按识别|扫描二维码|扫码关注|下载客户端|点击下方|活动报名|直播入口)", s)[0]
    s = re.sub(r"\s+", " ", s).strip(" 。．")
    return s


def meta_for(source, cat=None):
    if source == "中国新闻网-财经":
        return {"score": 80, "priority": "P1", "topic": "国内/金融政策", "tags": ["金融政策", "中文", "国内", source]}
    # 国际商品行情
    return {"score": 84, "priority": "P1", "topic": cat, "tags": [cat, "大宗商品"]}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for verify in (True, False):
        try:
            c = ssl.create_default_context()
            if not verify:
                c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=c) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if not verify:
                raise
            time.sleep(1.5)
    raise RuntimeError("fetch failed")


def clean_text(s):
    s = s or ""
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S)
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_noise_text(title, summary):
    t = (title + " " + (summary or "")).lower()
    noise = [
        "black friday", "cyber monday", "discount", "sale", "promo", "coupon",
        "this $", " save ", "loot", "giveaway", " free ", "trick",
        "gta", "xbox", "playstation", "nintendo", "remake", "retro arcade",
        "点击领取", "领取红包", "扫码", "扫码进群", "限时抢购", "特价", "优惠券",
        "下载客户端", "长按识别", "点击查看", "了解更多", "报名入口", "直播预约",
        "app下载", "回放", "抽奖", "广告", "植入", "免费领取",
    ]
    return any(w in t for w in noise)


def is_bad(url):
    u = (url or "").strip()
    if not u.startswith("http"):
        return True
    if "news.google.com" in u and ("/rss/articles" in u or "/articles/" in u):
        return True
    after = u.split("://", 1)[-1]
    slash = after.find("/")
    if slash < 0:
        return True
    path = after[slash + 1:].rstrip("/")
    if not path or path == "#":
        return True
    if path.endswith("--") or (path.endswith("-") and not path.endswith("-story")):
        return True
    if "/promo-code" in u or "promo-code" in u:
        return True
    return False


def _iso(s):
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _entry_time(xml):
    pm = re.search(r"<(?:pubDate|published|updated|dc:date)[^>]*>(.*?)</(?:pubDate|published|updated|dc:date)>", xml, re.I | re.S)
    if pm:
        raw = pm.group(1).strip()
        for fn in (parsedate_to_datetime, _iso):
            try:
                v = fn(raw)
                if v is not None:
                    return v
            except Exception:
                pass
    return None


def parse_atom(xml):
    items = re.findall(r"<entry[ >].*?</entry>", xml, re.S | re.I)
    out = []
    now = datetime.now(timezone.utc)
    for it in items[:MAX_PER_SOURCE * 3]:
        tm = re.search(r"<title[^>]*>(.*?)</title>", it, re.I | re.S)
        lm = re.search(r'<link[^>]*href=["\']([^"\']+)["\']', it, re.I | re.S) or re.search(r"<link[^>]*>(.*?)</link>", it, re.I | re.S)
        dm = re.search(r"<(?:summary|content)[^>]*>(.*?)</(?:summary|content)>", it, re.I | re.S)
        title = clean_text(tm.group(1)) if tm else ""
        link = lm.group(1) if lm else ""
        if not title or is_bad(link):
            continue
        pub = _entry_time(it)
        pub_time = ""
        if pub:
            pub = pub.astimezone(timezone.utc)
            pub_time = pub.strftime("%Y-%m-%dT%H:%M:%SZ")
        hours_ago = max(0.0, (now - pub).total_seconds() / 3600) if pub else None
        if hours_ago is None or hours_ago > TIME_WINDOW_HOURS:
            continue
        summary = clean_text(dm.group(1))[:300] if dm else ""
        out.append({"title": title, "url": link, "summary": summary,
                    "pub_time": pub_time or now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out


def parse(xml):
    if "<entry" in xml.lower() and "<item>" not in xml.lower():
        return parse_atom(xml)
    items = re.findall(r"<item>(.*?)</item>", xml, re.S | re.I)
    out = []
    now = datetime.now(timezone.utc)
    for it in items[:MAX_PER_SOURCE]:
        tm = re.search(r"<title[^>]*>(.*?)</title>", it, re.I | re.S)
        lm = re.search(r"<link[^>]*>(.*?)</link>", it, re.I | re.S)
        dm = re.search(r"<(?:description|content:encoded)[^>]*>(.*?)</(?:description|content:encoded)>", it, re.I | re.S)
        pm = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", it, re.I | re.S) or re.search(r"<published[^>]*>(.*?)</published>", it, re.I | re.S)
        title = clean_text(tm.group(1)) if tm else ""
        link = (lm.group(1).strip() if lm else "").split("&amp;")[0]
        summary = clean_text(dm.group(1))[:300] if dm else ""
        if not title or is_bad(link):
            continue
        pub = None
        pub_time = ""
        if pm:
            try:
                pub = parsedate_to_datetime(pm.group(1).strip())
                pub = pub.astimezone(timezone.utc)
                pub_time = pub.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pub = None
        hours_ago = max(0.0, (now - pub).total_seconds() / 3600) if pub else None
        if hours_ago is None or hours_ago > TIME_WINDOW_HOURS:
            continue
        out.append({"title": title, "url": link, "summary": summary,
                    "pub_time": pub_time or now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out


def build():
    all_articles = []
    ok = fail = 0
    now = datetime.now(timezone.utc)
    tr_cache = {}
    for src in SOURCES:
        try:
            xml = fetch(src["rss"])
            arts = parse(xml)
            picked = []
            for a in arts:
                a["source"] = src["name"]
                if src["kind"] == "comm":
                    cat = commodity_cat(a["title"], a.get("summary", ""))
                    if not cat:
                        continue  # 非大宗商品，丢掉
                    a["_cat"] = cat
                else:
                    # 国内：只保留经济/政策/政治军事，且去掉样板/广告尾巴
                    if not cn_fin(a["title"] + " " + a.get("summary", "")):
                        continue
                    a["_cn"] = True
                    a["summary"] = clean_cn_summary(a.get("summary", ""))
                picked.append(a)
            all_articles.extend(picked)
            ok += 1
            print(f"[OK] {src['name']}: {len(picked)} 条")
        except Exception as e:
            fail += 1
            print(f"[FAIL] {src['name']}: {str(e)[:40]}")
        time.sleep(0.5)

    seen = set()
    uniq = []
    for a in all_articles:
        key = hashlib.md5((a["title"] + "|" + a["url"]).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        if a.get("_cn"):
            tp = cn_topic(a["title"])
            a["dedup_key"] = hashlib.md5((a["title"] + "|" + a["source"]).encode()).hexdigest()
            a["score"] = 80
            a["priority"] = "P1"
            a["topic"] = tp
            a["tags"] = [tp.split("/")[-1], "中文", "国内", a["source"]]
            a["is_elite"] = False
        else:
            m = meta_for(a["source"], a.get("_cat", "综合"))
            a["dedup_key"] = hashlib.md5((a["title"] + "|" + a["source"]).encode()).hexdigest()
            a["score"] = m["score"]
            a["priority"] = m["priority"]
            a["topic"] = m["topic"]
            a["tags"] = m["tags"]
            a["is_elite"] = False
        if not a.get("_cn"):
            # 国外新闻：翻译成中文简述，不保留可打开的原链接
            a["keywords"] = extract_keywords(a["title"], a.get("_cat", ""))
            a["en_title"] = a["title"]
            a["summary"] = translate_zh(a.get("summary", ""), 600, tr_cache)
            a["title"] = translate_zh(a["title"], 90, tr_cache)
            a["url"] = ""
            a["tags"] = list(dict.fromkeys(a["tags"] + ["国外", "中文翻译", "无链接", "关键字"]))
        uniq.append(a)

    uniq.sort(key=lambda x: x.get("pub_time", ""), reverse=True)
    uniq = uniq[:200]
    return uniq, ok, fail


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "output", "news.json")
    data, ok, fail = build()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    cn = sum(1 for x in data if x.get("_cn"))
    comm = len(data) - cn
    print(f"\n完成：源OK={ok} FAIL={fail}，共 {len(data)} 条（大宗商品 {comm} / 国内财经 {cn}） -> {out_path}")

