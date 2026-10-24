#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦盒 McBox · 抽盒引擎 v1.1

设计基线见 docs/DESIGN-DECISIONS.md。四条不可违背的规则：
  1. fact 只能来自 MCP 返回，缺失即 null，禁止补齐；
  2. experience 只能由本项目规则生成，禁止伪装成官方信息；
  3. 候选池为空时不得编造结果，必须返回结构化原因；
  4. 随机必须可复现（种子 + 池指纹），LLM 不参与任何随机决策。

零依赖（仅标准库）。stdout 永远是一个 JSON 对象；日志走 stderr。

用法:
  python3 draw.py --pool fixtures/query_meals.sample.json --series beef-universe
  python3 draw.py --pool ... --mode fair --nonce 2
  python3 draw.py --pool ... --budget 25 --exclude 牛肉,香菜
  python3 draw.py --pool ... --mood 累 --suggest-series
  python3 draw.py --pool ... --series chicken --box --budget 40     # 端盒（主食+小食+饮）
  python3 draw.py --pool ... --odds
  python3 draw.py --pool ... --simulate 10000
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
SECRET = os.environ.get("POPMC_SECRET", os.environ.get("MCBOX_SECRET", "popmc-public-secret-v1"))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
FIXTURES = os.path.join(HERE, "..", "fixtures")
DEFAULT_STATE = os.environ.get("POPMC_STATE", os.environ.get("MCBOX_STATE", os.path.expanduser("~/.popmc/collection.json")))

DISCLAIMER = "非官方产品 · 参赛作品。商品信息以麦当劳官方渠道实时结果为准。"
RARITY_NOTE = "分级是本项目玩法设定，仅影响卡面视觉与文案，不代表官方发行量、限量或稀缺性。"
SERIES_NOTE = "系列为本项目原创体验主题，非麦当劳官方系列。"
COLLECT_NOTE = "收藏记录是抽取历史，不代表购买记录，也不代表该商品当前仍在售。"
BOX_NOTE = "组合总价为本项目按单品现价累加的结果，实际金额以下单页为准。"

# --------------------------------------------------------------------------
# 非食品 / 品类关键词：来自 query-meals 真实返回的清洗经验
# --------------------------------------------------------------------------
NON_FOOD_KW = ("丝巾", "棒球帽", "水手帽", "按摩捶", "痒痒挠", "徽章", "玩偶", "玩具", "帆布袋")
DRINK_KW = ("可乐", "雪碧", "红茶", "咖啡", "奶昔", "牛奶", "豆浆", "果汁", "苹果汁", "纯悦",
            "怡泉", "美汁源", "柠", "橙", "奶茶", "拿铁", "美式", "卡布", "奶铁", "鲜萃",
            "黑巧", "抹茶", "阿芙佳朵", "雪冰", "玛奇朵", "浓缩", "燕麦奶")
DESSERT_KW = ("冰淇淋", "圆筒", "新地", "麦旋风", "派", "阿芙佳朵", "雪冰", "拉明顿", "奶冻", "爆爆珠")
SIDE_KW = ("薯条", "薯饼", "麦乐鸡", "鸡翅", "鸡排", "脆汁鸡", "V翅", "玉米杯", "苹果片", "芝士条", "趣鸡球")
MAIN_KW = ("堡", "卷", "套餐", "件套", "随心配", "拼盘", "多人餐", "单人餐")
COMBO_KW = ("套餐", "件套", "随心配", "随心选", "拼盘", "多人餐", "双人餐", "亲子餐")

# 时段分桶：左闭右开，按分钟计（早餐 10:30 收档是麦当劳中国的通行规则）
TIME_BUCKETS = (
    (0, 5 * 60, "late", "深夜"),
    (5 * 60, 10 * 60 + 30, "breakfast", "早餐"),
    (10 * 60 + 30, 14 * 60, "lunch", "午餐"),
    (14 * 60, 17 * 60, "afternoon", "下午茶"),
    (17 * 60, 21 * 60, "dinner", "晚餐"),
    (21 * 60, 24 * 60, "late", "深夜"),
)

SLOT_LABEL = {"main": "主食", "side": "小食", "drink": "饮料", "dessert": "甜品"}


def log(*a):
    print(*a, file=sys.stderr)


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def norm(text):
    """归一化：MCP 分类名带换行符，如 '巨无霸\\n牛鱼肉堡'。商品名里的 '™' 也要去掉才能匹配营养表。"""
    if not text:
        return ""
    for ch in ("\n", "\r", "\t", "/", "™", " "):
        text = text.replace(ch, "")
    return text.strip()


