# -*- coding: utf-8 -*-
"""weekend_prep.py - Sat/Sun aggregate so Monday's morning/noon boards get a stable basis.

Reads output/prices.json (fresh domestic futures incl. est_margin/day_range/trend),
writes data/weekend_summary.json with:
  monday        : next trading (Monday) date
  prepared_at   : now
  cheap_highvol_top : up to 12 domestic futures sorted by (low margin, high daily range) - the ones a small account can actually trade
  categories    : per category: avg change %, # items, top names
"""
import json, os, sys, datetime

def _fmt(v, pct=False):
    try:
        v = float(v)
    except Exception:
        return 0.0
    return round(v, 3)

def _next_monday(now=None):
    now = now or datetime.date.today()
    return now + datetime.timedelta(days=(7 - now.weekday()) % 7 or 7)

def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prices_path = os.path.join(base, "output", "prices.json")
    if not os.path.exists(prices_path):
        print("[weekend] prices.json missing, skip"); return 0
    with open(prices_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("prices") or []
    dom = [x for x in items if (x.get("market") == u"国内" and x.get("future"))]
    rows = []
    for it in dom:
        mg = _fmt(it.get("est_margin"))
        rng = _fmt(it.get("day_range_pct"))
        if mg <= 0:
            continue
        rows.append({
            "symbol": it.get("symbol"), "name": it.get("name"), "unit": it.get("unit"),
            "est_margin": mg, "future": _fmt(it.get("future")),
            "change_pct": _fmt(it.get("change_pct")), "range_pct": rng,
            "trend": it.get("trend") or "flat", "category": it.get("category")})
    rows.sort(key=lambda r: (r["est_margin"], -r["range_pct"]))
    cats = {}
    order = []
    for r in rows:
        c = r.get("category") or "综合"
        if c not in cats:
            cats[c] = {"items": [], "chg_sum": 0.0}; order.append(c)
        cats[c]["items"].append(r["name"]); cats[c]["chg_sum"] += r.get("change_pct") or 0.0
    cat_list = []
    for c in order:
        cat_list.append({
            "category": c, "count": len(cats[c]["items"]),
            "avg_change_pct": round(cats[c]["chg_sum"] / max(1, len(cats[c]["items"])), 3),
            "names": cats[c]["items"][:8]})
    pack = {
        "monday": _next_monday().isoformat(),
        "prepared_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "cheap_highvol_top": rows[:12],
        "categories": cat_list,
    }
    out_dir = os.path.join(base, "data"); os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "weekend_summary.json"), "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)
    print("[weekend] prepared %d categories / top %d cheap-highvol futures" % (len(cat_list), min(12, len(rows))))
    return 0

if __name__ == "__main__":
    sys.exit(main())
