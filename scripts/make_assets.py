#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦盒 McBox · 演示资产生成器

一条命令重建 docs/assets/cards/*.svg 与 docs/cards-preview.html。
目的：README 里的截图永远和引擎实际输出一致，避免"改了代码忘了改图"。

用法:
  cd skill/mcbox && python3 scripts/make_assets.py
  cd skill/mcbox && python3 scripts/make_assets.py --pool /tmp/mcbox_pool.json --store 1450713
"""

import argparse
import html
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL_DIR = os.path.join(HERE, "..")
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")
CARD_DIR = os.path.join(ASSETS_DIR, "cards")
UNBOX_DIR = os.path.join(ASSETS_DIR, "unbox")
DOCS_DIR = os.path.join(SKILL_DIR, "..", "..", "docs")
DOCS_CARD_DIR = os.path.join(DOCS_DIR, "assets", "cards")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


draw = load("draw", os.path.join(HERE, "draw.py"))
card_mod = load("render_card", os.path.join(HERE, "render_card.py"))

# 每个系列抓哪几档，以及展示顺序
WANTED = (
    ("beef-universe", ("SSR", "R", "N")),
    ("chicken", ("SR", "R", "N")),
    ("fries-snack", ("SSR", "R")),
    ("drinks-soda", ("SSR", "R")),
    ("dessert", ("R", "N")),
    ("coffee", ("R",)),
    ("combo", ("R",)),
    ("party", ("R",)),
)


def find_card(series, cfg, cards, tier, limit=600):
    """确定性找一个能抽到指定档位的 nonce（不依赖运气、不依赖当前时间）。"""
    counters = {"sinceR": 0, "sinceSSR": 0}
    for nonce in range(1, limit):
        card, counters, meta = draw.do_draw(series, cfg, cards, nonce, counters,
                                            "default", "neutral")
        if card["experience"]["rarity"] == tier:
            return card, meta
    return None, None


def build(pool_path, nutrition_path, store_code, now):
    items, payload = draw.load_menu(pool_path)
    if not items:
        sys.exit("菜单为空，无法生成资产")
    nutrition = {}
    if nutrition_path and os.path.exists(nutrition_path):
        nutrition = draw.parse_nutrition(open(nutrition_path, encoding="utf-8").read())

    os.makedirs(CARD_DIR, exist_ok=True)
    os.makedirs(UNBOX_DIR, exist_ok=True)
    os.makedirs(DOCS_CARD_DIR, exist_ok=True)
    for d in (CARD_DIR, DOCS_CARD_DIR):
        for old in os.listdir(d):
            if old.endswith(".svg"):
                try: os.remove(os.path.join(d, old))
                except OSError: pass

    figures, stats = [], []
    for series_id, tiers in WANTED:
        series, cfg, cards, *_ = draw.build_series_pool(series_id, items, nutrition, now=now)
        if not cards:
            print(f"  跳过 {series_id}：当前时段/本店无可用餐品")
            continue
        for tier in tiers:
            card, meta = find_card(series, cfg, cards, tier)
            if card is None:
                continue
            meta = dict(meta, storeCode=store_code, queriedAt=payload.get("datetime", ""),
                        timeBucket=draw.time_bucket(draw.now_minutes(now))[0])
            card["fact"]["source"] = f"mcd-mcp.query-meals@{payload.get('datetime', '')}"
            payload_card = draw.ok_payload(series, card, meta)
            name = f"{series_id}-{tier}.svg"
            svg_str = card_mod.render(payload_card)
            for d in (CARD_DIR, DOCS_CARD_DIR):
                with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                    f.write(svg_str)
            figures.append({
                "file": name,
                "rarity": card["experience"]["rarityLabel"],
                "title": card["fact"]["name"],
                "no": card["experience"]["cardNo"],
                "price": card["fact"]["price"],
                "series": series["name"],
            })
            stats.append((series_id, tier, card["fact"]["name"]))

    # 端盒卡（核心差异化，必须出现在预览里）
    series, cfg, cards, *_ = draw.build_series_pool("chicken", items, nutrition, now=now)
    labels = {t["id"]: t["label"] for t in cfg["tiers"]}
    box, reason, _detail = draw.build_box(series, cfg, labels, items, nutrition,
                                          45.0, [], 1, "up", "default")
    if box:
        meta = {"drawId": box["boxId"], "storeCode": store_code,
                "queriedAt": payload.get("datetime", ""), "engine": "mcbox-box/1.1"}
        box_svg_str = card_mod.render_box(draw.box_payload(series, box, meta, []))
        pkg_svg_str = card_mod.render_package(series)
        for d in (CARD_DIR, DOCS_CARD_DIR):
            with open(os.path.join(d, "box-chicken.svg"), "w", encoding="utf-8") as f:
                f.write(box_svg_str)
            with open(os.path.join(d, "package-chicken.svg"), "w", encoding="utf-8") as f:
                f.write(pkg_svg_str)
        figures.insert(0, {
            "file": "box-chicken.svg",
            "rarity": "端盒",
            "title": "整盒 " + box["structure"],
            "no": f'¥{box["totalPrice"]:g}',
            "price": box["totalPrice"],
            "series": series["name"],
            "wide": True,
        })
        figures.insert(1, {
            "file": "unboxing-ssr.gif",
            "rarity": "动效",
            "title": "开盒揭晓动画 (GIF 动效)",
            "no": "ANIMATED",
            "price": 25.5,
            "series": "牛堡宇宙",
            "wide": False,
        })
        figures.insert(2, {
            "file": "package-chicken.svg",
            "rarity": "外盒",
            "title": "立体盲盒包装（开盒前）",
            "no": "UNBOX",
            "price": 0,
            "series": series["name"],
            "wide": False,
        })
    else:
        print(f"  端盒生成失败：{reason}")

    write_preview(figures, payload.get("datetime", ""), store_code)
    print(f"  卡面 {len(figures)} 张 → {os.path.relpath(CARD_DIR, ROOT)}")
    print(f"  预览页   → {os.path.relpath(os.path.join(DOCS_DIR, 'cards-preview.html'), ROOT)}")
    return figures


PREVIEW = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦盒 McBox · 卡面预览</title>
<style>
  :root { --bg:#14100f; --card:#1f1917; --line:rgba(255,255,255,.1); --fg:#f5efe8;
          --dim:rgba(245,239,232,.55); --gold:#f2c14e; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font-family:"PingFang SC","Noto Sans SC",-apple-system,sans-serif; }
  .wrap { max-width:1180px; margin:0 auto; padding:48px 28px 72px; }
  header { border-bottom:1px solid var(--line); padding-bottom:26px; margin-bottom:34px; }
  .kicker { color:var(--gold); font-size:13px; letter-spacing:.22em; text-transform:uppercase; }
  h1 { margin:10px 0 8px; font-size:40px; letter-spacing:-.02em; }
  .sub { color:var(--dim); font-size:15px; line-height:1.7; max-width:780px; }
  .sub b { color:var(--fg); font-weight:600; }
  .meta { margin-top:14px; font-size:12px; color:var(--dim); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(215px,1fr)); gap:20px; }
  figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:16px;
           padding:13px; transition:transform .2s ease, border-color .2s ease; }
  figure:hover { transform:translateY(-3px); border-color:rgba(242,193,78,.45); }
  figure.wide { grid-column:span 2; }
  figure img { width:100%; display:block; border-radius:10px; }
  figcaption { margin-top:11px; font-size:12px; color:var(--dim);
               display:flex; justify-content:space-between; gap:8px; }
  figcaption b { color:var(--fg); font-weight:600; }
  .tag { display:inline-block; padding:1px 7px; border-radius:99px; font-size:11px;
         border:1px solid rgba(242,193,78,.4); color:var(--gold); margin-right:6px; }
  .notes { margin-top:44px; display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:18px; }
  .note { background:var(--card); border:1px solid var(--line); border-left:2px solid var(--gold);
          border-radius:12px; padding:18px 20px; }
  .note h3 { margin:0 0 8px; font-size:14px; }
  .note p { margin:0; font-size:13px; line-height:1.75; color:var(--dim); }
  code { background:rgba(255,255,255,.07); padding:1px 6px; border-radius:4px; font-size:12px; }
  footer { margin-top:40px; padding-top:20px; border-top:1px solid var(--line);
           font-size:12px; color:var(--dim); line-height:1.8; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div style="float:right; margin-top:4px;">
      <a href="unboxing-player.html" style="display:inline-block; padding:10px 22px; border-radius:99px; background:linear-gradient(135deg, #ffd166, #fb8500); color:#120914; text-decoration:none; font-weight:800; font-size:13px; box-shadow:0 6px 16px rgba(251,133,0,0.35);">体验 3D 沉浸式开盒互动 ➔</a>
    </div>
    <div class="kicker">McBox · Collectible Cards</div>
    <h1>麦盒 · 卡面预览</h1>
    <p class="sub">
      每一张都是真实门店、真实价格、真实营养。<b>食物照片来自麦当劳 MCP 返回的官方 CDN 图</b>，
      不做任何加工；卡框、系列色、稀有度光效、编号与水印是本项目程序化生成的原创视觉。
      同一张卡可由 <code>种子 + 池指纹</code> 完整复现。
    </p>
    <p class="meta">数据：门店 __STORE__ ｜ 菜单落库 __AT__ ｜ 由 <code>scripts/make_assets.py</code> 生成</p>
  </header>

  <div class="grid">
__FIGURES__
  </div>

  <div class="notes">
    <div class="note">
      <h3>食物图：官方，不画</h3>
      <p><code>query-meals</code> 每项都返回 <code>image</code>，指向 <code>menu-img.mcd.cn</code>。
      卡面直接 <code>&lt;image href&gt;</code> 嵌进去，不重绘、不生成、不裁切改造。</p>
    </div>
    <div class="note">
      <h3>卡框：原创，必须自研</h3>
      <p>官方只给白底商品抠图，没有"盲盒包装"这种物料。要做开盒，就必须自己造盒面——且不能伪造官方包装，
      所以用 SVG 渐变 + pattern 程序化生成，1 秒出图、可复现、可换色。</p>
    </div>
    <div class="note">
      <h3>属性：官方营养表</h3>
      <p>能量 / 蛋白 / 脂肪 / 碳水来自 <code>list-nutrition-foods</code>。菜单名与营养表名只在
      "唯一且后缀只是杯型/包装"时才映射（如 <code>可乐 → 可乐中杯</code>），且卡面写明依据。
      套餐官方表未收录，就显示"品类 + 比原价省"——<b>绝不按名称估热量</b>。</p>
    </div>
    <div class="note">
      <h3>稀有度：只是壳</h3>
      <p>常驻 / 人气 / 当期 / 图腾 只改边框与文案，不影响你拿到什么、付多少钱，
      也不代表官方发行量或限量。四档的真实概率由 <code>--odds</code> 按当前池子实算并公示（含保底）。</p>
    </div>
  </div>

  <footer>
    非官方产品 · 麦当劳程序员创意开发大赛参赛作品 · 商品信息以麦当劳官方渠道实时结果为准<br>
    收藏记录是抽取历史，不代表购买记录，也不代表该商品当前仍在售。
  </footer>
</div>
</body>
</html>
"""

FIG = """    <figure{wide}>
      <img src="assets/cards/{file}" alt="{alt}">
      <figcaption><span><span class="tag">{rarity}</span><b>{title}</b></span><span>{no}</span></figcaption>
    </figure>"""


def write_preview(figures, at, store):
    blocks = []
    for f in figures:
        blocks.append(FIG.format(
            wide=' class="wide"' if f.get("wide") else "",
            file=f["file"],
            alt=html.escape(f'{f["series"]} {f["rarity"]} {f["title"]}'),
            rarity=html.escape(f["rarity"]),
            title=html.escape(f["title"]),
            no=html.escape(f["no"]),
        ))
    page = (PREVIEW.replace("__FIGURES__", "\n".join(blocks))
            .replace("__STORE__", html.escape(str(store or "—")))
            .replace("__AT__", html.escape(str(at or "—"))))
    with open(os.path.join(DOCS_DIR, "cards-preview.html"), "w", encoding="utf-8") as fh:
        fh.write(page)


def main():
    ap = argparse.ArgumentParser(description="重建卡面资产与预览页")
    ap.add_argument("--pool", default=os.path.join(ROOT, "fixtures", "query_meals.sample.json"))
    ap.add_argument("--nutrition", default=os.path.join(ROOT, "fixtures", "nutrition.raw.txt"))
    ap.add_argument("--store", default="1450713")
    ap.add_argument("--now", default="18:39", help="按哪个时刻取系列（早餐系列需要 05:00-10:30）")
    args = ap.parse_args()
    build(args.pool, args.nutrition, args.store, args.now)


if __name__ == "__main__":
    main()