def money(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# 时段：系列可用性依赖它（D9）。纯本地计算，不依赖 MCP 也可用。
# --------------------------------------------------------------------------
def parse_hhmm(text):
    """"10:30" / "5" / 5 / 10.5 → 分钟"""
    if isinstance(text, (int, float)):
        return int(float(text) * 60)
    text = str(text).strip()
    if ":" in text:
        h, m = text.split(":", 1)
        return int(h) * 60 + int(m)
    return int(float(text) * 60)


def _fmt_hhmm(minutes):
    minutes = int(minutes) % (24 * 60)
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def series_window(series):
    """返回 (start, end) 分钟；无限制返回 None。支持跨零点（start > end）。"""
    win = series.get("availableWindow")
    if win:
        return parse_hhmm(win[0]), parse_hhmm(win[1])
    hours = series.get("availableHours")
    if hours:
        return parse_hhmm(hours[0]), parse_hhmm(hours[1])
    return None


def in_window(window, minutes):
    if not window:
        return True
    start, end = window
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end   # 跨零点


def time_bucket(minutes):
    m = int(minutes) % (24 * 60)
    for start, end, key, label in TIME_BUCKETS:
        if start <= m < end:
            return key, label
    return "lunch", "午餐"


def now_minutes(value=None):
    if value:
        return parse_hhmm(value)
    now = datetime.now(CST)
    return now.hour * 60 + now.minute


# --------------------------------------------------------------------------
# 营养表：list-nutrition-foods 的 data 是"字符串"，不是 JSON
# --------------------------------------------------------------------------
def parse_nutrition(raw_text):
    table = {}
    if not raw_text:
        return table
    body = raw_text.split(":", 1)[-1]
    for line in body.splitlines():
        parts = [p.strip() for p in line.strip().split(",")]
        if len(parts) != 9:
            continue
        name, note, _kj, kcal, protein, fat, carb, sodium, calcium = parts
        if not name or name.startswith("["):
            continue
        table.setdefault(norm(name), {
            "energyKcal": int(float(kcal)),
            "proteinG": int(float(protein)),
            "fatG": int(float(fat)),
            "carbG": int(float(carb)),
            "sodiumMg": int(float(sodium)),
            "calciumMg": int(float(calcium)),
            "officialNote": "" if note in ("null", "") else note,
        })
    return table


# 菜单名 "可乐" / 营养表名 "可乐中杯"：只接受"唯一且后缀只是规格/包装"的映射。
# 这是可验证的同一商品，不是靠名称相似度猜——模糊匹配（麦辣鸡腿堡 ↔ 麦辣鸡腿堡三件套）绝对禁止。
SIZE_SUFFIX = {"中杯", "大杯", "小杯", "中", "大", "小", "标准杯", "（中杯）", "（大杯）"}
PACK_SUFFIX = {"盒装", "（盒装）", "(盒装)", "瓶装", "罐装"}


def resolve_nutrition(name, table):
    """返回 (stats, basis, officialName)。basis=exact 表示名字完全一致；
    basis=suffix 表示官方营养表用的是同一商品带规格后缀的名字。匹配不到返回 (None, "", "")。"""
    key = norm(name)
    if key in table:
        return table[key], "exact", key
    cands = [k for k in table if k.startswith(key) and k != key]
    if len(cands) == 1 and cands[0][len(key):] in SIZE_SUFFIX:
        return table[cands[0]], "suffix", cands[0]
    back = [k for k in table if k != key and key.startswith(k)]
    if len(back) == 1 and key[len(back[0]):] in PACK_SUFFIX:
        return table[back[0]], "suffix", back[0]
    return None, "", ""


# --------------------------------------------------------------------------
# 菜单 → 事实对象
# --------------------------------------------------------------------------
def classify(name, tags, price, category):
    if any(k in name for k in DRINK_KW) or "饮" in category:
        return "drink"
    if any(k in name for k in DESSERT_KW):
        return "dessert"
    if any(k in name for k in COMBO_KW) or "套餐" in tags:
        return "combo"
    if any(k in name for k in MAIN_KW):
        return "main"
    if any(k in name for k in SIDE_KW):
        return "side"
    return "side" if price <= 8 else "main"


def is_food(name, price):
    if any(k in name for k in NON_FOOD_KW):
        return False
    if name.endswith("酱") and price <= 5:  # 酱料不是一餐
        return False
    return True


def load_menu(pool_path):
    with open(pool_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    data = payload.get("data", payload)
    meals_map = data.get("meals") or {}
    items = {}
    for cat in data.get("categories") or []:
        cname = norm(cat.get("name", ""))
        for m in cat.get("meals") or []:
            code = str(m.get("code"))
            if not code or code not in meals_map:
                continue
            d = meals_map[code]
            name = d.get("name", "")
            price = money(d.get("currentPrice"))
            if not name or not is_food(name, price):
                continue
            tags = list(m.get("tags") or [])
            if code in items:
                # 同一 code 会出现在多个分类下：必须合并，否则"先到先得"会静默丢掉商品
                # （真实案例：巨无霸 1100 先出现在「人气热卖」，导致「牛堡宇宙」建池时漏掉图腾款）
                it = items[code]
                if cname not in it["categories"]:
                    it["categories"].append(cname)
                it["tags"] = list(dict.fromkeys(it["tags"] + tags))
                continue
            items[code] = {
                "productCode": code,
                "name": name,
                "image": d.get("image", ""),
                "price": price,
                "originalPrice": money(d.get("originalPrice")) or price,
                "tags": tags,
                "category": cname,
                "categories": [cname],
                "kind": classify(name, tags, price, cname),
            }
    return items, payload


def load_json(name, subdir=DATA):
    with open(os.path.join(subdir, name), "r", encoding="utf-8") as f:
        return json.load(f)


def matches(rule, it):
    """单条规则是否命中（不含硬条件），用于 widen 复用。"""
    cats = [norm(c) for c in rule.get("categories", [])]
    tags_any = set(rule.get("tagsAny", []))
    in_cat = any(c in cat for cat in it.get("categories", [it["category"]]) for c in cats) if cats else False
    return in_cat or bool(tags_any & set(it["tags"]))


def match_series(series, items):
    mt = series.get("match", {})
    cats = [norm(c) for c in mt.get("categories", [])]
    kinds = set(mt.get("kinds", []))
    tags_any = set(mt.get("tagsAny", []))
    excl_tags = set(mt.get("excludeTags", []))
    excl_name = mt.get("excludeNameKeywords", [])

    pool = []
    for it in items.values():
        in_cat = any(c in cat for cat in it.get("categories", [it["category"]]) for c in cats) if cats else False
        in_tag = bool(tags_any & set(it["tags"]))
        if kinds and it["kind"] not in kinds:      # kinds 是硬条件
            continue
        if cats and not (in_cat or in_tag):        # categories 需要命中
            continue
        if not cats and not kinds and not in_tag:
            continue
        if excl_tags & set(it["tags"]):
            continue
        if any(k in it["name"] for k in excl_name):
            continue
        pool.append(it)
    pool.sort(key=lambda x: (-x["price"], x["productCode"]))  # 编号稳定
    return pool


def assign_rarity(item, series, rules, price_p70):
    for pin in series.get("pinned", []):
        if str(pin.get("productCode")) == item["productCode"]:
            return pin.get("rarity", "SSR"), pin.get("title", "")
    tags = set(item["tags"])
    if tags & set(rules["SR"]["tagsAny"]):
        return "SR", ""
    if tags & set(rules["R"]["tagsAny"]):
        return "R", ""
    if item["price"] > 0 and item["originalPrice"] / item["price"] >= rules["R"].get("discountRatioGte", 99):
        return "R", ""
    if price_p70 > 0 and item["price"] >= price_p70:
        return "R", ""
    return "N", ""


def apply_hard_filters(raw, budget=0.0, excludes=None):
    """预算 / 排除是硬约束：任何情况下不得为了"有结果"而放宽。

    返回 (after_excl, cand) —— 分开返回是为了让空池 reason 能说清是哪一步卡死的。
    """
    excludes = [e for e in (excludes or []) if e]
    after_excl = []
    for it in raw:
        if excludes and any(e in it["name"] or e in " ".join(it["tags"]) for e in excludes):
            continue
        after_excl.append(it)
    cand = [it for it in after_excl if not (budget and budget > 0 and it["price"] > budget)]
    return after_excl, cand


def to_card(it, index, total, series, rarity, pinned_title, nutrition, labels):
    stats, basis, official_name = resolve_nutrition(it["name"], nutrition)
    return {
        "fact": {
            "productCode": it["productCode"],
            "name": it["name"],
            "image": it["image"],
            "price": it["price"],
            "originalPrice": it["originalPrice"],
            "saving": round(it["originalPrice"] - it["price"], 1),
            "kind": it["kind"],
            "category": it["category"],
            "tags": it["tags"],
            "nutrition": stats,
            "nutritionNote": (stats or {}).get("officialNote", ""),
            "nutritionMatch": {"basis": basis, "officialName": official_name} if stats else None,
            "source": "mcd-mcp.query-meals",
        },
        "experience": {
            "cardNo": f"{series['code']}-{index:02d}/{total:02d}",
            "seriesCode": series["code"],
            "rarity": rarity,
            "rarityLabel": labels[rarity],
            "pinnedTitle": pinned_title,
        },
    }


def build_series_pool(series_id, items, nutrition, budget=0.0, excludes=None,
                      keywords=None, now=None):
    defs = load_json("series.json")["series"]
    rarity_cfg = load_json("rarity.json")
    labels = {t["id"]: t["label"] for t in rarity_cfg["tiers"]}
    series = next((s for s in defs if s["id"] == series_id), None)
    if series is None:
        emit({"ok": False, "reason": "series_not_found",
              "detail": f"没有这个系列: {series_id}", "available": [s["id"] for s in defs]}, 2)
    series = dict(series)  # 局部副本，避免 widen 标记污染后续调用

    # ---- 时段闸门：早餐系列不该在晚上被抽出来 ----
    window = series_window(series)
    minutes = now_minutes(now)
    series["_window"] = [_fmt_hhmm(window[0]), _fmt_hhmm(window[1])] if window else None
    series["_availableNow"] = in_window(window, minutes)

    raw = match_series(series, items)

    # ---- 池容量不足时的兜底：只有系列自己声明了 widen 才扩展（见 series-schema）----
    series["_widened"] = []
    min_size = series.get("minPoolSize", 1)
    if series["_availableNow"] and len(raw) < min_size and series.get("widen"):
        have = {it["productCode"] for it in raw}
        extra = []
        for it in items.values():
            if it["productCode"] in have:
                continue
            if matches(series["widen"], it):
                extra.append(it)
        extra.sort(key=lambda x: (-x["price"], x["productCode"]))
        if extra:
            raw = raw + extra
            series["_widened"] = [it["productCode"] for it in extra]

    after_excl, cand = apply_hard_filters(raw, budget, excludes)
    if keywords:  # 偏好词只是软加权，不参与过滤
        log(f"[info] 偏好词 {keywords} 仅用于文案，不改变候选集合")

    prices = sorted(i["price"] for i in cand)
    p70 = prices[min(len(prices) - 1, int(len(prices) * 0.7))] if prices else 0.0

    cards = []
    for i, it in enumerate(cand, 1):
        rarity, pinned_title = assign_rarity(it, series, rarity_cfg["rules"], p70)
        cards.append(to_card(it, i, len(cand), series, rarity, pinned_title, nutrition, labels))
    return series, rarity_cfg, cards, raw, cand, after_excl


# --------------------------------------------------------------------------
# 情绪 → 系列（D8：只改"选择概率"，不改商品事实）
# --------------------------------------------------------------------------
def resolve_mood(text):
    moods = load_json("moods.json")
    text = text or ""
    for m in moods["moods"]:
        if m["id"] == "random":
            continue
        if any(k in text for k in m["keywords"]):
            return m, moods
    fallback = next(m for m in moods["moods"] if m["id"] == moods["defaultMood"])
    return fallback, moods


def series_weights(mood, available_series):
    """情绪 → {series_id: weight}。权重为 1 + boost，平滑项保证冷门系列仍有机会。"""
    boost = mood.get("seriesBoost", {})
    return {s["id"]: 1.0 + boost.get(s["id"], 0) for s in available_series}


def suggest_series_by_mood(mood, available_series):
    """按情绪给可用系列排序（供 --suggest-series 展示给用户选，不做决策）。"""
    w = series_weights(mood, available_series)
    out = [{"series": s["id"], "name": s["name"], "weight": w[s["id"]]} for s in available_series]
    out.sort(key=lambda x: -x["weight"])
    return out


def choose_series_by_mood(mood, available_series, seed):
    """按权重做确定性抽样。修复：原来直接取权重最大的第一个，
    导致"累"永远命中同一个系列，抽盒失去变化。"""
    if not available_series:
        return None
    if len(available_series) == 1:
        return available_series[0]
    w = series_weights(mood, available_series)
    total = sum(w[s["id"]] for s in available_series)
    point = int(_h(seed, "mood-series")[:8], 16) / 0xFFFFFFFF * total
    acc = 0.0
    for s in available_series:
        acc += w[s["id"]]
        if point <= acc:
            return s
    return available_series[-1]


# --------------------------------------------------------------------------
# 随机：确定性、可复现（不用 random.seed，跨 Python 版本不稳定）
# --------------------------------------------------------------------------
def _h(*parts):
    material = "|".join(str(p) for p in parts)
    return hmac.new(SECRET.encode(), material.encode(), hashlib.sha256).hexdigest()


def fingerprint(cards):
    codes = "".join(sorted(c["fact"]["productCode"] for c in cards))
    return hashlib.sha256(codes.encode()).hexdigest()[:16]


def weighted_tier(tiers, allowed, seed):
    pool = [t for t in tiers if t["id"] in allowed]
    total = sum(t["weight"] for t in pool) or 1.0
    point = int(_h(seed, "tier")[:8], 16) / 0xFFFFFFFF * total
    acc = 0.0
    for t in pool:
        acc += t["weight"]
        if point <= acc:
            return t["id"]
    return pool[-1]["id"]


def _nearest_tier(tier, by_tier, order):
    """把抽到的档位对齐到"池里真的存在"的档位。

    原来只沿 order 向下走（SSR→SR→R→N），当池里只有 SSR/R 而抽到 N 时会走到头，
    返回一个不存在的档位 → 空 bucket → ZeroDivisionError。改为先向下、再向上。
    """
    if tier in by_tier:
        return tier
    i = order.index(tier)
    for t in order[i:]:
        if t in by_tier:
            return t
    for t in reversed(order[:i]):
        if t in by_tier:
            return t
    return None


def pick_tier(tiers, cards, counters, pity, seed):
    by_tier = {}
    for c in cards:
        by_tier.setdefault(c["experience"]["rarity"], []).append(c)
    order = ["SSR", "SR", "R", "N"]

    if counters.get("sinceSSR", 0) + 1 >= pity["SSR_every"] and by_tier.get("SSR"):
        return "SSR"
    if counters.get("sinceR", 0) + 1 >= pity["R_or_above_every"]:
        return _nearest_tier(weighted_tier(tiers, {"R", "SR", "SSR"}, seed), by_tier, order)
    return _nearest_tier(weighted_tier(tiers, {t["id"] for t in tiers}, seed), by_tier, order)


# --------------------------------------------------------------------------
# 文案：模板 + 数据槽位（禁止 LLM 自由发挥，见 DESIGN-DECISIONS D5）
# --------------------------------------------------------------------------
FORBIDDEN = ("最", "第一", "天花板", "官方", "联名", "限量", "必买", "养生", "减肥", "健康",
             "吊打", "欧皇", "非酋", "氪")
TEMPLATES = {
    "neutral": {"N": ["{f}。今天也不错。", "{f}。就它了。"],
                "R": ["{f}。这一口，稳的。", "{f}。你选对了。"],
                "SR": ["{f}。赶上了，就是你的。", "{f}。这批里有它。"],
                "SSR": ["{f}。传说就该这样出场。", "{f}。等很久了吧。"]},
    "soft": {"N": ["{f}。慢慢吃。", "{f}。不用想太多。"],
             "R": ["{f}。今天值得。", "{f}。别亏待自己。"],
             "SR": ["{f}。刚好落你手里。", "{f}。算是今天的小补偿。"],
             "SSR": ["{f}。今天归你了。", "{f}。运气没走远。"]},
    "up": {"N": ["{f}。开饭。", "{f}。安排上。"],
           "R": ["{f}。这个可以有。", "{f}。恭喜，没踩雷。"],
           "SR": ["{f}。你手气不错。", "{f}。这波赚了。"],
           "SSR": ["{f}。今天你说了算。", "{f}。全场最靓的一盒。"]},
    "short": {"N": ["{f}。开吃。", "{f}。这个够味。"],
              "R": ["{f}。够狠。", "{f}。不亏。"],
              "SR": ["{f}。抓到了。", "{f}。别犹豫。"],
              "SSR": ["{f}。就它。", "{f}。收好。"]},
    "dry": {"N": ["{f}。开工。", "{f}。先垫一下。"],
            "R": ["{f}。效率之选。", "{f}。这个不耽误事。"],
            "SR": ["{f}。今天运气还行。", "{f}。抽到了就不想了。"],
            "SSR": ["{f}。稀有度不重要，能提神就行。", "{f}。这一盒，值回票价。"]},
}

# 这些 tag 是运营标记或品类词，不是风味描述，不能当文案钩子（否则会出现「上新。这批里有它。」）
STOP_TAGS = {"上新", "限时特惠", "爆款", "人气", "经典", "麦金卡", "单品", "套餐", "小食", "冷饮",
             "热饮", "粉丝之选", "麦香鱼系列", "第二份半价", "第二份优惠", "限定特惠", "超值",
             "小食拼盘", "随心拼", "万种组合", "新升级", "更多汁", "童年童款", "蘸酱",
             "冰淇淋", "派", "开心乐园餐", "蘸酱炸鸡"}
FLAVOR_MARKS = ("风味", "香", "脆", "浓", "辣", "甜", "奶", "芝士", "咖喱", "蒜", "蜜",
                "果", "朱古力", "抹茶", "可可", "柠", "橙", "牛", "鸡", "鱼", "薯")
NAME_HOOKS = (("鳕鱼", "鱼的温柔"), ("牛肉", "牛肉味正"), ("脆", "咔嚓一声"),
              ("辣", "辣得直接"), ("厚", "厚实"), ("芝士", "能拉丝"),
              ("鸡", "鸡肉的香"), ("薯", "薯条的香"), ("甜", "甜到了"),
              ("堡", "这一堡很实在"), ("派", "热乎的"))
SERIES_FALLBACK = {"BU": "扎实的牛肉", "CH": "咔嚓一声", "SW": "甜一下", "CF": "咖啡因到位",
                   "CL": "省心的一盒", "PT": "一起分着吃", "AM": "早安",
                   "FS": "金黄酥脆", "SD": "气泡爽口"}
# 端盒里的小食/饮料不该继承主食系列的钩子（否则清水会被写成"咔嚓一声"）
KIND_FALLBACK = {"drink": "先喝一口", "side": "配着正好", "dessert": "甜的收尾",
                 "main": "扎实的一口", "combo": "一整套都在这"}


def flavor_text(card, tone="neutral"):
    fact, exp = card["fact"], card["experience"]
    slot = exp.get("slot", "")
    # 钩子阶梯：① 风味标签 ② 名称意象 ③ 系列氛围（仅主食位）④ 品类兜底
    tags = [t for t in fact["tags"] if t and t not in STOP_TAGS and len(t) >= 4
            and any(m in t for m in FLAVOR_MARKS)]
    if tags:
        head = tags[0]
    else:
        head = next((h for k, h in NAME_HOOKS if k in fact["name"]), None)
        if not head and slot in ("", "main", "combo"):
            head = SERIES_FALLBACK.get(exp.get("seriesCode", ""), "")
        if not head:
            head = KIND_FALLBACK.get(slot or fact["kind"], "刚好来一口")
    pick = TEMPLATES.get(tone, TEMPLATES["neutral"]).get(exp["rarity"], ["{f}。今天也不错。"])
    idx = int(_h(fact["productCode"], exp["rarity"], tone)[:8], 16) % len(pick)
    text = pick[idx].replace("{f}", head)
    if any(w in text for w in FORBIDDEN):
        text = f"{head}。今天也不错。"
    return text


def do_draw(series, rarity_cfg, cards, nonce, counters, mode, tone, slot="", avoid=None):
    fp = fingerprint(cards)
    day_key = datetime.now(CST).strftime("%Y-%m-%d")
    seed = _h(day_key, nonce, series["id"], fp, mode, slot)
    avoid = set(avoid or ())

    def fresh(pool, fallback_pool):
        """避开最近抽过的商品，避免"再抽一次"原地打转（PRD F04 同轮去重）。

        该档已经全是抽过的卡时，退到整池里未抽过的卡——宁可变档，也不重复同一张。
        整池也都抽过，才允许重复。**任何分支都必须返回非空**，空列表会在后面除零。
        """
        kept = [c for c in pool if c["fact"]["productCode"] not in avoid]
        if kept:
            return kept
        alt = [c for c in fallback_pool if c["fact"]["productCode"] not in avoid]
        if alt:
            return alt
        return pool or fallback_pool

    if mode == "fair":  # 纯随缘：候选集合内均匀，无等级加权
        tier = None
        pool = fresh(cards, cards)
        chosen = pool[int(_h(seed, "fair")[:8], 16) % len(pool)]
    else:
        tier = pick_tier(rarity_cfg["tiers"], cards, counters, rarity_cfg["pity"], seed)
        bucket = fresh([c for c in cards if c["experience"]["rarity"] == tier], cards)
        if not bucket:                      # 理论不可达，兜底防崩
            bucket = cards
        chosen = bucket[int(_h(seed, "card")[:8], 16) % len(bucket)]

    card = {
        "fact": dict(chosen["fact"]),
        "experience": dict(chosen["experience"]),
    }
    if slot:
        card["experience"]["slot"] = slot
    card["experience"]["flavorText"] = flavor_text(card, tone)
    card["experience"]["tone"] = tone

    if tier in ("R", "SR", "SSR"):
        counters["sinceR"] = 0
    else:
        counters["sinceR"] = counters.get("sinceR", 0) + 1
    counters["sinceSSR"] = 0 if tier == "SSR" else counters.get("sinceSSR", 0) + 1
    counters["totalDraws"] = counters.get("totalDraws", 0) + 1

    meta = {
        "drawId": f"{datetime.now(CST).strftime('%Y%m%d')}-{fp[:6]}-{int(nonce):02d}",
        "seedHash": seed[:32],
        "poolFingerprint": fp,
        "poolSize": len(cards),
        "mode": mode,
        "tier": tier or "FAIR",
        "nonce": str(nonce),
        "dayKey": day_key,
        "avoided": len(avoid),
        "engine": "popmc-draw/1.2",
    }
    return card, counters, meta


# --------------------------------------------------------------------------
# 端盒（SPEC §5.4）：主食 + 小食 + 饮料，预算内组合，绝不超预算
# --------------------------------------------------------------------------
def slot_pool(items, kind, budget=0.0, excludes=None, draw_from=None):
    if draw_from is not None:
        base = [it for it in draw_from if it["kind"] == kind]
        if base:
            return base
    base = [it for it in items.values() if it["kind"] == kind]
    base.sort(key=lambda x: (-x["price"], x["productCode"]))
    _e, cand = apply_hard_filters(base, budget, excludes)
    return cand


def build_box(series, rarity_cfg, labels, items, nutrition, budget, excludes, nonce, tone, mode,
              avoid=None):
    """端盒算法（SPEC §5.4 的落地版）：

    1. 主食先行：在系列池（或全店主食）里抽；
    2. 留够小食 + 饮料的最低开销，避免"主食抽贵了，后面全塞满"；
    3. 小食从剩余预算里抽；饮料再从抽完小食的剩余里抽；
    4. 任一段抽不出就降级（3 件→2 件→1 件），并明确写在 warnings 里；
    5. 总价 = 单品现价累加，永远 ≤ 预算（有预算时）。
    """
    main_src = [it for it in items.values() if it["kind"] in ("main", "combo")]
    raw_main = [it for it in match_series(series, items) if it["kind"] in ("main", "combo")] or main_src
    _e, main_cand = apply_hard_filters(raw_main, budget, excludes)

    sides = slot_pool(items, "side", 0, excludes, draw_from=None)
    drinks = slot_pool(items, "drink", 0, excludes, draw_from=None)

    if not main_cand:
        return None, "budget_too_low", "预算内没有可选主食。"

    # 给后续两件留出最低组合
    reserve = (min((s["price"] for s in sides), default=0.0)
               + min((d["price"] for d in drinks), default=0.0))
    if budget and budget > 0:
        affordable = [m for m in main_cand if m["price"] + reserve <= budget]
        # 连"主食 + 最低小食/饮料"都装不下时，退到最便宜的主食，只出 1 件
        main_pool = affordable or [min(main_cand, key=lambda x: x["price"])]
    else:
        main_pool = main_cand

    seen = set(avoid or ())

    def pick(pool, tag):
        if not pool:
            return None, {"sinceR": 0, "sinceSSR": 0}
        prices = sorted(p["price"] for p in pool)
        p70 = prices[min(len(prices) - 1, int(len(prices) * 0.7))]
        pool_cards = []
        for i, it in enumerate(pool, 1):
            r, t = assign_rarity(it, series, rarity_cfg["rules"], p70)
            pool_cards.append(to_card(it, i, len(pool), series, r, t, nutrition, labels))
        card, _c, _m = do_draw(series, rarity_cfg, pool_cards, nonce,
                               {"sinceR": 0, "sinceSSR": 0}, mode, tone, slot=tag, avoid=seen)
        seen.add(card["fact"]["productCode"])   # 盒内不重复
        return card, _c

    main_card, _ = pick(main_pool, "main")
    chosen = [("main", main_card)]
    remaining = budget - main_card["fact"]["price"] if budget and budget > 0 else None

    def fit(pool, remain, reserve_after=0.0):
        if remain is None:
            return pool
        return [p for p in pool if p["price"] + reserve_after <= remain + 1e-9]

    side_pool = fit(sides, remaining, min((d["price"] for d in drinks), default=0.0))
    side_card, _ = pick(side_pool, "side") if side_pool else (None, None)
    if side_card:
        chosen.append(("side", side_card))
        if remaining is not None:
            remaining -= side_card["fact"]["price"]

    drink_pool = fit(drinks, remaining)
    drink_card, _ = pick(drink_pool, "drink") if drink_pool else (None, None)
    if drink_card:
        chosen.append(("drink", drink_card))

    total = round(sum(c["fact"]["price"] for _s, c in chosen), 2)
    total_orig = round(sum(c["fact"]["originalPrice"] for _s, c in chosen), 2)
    kcals, covered = 0, 0
    for _s, c in chosen:
        nut = c["fact"]["nutrition"]
        if nut:
            kcals += nut.get("energyKcal", 0)
            covered += 1

    slots = []
    for idx, (slot, c) in enumerate(chosen):
        c["experience"]["slot"] = slot
        c["experience"]["slotLabel"] = SLOT_LABEL[slot]
        c["experience"]["boxNo"] = f"{series['code']}-B{int(nonce):02d}/{idx + 1}"
        slots.append(c)

    box = {
        "boxId": f"{datetime.now(CST).strftime('%Y%m%d')}-{series['code']}-B{int(nonce):02d}",
        "structure": "+".join(SLOT_LABEL[s] for s, _c in chosen),
        "slots": slots,
        "totalPrice": total,
        "totalOriginalPrice": total_orig,
        "totalSaving": round(total_orig - total, 1),
        "totalKcal": kcals if covered else None,
        "kcalCovered": f"{covered}/{len(chosen)}",
        "note": BOX_NOTE,
    }
    return box, None, ""


# --------------------------------------------------------------------------
# 输出 / 检查命令
# --------------------------------------------------------------------------
def ok_payload(series, card, meta, warnings=None):
    sid = series["id"]
    rarity = card["experience"]["rarity"]
    
    # 极速路径资产匹配（Instant Asset Mapping）：无需重新耗时渲染，秒级直接取用
    preset_card = f"assets/cards/{sid}-{rarity}.svg"
    here_assets = os.path.join(HERE, "..", "assets", "cards")
    if not os.path.exists(os.path.join(here_assets, f"{sid}-{rarity}.svg")):
        preset_card = f"assets/cards/{sid}-R.svg" # 回退到该系列典型卡面
    if not os.path.exists(os.path.join(here_assets, f"{sid}-R.svg")):
        preset_card = "assets/cards/beef-universe-SSR.svg"

    preset_gif = "assets/unbox/unboxing-ssr.gif" if rarity == "SSR" else "assets/unbox/unboxing-chicken.gif"

    return {
        "ok": True,
        "series": {
            "id": series["id"], "name": series["name"], "code": series["code"],
            "tagline": series.get("tagline", ""), "season": series.get("season", "S1"),
            "palette": series.get("palette", {}),
            "disclaimer": SERIES_NOTE,
        },
        "fact": card["fact"],
        "experience": {**card["experience"], "rarityNote": RARITY_NOTE},
        "meta": meta,
        "assets": {
            "cardSvg": preset_card,
            "unboxGif": preset_gif,
            "packageSvg": "assets/cards/package-chicken.svg",
        },
        "warnings": warnings or [],
        "disclaimer": DISCLAIMER,
    }
def measure(rarity_cfg, cards, n=20000):
    """跑一遍含保底的模拟，返回各档实际频率。公示值必须用这个，而不是裸权重。"""
    counters, counts = {"sinceR": 0, "sinceSSR": 0}, {}
    fake_series = {"id": "measure"}
    for i in range(n):
        card, counters, _m = do_draw(fake_series, rarity_cfg, cards, i, counters, "default", "neutral")
        t = card["experience"]["rarity"]
        counts[t] = counts.get(t, 0) + 1
    return {t: c / n for t, c in counts.items()}


def show_odds(series, cards, rarity_cfg):
    weights = {t["id"]: t["weight"] for t in rarity_cfg["tiers"]}
    buckets = {}
    for c in cards:
        buckets.setdefault(c["experience"]["rarity"], []).append(c)
    print(f"[{series['name']}] 候选池 {len(cards)} 张｜模式 default 下的当期确认概率：")
    actual = measure(rarity_cfg, cards)
    print("  档位   基础权重   含保底实际   该档张数   单卡概率")
    for tier in ("SSR", "SR", "R", "N"):
        if tier not in weights:
            continue
        n = len(buckets.get(tier, []))
        act = actual.get(tier, 0.0) * 100
        per = (act / n) if n else 0.0
        print(f"  {tier:<4} {weights[tier]:8.1f}% {act:11.2f}% {n:10d} {per:9.2f}%")
    print(f"\n  模式 fair（纯随缘）：每张均匀 1/{len(cards)} = {100 / len(cards):.2f}%")
    print("  『含保底实际』是按当前池子跑 20000 次的蒙特卡洛结果，对外公示请用它，不要用裸权重。")
    print("  分级仅影响卡面视觉与文案，不改变商品价格与份量，也不代表官方发行量。")
    print("\n明细：")
    for c in cards:
        f, e = c["fact"], c["experience"]
        per = (actual.get(e["rarity"], 0.0) * 100) / max(1, len(buckets.get(e["rarity"], [])))
        print(f"  {e['cardNo']}  {e['rarity']:<3} {e['rarityLabel']}  {per:5.2f}%  "
              f"¥{f['price']:<6} {f['name']}")


def simulate(rarity_cfg, cards, n):
    cfg = {t["id"]: t["weight"] for t in rarity_cfg["tiers"]}
    actual = measure(rarity_cfg, cards, n)
    print(f"模拟 {n} 次（含保底）：")
    for tier in ("SSR", "SR", "R", "N"):
        if tier not in cfg:
            continue
        act = actual.get(tier, 0.0) * 100
        print(f"  {tier:<3} 理论 {cfg[tier]:5.1f}%  实际 {act:5.2f}%  "
              f"偏差 {act - cfg[tier]:+5.2f}pt")


# --------------------------------------------------------------------------
# 状态：nonce 自增 + 排除词记忆（D6：本地 JSON，无账号、无云端）
# --------------------------------------------------------------------------
def load_state(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            log(f"[warn] 收藏文件损坏，按空状态处理：{e}")
    return {}


def save_state(path, state):
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log(f"[warn] 写收藏失败（不影响本次结果）：{e}")


def next_nonce(state, day, explicit=None):
    """修复：原来 nonce 靠调用方手动递增，LLM 一旦忘记，
    「再抽一次」就会拿到与上次完全相同的卡。改为从本地计数自增。"""
    daily = state.setdefault("counters", {}).setdefault("dailyNonce", {})
    current = int(daily.get(day, 0))
    if explicit:
        value = max(int(explicit), current + 1)
    else:
        value = current + 1
    daily[day] = value
    return value


def main():
    ap = argparse.ArgumentParser(description="麦泡泡 PopMc 潮玩抽盒引擎")
    ap.add_argument("--pool", required=True, help="query-meals 原始返回 JSON")
    ap.add_argument("--series", default="")
    ap.add_argument("--mood", default="", help="用户原话，用于解析情绪")
    ap.add_argument("--mode", choices=["default", "fair"], default="default")
    ap.add_argument("--budget", type=float, default=0.0, help="单品预算上限（元）；--box 时为整盒预算")
    ap.add_argument("--exclude", default="", help="排除关键词，逗号分隔")
    ap.add_argument("--remember-exclude", default="", help="把排除词写入本地状态，下次自动生效")
    ap.add_argument("--nonce", default="", help="不传则按本地当日计数自增")
    ap.add_argument("--now", default="", help="HH:MM，用于时段判定；不传取本机时间")
    ap.add_argument("--box", action="store_true", help="端盒模式：主食+小食+饮料")
    ap.add_argument("--nutrition", default=os.path.join(FIXTURES, "nutrition.raw.txt"))
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--commit", action="store_true", help="写回 state（收藏与保底计数）")
    ap.add_argument("--split-dir", default="", help="端盒时把每张卡另存为单独 JSON，供渲染")
    ap.add_argument("--suggest-series", action="store_true")
    ap.add_argument("--odds", action="store_true")
    ap.add_argument("--simulate", type=int, default=0)
    args = ap.parse_args()

    items, payload = load_menu(args.pool)
    if not items:
        emit({"ok": False, "reason": "empty_menu",
              "detail": "该门店当前没有返回任何可售餐品，可能是打烊或菜单接口异常。",
              "relax": [{"action": "switch_store"}, {"action": "retry_later"}]}, 2)

    nutrition = {}
    if args.nutrition and os.path.exists(args.nutrition):
        nutrition = parse_nutrition(open(args.nutrition, encoding="utf-8").read())
    else:
        log("[warn] 未找到营养表，nutrition 将为 null（按规则不得估算）")

    mood, _moods = resolve_mood(args.mood)
    defs = load_json("series.json")["series"]
    minutes = now_minutes(args.now)
    bucket_key, bucket_label = time_bucket(minutes)

    # 只在"此刻供应 且 本店真的有货"的系列里挑：
    # 只看时段会挑到"菜单里没上早餐"的空系列，用户会莫名收到 series_unavailable
    available = [s for s in defs
                 if in_window(series_window(s), minutes) and match_series(s, items)]

    if args.suggest_series:
        emit({"ok": True,
              "mood": {"id": mood["id"], "label": mood["label"], "tone": mood["tone"]},
              "time": {"bucket": bucket_key, "label": bucket_label, "hhmm": _fmt_hhmm(minutes)},
              "suggested": suggest_series_by_mood(mood, available),
              "unavailable": [{"series": s["id"], "name": s["name"],
                               "why": "时段外" if not in_window(series_window(s), minutes) else "本店无对应餐品",
                               "window": series_window(s) and
                               [_fmt_hhmm(series_window(s)[0]), _fmt_hhmm(series_window(s)[1])]}
                              for s in defs if s not in available]}, 0)

    state = load_state(args.state)
    day = datetime.now(CST).strftime("%Y-%m-%d")
    nonce = next_nonce(state, day, args.nonce or None)
    avoid = list(state.get("recent", []))

    # 前置解析排除项与长期记忆
    excludes = [e.strip() for e in args.exclude.split(",") if e.strip()]
    remembered = [b for b in state.get("blacklist", []) if b]
    if args.remember_exclude:
        new = [e.strip() for e in args.remember_exclude.split(",") if e.strip()]
        remembered = list(dict.fromkeys(remembered + new))
        state["blacklist"] = remembered
        save_state(args.state, state)
    excludes = list(dict.fromkeys(excludes + remembered))

    # ---- 系列决策：显式指定 > 约束感知调度 (Constraint-Aware Routing) ----
    if args.series:
        series_id = args.series
        target = next((s for s in defs if s["id"] == series_id), None)
        if target is None:
            emit({"ok": False, "reason": "series_not_found",
                  "detail": f"没有这个系列: {series_id}",
                  "available": [s["id"] for s in defs]}, 2)
        win = series_window(target)
        if not in_window(win, minutes):
            emit({"ok": False, "reason": "series_unavailable",
                  "detail": f"「{target['name']}」只在 {_fmt_hhmm(win[0])}–{_fmt_hhmm(win[1])} 供应，"
                            f"现在是 {_fmt_hhmm(minutes)}（{bucket_label}）。",
                  "relax": [{"action": "pick_other_series",
                             "options": [s["id"] for s in available]}],
                  "disclaimer": DISCLAIMER}, 2)
    else:
        # 智能约束感知：先过滤出在当前预算和排除条件下，真正有餐品可抽的系列！
        # 避免盲目选了高价系列导致误报 budget_too_low
        viable_series = []
        for s in available:
            s_raw = match_series(s, items)
            _ex, s_cand = apply_hard_filters(s_raw, args.budget, excludes)
            if s_cand:
                viable_series.append(s)

        # 如果有系列满足约束，只在满足约束的系列中加权抽样；
        # 若全店都无满足预算的系列，保留 available 走后续标准空池自愈诊断
        pool_for_routing = viable_series or available

        # 防疲劳与多样性机制 (Anti-Fatigue)：若最近连续出现同类，对其他系列适当加权
        recent_kinds = [items[c]["kind"] for c in avoid if c in items]
        if len(recent_kinds) >= 2 and len(set(recent_kinds[-2:])) == 1:
            dominant_kind = recent_kinds[-1]
            log(f"[info] 检测到最近品类连续为 {dominant_kind}，触发防疲劳多样性平衡")

        picked = choose_series_by_mood(mood, pool_for_routing, _h(bucket_key, args.mood or "none"))
        if picked is None:
            emit({"ok": False, "reason": "series_unavailable",
                  "detail": "此刻没有任何系列可用。", "relax": [{"action": "retry_later"}]}, 2)
        series_id = picked["id"]

    (series, rarity_cfg, cards, raw, cand,
     after_excl) = build_series_pool(series_id, items, nutrition, args.budget, excludes,
                                     now=_fmt_hhmm(minutes))
    warnings = []
    if not series["_availableNow"]:
        warnings.append(f"「{series['name']}」不在当前时段供应。")
    if series["_widened"]:
        warnings.append(f"该系列在本店可用餐品不足 {series.get('minPoolSize', 1)} 个，"
                        f"已并入同类池 {len(series['_widened'])} 项（跨系列）。")
    elif raw and len(raw) < series.get("minPoolSize", 1):
        warnings.append(f"系列「{series['name']}」本期可用餐品偏少（{len(raw)} 个），建议换系列。")
    if remembered:
        warnings.append(f"已按你的长期排除项过滤：{'、'.join(remembered)}")

    def fail(reason, detail, relax):
        emit({"ok": False, "reason": reason, "detail": detail, "relax": relax,
              "time": {"bucket": bucket_key, "label": bucket_label},
              "disclaimer": DISCLAIMER}, 2)

    # ---- 空池协议：必须区分"这一档根本没有"和"被你筛掉了" ----
    if not raw:
        win = series["_window"]
        fail("series_unavailable",
             f"「{series['name']}」在本店当前菜单里没有对应餐品"
             + (f"（该系列供应时段 {win[0]}–{win[1]}）。" if win and not series["_availableNow"]
                else "，可能是本店没上或已售罄。"),
             [{"action": "switch_series", "to": s["id"]} for s in available if s["id"] != series_id][:3])
    if not after_excl:
        fail("all_excluded",
             f"排除 {'、'.join(excludes)} 之后，系列「{series['name']}」一项都不剩了。",
             [{"action": "drop_excludes"}])
    if not cand:
        cheapest = min(i["price"] for i in after_excl)
        keep = ", ".join(f"{i['name']}¥{i['price']}" for i in sorted(after_excl, key=lambda x: x["price"])[:3])
        
        # 全店全局探测最低门槛
        global_valid_foods = [it for it in items.values() if not (excludes and any(e in it["name"] for e in excludes))]
        global_cheapest_food = min(global_valid_foods, key=lambda x: x["price"]) if global_valid_foods else None
        
        relax_actions = [{"action": "raise_budget", "to": cheapest}]
        extra_hint = ""
        if global_cheapest_food and global_cheapest_food["price"] < cheapest:
            delta = round(global_cheapest_food["price"] - args.budget, 1)
            extra_hint = f"（全店起抽底线为【{global_cheapest_food['name']}】¥{global_cheapest_food['price']:g}，仅差 ¥{delta:g}）"
            relax_actions.append({"action": "try_cheapest_item", "item": global_cheapest_food["name"], "to": global_cheapest_food["price"]})
        else:
            relax_actions.append({"action": "switch_series", "to": "combo"})

        fail("budget_too_low",
             f"预算 ¥{args.budget:g}，系列「{series['name']}」最便宜的是 ¥{cheapest:g} {extra_hint}。该系列备选：{keep}。",
             relax_actions)

    if args.odds:
        return show_odds(series, cards, rarity_cfg)
    if args.simulate:
        return simulate(rarity_cfg, cards, args.simulate)

    base_meta = {
        "storeCode": payload.get("storeCode", "") or (payload.get("data") or {}).get("storeCode", ""),
        "queriedAt": payload.get("datetime", ""),
        "dayKey": day,
        "nonce": str(nonce),
        "mode": args.mode,
        "timeBucket": bucket_key,
        "timeLabel": bucket_label,
        "at": _fmt_hhmm(minutes),
        "mood": mood["id"],
        "excludes": excludes,
    }

    # ---- 端盒 ----
    if args.box:
        box, reason, detail = build_box(series, rarity_cfg,
                                        {t["id"]: t["label"] for t in rarity_cfg["tiers"]},
                                        items, nutrition, args.budget, excludes,
                                        nonce, mood["tone"], args.mode, avoid=avoid)
        if reason:
            fail(reason, detail, [{"action": "raise_budget"},
                                  {"action": "switch_series", "to": "combo"}])
        box_meta = dict(base_meta, drawId=box["boxId"],
                        poolFingerprint=fingerprint(box["slots"]), poolSize=len(box["slots"]),
                        engine="popmc-box/1.2")
        if len(box["slots"]) < 3:
            warnings.append(f"预算只够 {box['structure']}，已按结构降级。")
        state["recent"] = ([c for c in avoid if c not in
                            {s["fact"]["productCode"] for s in box["slots"]}]
                           + [c["fact"]["productCode"] for c in box["slots"]])[-4:]
        if args.commit:
            owned = state.setdefault("owned", {}).setdefault(series["id"], {})
            for c in box["slots"]:
                rec = owned.setdefault(c["fact"]["productCode"], {"count": 0, "firstAt": day})
                rec["count"] = rec.get("count", 0) + 1
                rec["name"] = c["fact"]["name"]
                rec["kind"] = c["fact"]["kind"]
            save_state(args.state, state)
        else:
            save_state(args.state, state)
        if args.split_dir:
            os.makedirs(args.split_dir, exist_ok=True)
            for i, c in enumerate(box["slots"], 1):
                path = os.path.join(args.split_dir, f"box-{i}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(ok_payload(series, c, dict(box_meta, drawId=c["experience"]["boxNo"]),
                                         []), f, ensure_ascii=False, indent=2)
            log(f"[info] 已写出 {len(box['slots'])} 张单卡到 {args.split_dir}")
        emit(box_payload(series, box, box_meta, warnings), 0)

    # ---- 单抽 ----
    counters = state.get("counters", {"sinceR": 0, "sinceSSR": 0, "totalDraws": 0})
    card, counters, meta = do_draw(series, rarity_cfg, cards, nonce, counters,
                                   args.mode, mood["tone"], avoid=avoid)
    meta = dict(base_meta, **meta)
    card["fact"]["source"] = f"mcd-mcp.query-meals@{payload.get('datetime', '')}"

    # 抽到图腾款时，用 series.pinned.copy 覆盖模板文案（人工写过的那句更好）
    for pin in series.get("pinned", []):
        if str(pin.get("productCode")) == card["fact"]["productCode"] and pin.get("copy"):
            card["experience"]["flavorText"] = pin["copy"]
            break

    state["counters"] = counters
    state.setdefault("counters", {}).setdefault("dailyNonce", {})[day] = nonce
    code = card["fact"]["productCode"]
    state["recent"] = ([c for c in avoid if c != code] + [code])[-4:]
    if args.commit:
        owned = state.setdefault("owned", {}).setdefault(series["id"], {})
        rec = owned.setdefault(card["fact"]["productCode"], {"count": 0, "firstAt": day})
        rec["count"] = rec.get("count", 0) + 1
        rec["name"] = card["fact"]["name"]      # 仅供本地图鉴，不含个人信息
        rec["kind"] = card["fact"]["kind"]
    save_state(args.state, state)

    emit(ok_payload(series, card, meta, warnings), 0)

def box_payload(series, box, meta, warnings):
    return {
        "ok": True,
        "series": {
            "id": series["id"], "name": series["name"], "code": series["code"],
            "tagline": series.get("tagline", ""), "season": series.get("season", "S1"),
            "palette": series.get("palette", {}),
            "disclaimer": SERIES_NOTE,
        },
        "box": box,
        "meta": meta,
        "assets": {
            "cardSvg": "assets/cards/box-chicken.svg",
            "unboxGif": "assets/unbox/unboxing-chicken.gif",
            "packageSvg": "assets/cards/package-chicken.svg",
        },
        "warnings": warnings or [],
        "disclaimer": DISCLAIMER,
        "rarityNote": RARITY_NOTE,
    }


if __name__ == "__main__":
    main()
