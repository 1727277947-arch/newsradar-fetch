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
    {"name": "上海钢联Mysteel", "rss": "https://news.mysteel.com/", "kind": "cn", "parser": "mysteel"},
    {"name": "粮油豆粕", "rss": "http://www.chinagrain.cn/doupo/", "kind": "cn", "parser": "chinagrain"},
    {"name": "粮油玉米", "rss": "http://www.chinagrain.cn/yumi/", "kind": "cn", "parser": "chinagrain"},
    {"name": "粮油大豆", "rss": "http://www.chinagrain.cn/dadou/", "kind": "cn", "parser": "chinagrain"},
    {"name": "粮油小麦", "rss": "http://www.chinagrain.cn/xiaomai/", "kind": "cn", "parser": "chinagrain"},
    {"name": "粮油菜籽", "rss": "http://www.chinagrain.cn/caizi/", "kind": "cn", "parser": "chinagrain"},
    {"name": "粮油首页", "rss": "http://www.chinagrain.cn/", "kind": "cn", "parser": "chinagrain"},
]

# ---- 大宗商品全品种白名单（中文+英文关键词）----
COMMODITY_CATS = [
    ("贵金属",  ["黄金", "金价", "白银", "铂金", "钯金", "gold", "silver", "platinum", "palladium", "precious metal"]),
    ("能源",    ["原油", "石油", "油价", "wti", "布伦特", "brent", "天然气", "汽油", "燃料油", "oil", "crude", "gas", "petroleum", "energy price"]),
    ("基本金属", ["铜", "铝", "锌", "镍", "铅", "锡", "lme", "copper", "aluminum", "aluminium", "zinc", "nickel", "lead", "tin"]),
    ("黑色系",  ["铁矿石", "铁矿", "螺纹", "焦煤", "焦炭", "钢材", "钢铁", "iron ore", "steel", "coke", "futures steel"]),
    ("农产品",  ["大豆", "玉米", "小麦", "棉花", "白糖", "糖价", "豆粕", "菜粕", "棕榈油", "菜籽油", "菜油", "豆油",
                "生猪", "鸡蛋", "橡胶", "花生", "苹果", "红枣", "稻", "大米", "面粉", "玉米油", "葵花籽油", "油菜籽",
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


def _http_json(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _tr_google(text):
    """Google 免费翻译接口，译为简体中文"""
    import urllib.parse
    q = urllib.parse.quote(text)
    u = ("https://translate.googleapis.com/translate_a/single?client=gtx"
         "&sl=auto&tl=zh-CN&dt=t&q=" + q)
    d = _http_json(u, {"User-Agent": UA, "Referer": "https://translate.google.com/"})
    # 返回结构 [[["译文","原文",null,...],...],null,"en",...]
    segs = []
    for grp in d[0]:
        if isinstance(grp, list) and grp and grp[0]:
            segs.append(str(grp[0]))
    out = "".join(segs).strip()
    return out if out and len(out) > 1 else ""


def _tr_baidu(text):
    """百度免费网页接口（transapi），译为中文"""
    import urllib.parse
    q = urllib.parse.quote(text)
    u = "https://fanyi.baidu.com/transapi?query=" + q + "&from=auto&to=zh"
    d = _http_json(u, {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    arr = d.get("data") or []
    sb = []
    for o in arr:
        dst = (o or {}).get("dst")
        if dst:
            sb.append(dst)
    out = "".join(sb).strip()
    return out if out else ""


def _tr_mymemory(text):
    """MyMemory 免费接口；免费额度有限，常返回 429，作为最末兜底"""
    import urllib.parse
    q = urllib.parse.quote(text)
    u = "https://api.mymemory.translated.net/get?q=" + q + "&langpair=en|zh-CN"
    d = _http_json(u, {"User-Agent": "NewsRadar/1.0"}, timeout=8)
    out = (d.get("responseData") or {}).get("translatedText") or ""
    out = re.sub(r"\*\*\*|&quot;|&amp;", "", out).strip()
    return out


def translate_zh(text, max_len=900, cache=None):
    """把英文(自动检测)译为简体中文；逐个尝试 Google/百度/MyMemory，全部失败返回原串。"""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0]
    # 已含较多中文则视为已翻译，直接返回
    if re.search(r"[\u4e00-\u9fff]", t) and len(re.findall(r"[\u4e00-\u9fff]", t)) >= max(2, len(re.sub(r"\s", "", t)) // 4):
        return t
    h = hashlib.md5(t.encode("utf-8")).hexdigest()
    if cache is not None and h in cache:
        return cache[h]
    for fn in (_tr_google, _tr_baidu, _tr_mymemory):
        try:
            out = fn(t)
            if out and re.search(r"[\u4e00-\u9fff]", out):
                if cache is not None:
                    cache[h] = out
                return out
        except Exception:
            continue
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


# 国内：大宗商品“供需/景气事件”强词。
# 社会新闻（伤亡/餐饮/科技展会/数字产业等）没有这些词自动过滤；
# 具体品种由 commodity_cat() 保留（如油价/铜价/大豆）。
SUPPLY_DEMAND_STRONG = [
    "短缺", "过剩", "供大于求", "供不应求",
    "需求", "供应", "供给", "库存", "减产", "增产",
    "停产", "复产", "复工", "出口", "进口", "关税",
    "禁令", "制裁", "倾销", "OPEC", "欧佩克", "产量",
    "抛储", "收储", "港口", "到港", "装船",
    "涨价", "跌价", "利多", "利空",
]

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


# 国内市场上下文词：事件词命中时还需市场语境，避免 AI/数字产业等碰瓷
DOM_MARKET_CTX = [
    "期货", "现货", "大宗商品", "商品期货", "行情",
    "收评", "早盘", "午评", "合约", "价格指数",
    "油价", "铜价", "钢价", "煤价", "粮价", "棉价",
    "糖价", "猪价", "蛋价", "金价", "液化气", "原油",
]

def cn_fin(t):
    """国内：只保留大宗商品品种或“供需事件+市场语境”；社会/AI数字产业等无关全部丢弃。"""
    if is_noise_text(t, ""):
        return False
    tl = t.lower()
    for w in CN_DROP:
        if w in tl:
            return False
    if commodity_cat(t, "") is not None:
        return True
    if any(w in tl for w in SUPPLY_DEMAND_STRONG) and any(w in tl for w in DOM_MARKET_CTX):
        return True
    return False


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


def parse_mysteel(xml):
    """解析上海钢联(我的钢铁) HTML 首页：提取 news.mysteel.com/a/ 文章标题+链接+时间(从URL YYMMDDHH 还原)。"""
    now = datetime.now(timezone.utc)
    out = []
    pat = re.compile(r'<a[^>]+href="(https://news\.mysteel\.com/a/[^"]+)"[^>]*>\s*([^<]{2,120}?)\s*</a>', re.S)
    seen = set()
    for href, txt in pat.findall(xml):
        title = clean_text(txt)
        if not title or title in seen or is_bad(href):
            continue
        seen.add(title)
        pub = None; pub_time = ""
        m = re.search(r"/a/(\d{8})", href)
        if m:
            try:
                d = m.group(1)
                year = int("20" + d[0:2]); month = int(d[2:4]); day = int(d[4:6]); hour = int(d[6:8])
                pub = datetime(year, month, day, hour, 0, tzinfo=timezone.utc)
                pub_time = pub.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pub = None
        hours_ago = max(0.0, (now - pub).total_seconds() / 3600) if pub else None
        if hours_ago is None or hours_ago > TIME_WINDOW_HOURS:
            continue
        out.append({"title": title, "url": href, "summary": "",
                    "pub_time": pub_time or now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out


def parse_chinagrain(xml):
    """解析中国粮油信息网 HTML：抽取 .shtml 文章标题+链接+日期,过滤广告/供求。"""
    now = datetime.now(timezone.utc)
    out = []
    # 先拾全部 <a href=..>text..</a>，再过滤 .shtml 文章链接
    pat = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    seen = set()
    ADHINT = ("供", "出售", "召商", "代理", "招商", "联系", "电话", "活航", "活动", "联谊", "生态园", "V信", "价格请")
    for href, txt in pat.findall(xml):
        if ".shtml" not in href.lower():
            continue
        if "biz.chinagrain.cn" in href or "/ly" in href.lower():
            continue  # biz 用户广告 / 供求发布
        if not (href.startswith("http") or href.startswith("n/") or href.startswith("axfwnh/")):
            continue
        title = clean_text(txt)
        if not title or title in seen or is_bad(href):
            continue
        if any(h in title for h in ADHINT):
            continue
        # 淘汰首尾杂尾：去掉 ". "、数字、分页等前缀与 (置顶)/括号尾
        # 只剝格式噪点：点/计数前缀/（置顶），不称掉年份 2026
        title = re.sub(r"^[.\u2022\u00b7#]+\s*", "", title)
        title = re.sub(r"^\d{1,3}\s+", "", title)
        title = re.sub(r"[（(](?:\u7f6e\u9876|\u7ed1)\s*[)）]", "", title).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        full = href if href.startswith("http") else "http://www.chinagrain.cn/" + href
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/\d+\.shtml", full)
        pub = None; pub_time = ""
        if m:
            try:
                pub = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, tzinfo=timezone.utc)
                pub_time = pub.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pub = None
        hours_ago = max(0.0, (now - pub).total_seconds() / 3600) if pub else None
        if hours_ago is None or hours_ago > TIME_WINDOW_HOURS:
            continue
        out.append({"title": title, "url": full, "summary": "",
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
            if src.get("parser") == "mysteel":
                arts = parse_mysteel(xml)
            elif src.get("parser") == "chinagrain":
                arts = parse_chinagrain(xml)
            else:
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


