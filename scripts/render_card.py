#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦泡泡 PopMc · 收藏卡与盲盒外盒高级渲染器 v2.0

把 `draw.py` 输出的卡片 JSON / 端盒 JSON / 系列定义 渲染成潮玩级别的 600×840 SVG。

设计边界（见 docs/DESIGN-DECISIONS.md D5）：
  1. 商品实拍图使用麦当劳 MCP 返回的官方 CDN 原图（并内联为 base64，确保 <img> 引用不裂图）；
  2. 展台、光效、卡框、粒子、编号与盲盒包装盒全部程序化自研生成；
  3. 严禁出现麦当劳 Logo、金拱门图形或伪造官方包装；
  4. 底部恒带免责声明与参赛作品防伪标识。

用法:
  python3 render_card.py --card /tmp/card.json --out /tmp/card.svg
  python3 render_card.py --card /tmp/box.json --slot box --out /tmp/box.svg
  python3 render_card.py --package chicken --out /tmp/package.svg
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request

CACHE = os.environ.get("MCBOX_IMG_CACHE", os.path.expanduser("~/.popmc/imgcache"))
MAGIC = ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
         (b"GIF8", "image/gif"), (b"RIFF", "image/webp"))

W, H = 600, 840

FRAMES = {
    "N":   {"stroke": "#ffffff", "opacity": 0.16, "width": 1.2, "glow": 0},
    "R":   {"stroke": "#e2e8f0", "opacity": 0.85, "width": 2.2, "glow": 0.40},
    "SR":  {"stroke": "#ffd166", "opacity": 0.98, "width": 3.0, "glow": 0.65},
    "SSR": {"stroke": "#8fd6ff", "opacity": 1.00, "width": 4.0, "glow": 0.95},
}
LABEL = {"N": "常驻", "R": "人气", "SR": "当期", "SSR": "图腾"}
KIND_LABEL = {"single": "单品", "combo": "套餐", "main": "主食", "side": "小食",
              "drink": "饮品", "dessert": "甜品"}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _sniff(data):
    for magic, mime in MAGIC:
        if data.startswith(magic):
            return mime
    return "image/png"


def inline_image(url, embed=True, timeout=6):
    """把官方商品图内联成 data URI。

    为什么必须内联：浏览器不允许 <img src="x.svg"> 里的 SVG 再引用外部网络资源。
    不内联的话在 GitHub README、HTML 预览里食物图全是裂图。
    """
    if not url:
        return ""
    if not embed or url.startswith("data:"):
        return url
    key = hashlib.sha1(url.encode()).hexdigest()
    for ext in ("png", "jpg", "gif", "webp"):
        path = os.path.join(CACHE, f"{key}.{ext}")
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                return f"data:{_sniff(data)};base64,{base64.b64encode(data).decode()}"
            except OSError:
                pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mcbox/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        mime = _sniff(data)
        try:
            os.makedirs(CACHE, exist_ok=True)
            with open(os.path.join(CACHE, f"{key}.{mime.split('/')[-1]}".replace("jpeg", "jpg")),
                      "wb") as f:
                f.write(data)
        except OSError:
            pass
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception as e:
        print(f"[warn] 商品图内联失败，回落到原图链接：{e}", file=sys.stderr)
        return url


def shade(hex_color, factor):
    """factor<1 变暗，>1 变亮。"""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(v * factor))) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def wrap(text):
    """短句不换行；长了按句号断（最多 2 行），再长按 13 字硬切。禁止在词中间断开。"""
    text = str(text or "").strip()
    if not text:
        return [""]
    if len(text) <= 17:
        return [text]
    parts = [p for p in text.split("。") if p]
    if len(parts) >= 2:
        return [parts[0] + "。", "。".join(parts[1:]) + "。"]
    line = parts[0] if parts else text
    return [line[i:i + 13] for i in range(0, len(line), 13)][:2]


def render(card, embed=True):
    """高保真潮玩盲盒卡面：

    - 亚克力微透光卡套 + 外边框聚光灯
    - 3D 悬浮食物展台（弧光顶照 + 柔和展台阴影 + 亚克力底托）
    - 全息分级边框系统（SSR 镭射彩虹流动 + 炫光粒子 + 金星图腾勋章）
    - 毛玻璃微透属性胶囊面板（Frosted Glass Stats Pill）
    - 防伪条形码与收藏认证铭牌
    """
    fact = card.get("fact", {})
    exp = card.get("experience", {})
    series = card.get("series", {})
    meta = card.get("meta", {})

    base = series.get("palette", {}).get("base", "#8B1E2D") if series.get("palette") else "#8B1E2D"
    base = card.get("_palette", base)
    accent = series.get("palette", {}).get("accent", "#F2C14E")
    glow_col = series.get("palette", {}).get("glow", "#FF6B4A")

    rarity = exp.get("rarity", "N")
    fr = FRAMES.get(rarity, FRAMES["N"])
    name = fact.get("name", "")
    name_size = 34 if len(name) <= 9 else (28 if len(name) <= 13 else 22)
    price = fact.get("price")
    nut = fact.get("nutrition") or {}
    lines = wrap(exp.get("flavorText", ""))

    # --- 属性胶囊渲染 ---
    stat_cells = []
    if nut:
        stat_cells = [
            ("能量", f"{nut.get('energyKcal', 0)}", "kcal"),
            ("蛋白", f"{nut.get('proteinG', 0)}", "g"),
            ("脂肪", f"{nut.get('fatG', 0)}", "g"),
            ("碳水", f"{nut.get('carbG', 0)}", "g"),
        ]
    else:
        stat_cells = [("品类", KIND_LABEL.get(fact.get("kind", ""), "—"), "")]
        if fact.get("saving") and fact["saving"] > 0:
            stat_cells.append(("比原价省", f"¥{fact['saving']:g}", ""))
        else:
            stat_cells.append(("营养数据", "官方表未收录", ""))

    capsules_svg = []
    for i, item in enumerate(stat_cells):
        k, v = item[0], item[1]
        unit = item[2] if len(item) > 2 else ""
        x = 54 + (i % 2) * 248
        y = 672 + (i // 2) * 44
        unit_str = f' <tspan font-size="12" font-weight="500" opacity="0.65">{esc(unit)}</tspan>' if unit else ""
        capsules_svg.append(f'''
    <rect x="{x}" y="{y}" width="238" height="36" rx="10" fill="#000000" opacity="0.22"/>
    <rect x="{x}" y="{y}" width="238" height="36" rx="10" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.12"/>
    <text x="{x + 14}" y="{y + 23}" font-size="13" fill="#ffffff" opacity="0.75" font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(k)}</text>
    <text x="{x + 224}" y="{y + 24}" font-size="15" font-weight="700" fill="#ffffff" text-anchor="end" font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(v)}{unit_str}</text>''')

    # 官方依据标签
    match = fact.get("nutritionMatch") or {}
    basis_note = ""
    if nut and match.get("basis") == "suffix" and match.get("officialName"):
        basis_note = (f'<text x="56" y="770" font-size="11" fill="{accent}" opacity="0.85" '
                      f'font-family="PingFang SC, Noto Sans SC, sans-serif">'
                      f'✦ 营养官方对齐：「{esc(match["officialName"])}」条目</text>')
    elif nut and fact.get("nutritionNote"):
        basis_note = (f'<text x="56" y="770" font-size="11" fill="{accent}" opacity="0.85" '
                      f'font-family="PingFang SC, Noto Sans SC, sans-serif">'
                      f'✦ {esc(fact["nutritionNote"])}（官方营养表原话）</text>')
    elif not nut:
        basis_note = (f'<text x="56" y="770" font-size="11" fill="#ffffff" opacity="0.45" '
                      f'font-family="PingFang SC, Noto Sans SC, sans-serif">'
                      f'✦ 官方未收录独立营养数值，不作无据估算</text>')

    # --- 稀有度全息与光效元素 ---
    rarity_badge = ""
    rarity_fx = ""
    badge_label = exp.get("rarityLabel") or LABEL.get(rarity, "")

    if rarity == "SSR":
        rarity_fx = f'''
    <!-- SSR 全息虹彩流光层 -->
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="url(#prism)" stroke-width="3.5"/>
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="url(#prism)" stroke-width="14" opacity="0.32" filter="url(#glow_heavy)"/>
    <circle cx="100" cy="120" r="1.5" fill="#ffffff" opacity="0.8"/>
    <circle cx="490" cy="130" r="2.5" fill="#ffffff" opacity="0.9"/>
    <circle cx="120" cy="510" r="2.0" fill="#ffffff" opacity="0.7"/>
    <circle cx="480" cy="500" r="1.8" fill="#ffffff" opacity="0.85"/>
    <!-- 星芒角花 -->
    <path d="M 28 36 L 36 36 L 36 28 L 40 28 L 40 36 L 48 36 L 48 40 L 40 40 L 40 48 L 36 48 L 36 40 L 28 40 Z" fill="url(#prism)" opacity="0.85"/>
    <path d="M 552 36 L 560 36 L 560 28 L 564 28 L 564 36 L 572 36 L 572 40 L 564 40 L 564 48 L 560 48 L 560 40 L 552 40 Z" fill="url(#prism)" opacity="0.85"/>
    <!-- 展台全息背光 -->
    <ellipse cx="300" cy="300" rx="210" ry="200" fill="url(#holo_halo)" opacity="0.75" filter="url(#soft)"/>
    '''
        rarity_badge = f'''
    <rect x="446" y="42" width="112" height="34" rx="17" fill="url(#prism)" opacity="0.9"/>
    <rect x="448" y="44" width="108" height="30" rx="15" fill="#140f1a"/>
    <text x="502" y="64" font-size="13" font-weight="800" fill="url(#prism)" text-anchor="middle" letter-spacing="1"
          font-family="PingFang SC, Noto Sans SC, sans-serif">★ {esc(badge_label)} ★</text>
    '''
    elif rarity == "SR":
        rarity_fx = f'''
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="url(#gold)" stroke-width="2.8"/>
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="url(#gold)" stroke-width="10" opacity="0.25" filter="url(#soft)"/>
    <circle cx="485" cy="135" r="2.0" fill="#ffd166" opacity="0.85"/>
    <circle cx="115" cy="505" r="1.5" fill="#ffd166" opacity="0.7"/>
    <ellipse cx="300" cy="300" rx="190" ry="180" fill="#ffb703" opacity="0.16" filter="url(#soft)"/>
    '''
        rarity_badge = f'''
    <rect x="456" y="42" width="102" height="34" rx="17" fill="url(#gold)" opacity="0.85"/>
    <rect x="458" y="44" width="98" height="30" rx="15" fill="#1b1509"/>
    <text x="507" y="64" font-size="13" font-weight="800" fill="#ffe9a8" text-anchor="middle" letter-spacing="1"
          font-family="PingFang SC, Noto Sans SC, sans-serif">★ {esc(badge_label)}</text>
    '''
    elif rarity == "R":
        rarity_fx = f'''
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="url(#silver)" stroke-width="2.2" opacity="0.85"/>
    <ellipse cx="300" cy="300" rx="180" ry="170" fill="#ffffff" opacity="0.08" filter="url(#soft)"/>
    '''
        rarity_badge = f'''
    <rect x="466" y="42" width="92" height="34" rx="17" fill="url(#silver)" opacity="0.7"/>
    <rect x="468" y="44" width="88" height="30" rx="15" fill="#13171c"/>
    <text x="512" y="64" font-size="13" font-weight="700" fill="#eef3f7" text-anchor="middle" letter-spacing="0.5"
          font-family="PingFang SC, Noto Sans SC, sans-serif">◆ {esc(badge_label)}</text>
    '''
    else:  # N
        rarity_fx = f'''
    <rect x="16" y="16" width="568" height="808" rx="28" fill="none" stroke="#ffffff" stroke-width="1.2" opacity="0.2"/>
    '''
        rarity_badge = f'''
    <rect x="476" y="42" width="82" height="32" rx="16" fill="#000000" opacity="0.45"/>
    <rect x="476" y="42" width="82" height="32" rx="16" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.2"/>
    <text x="517" y="63" font-size="13" font-weight="600" fill="#ffffff" opacity="0.85" text-anchor="middle"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(badge_label)}</text>
    '''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <!-- 背景渐变：从左上聚光灯辐射延伸 -->
    <radialGradient id="spotlight" cx="20%" cy="15%" r="85%">
      <stop offset="0%" stop-color="{shade(base, 1.45)}"/>
      <stop offset="40%" stop-color="{base}"/>
      <stop offset="85%" stop-color="{shade(base, 0.35)}"/>
      <stop offset="100%" stop-color="#0a0709"/>
    </radialGradient>

    <!-- 金属与全息流光渐变 -->
    <linearGradient id="silver" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#8f9aa6"/><stop offset="30%" stop-color="#ffffff"/>
      <stop offset="50%" stop-color="#9aa5b1"/><stop offset="100%" stop-color="#d6e0ea"/>
    </linearGradient>
    <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#cf941a"/><stop offset="35%" stop-color="#fff2be"/>
      <stop offset="65%" stop-color="#e5aa28"/><stop offset="100%" stop-color="#8a5a04"/>
    </linearGradient>
    <linearGradient id="prism" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ff9ce6"/><stop offset="25%" stop-color="#70d6ff"/>
      <stop offset="50%" stop-color="#9bf6ff"/><stop offset="75%" stop-color="#caffbf"/>
      <stop offset="100%" stop-color="#ffd166"/>
    </linearGradient>
    <radialGradient id="holo_halo" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffb703" stop-opacity="0.35"/>
      <stop offset="50%" stop-color="#00f5d4" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="#7b2cbf" stop-opacity="0"/>
    </radialGradient>

    <!-- 食物展台：多层立体底座渐变 -->
    <linearGradient id="stage_glass" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.98"/>
      <stop offset="65%" stop-color="#f8fafc" stop-opacity="0.96"/>
      <stop offset="100%" stop-color="#e2e8f0" stop-opacity="0.94"/>
    </linearGradient>
    <radialGradient id="food_shadow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#1e1810" stop-opacity="0.22"/>
      <stop offset="50%" stop-color="#2a2016" stop-opacity="0.12"/>
      <stop offset="85%" stop-color="#3d2c1d" stop-opacity="0.04"/>
      <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
    </radialGradient>

    <!-- 细腻潮玩微网格纹理 -->
    <pattern id="dotgrid" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="10" cy="10" r="1.1" fill="#ffffff" opacity="0.08"/>
    </pattern>
    <pattern id="stripes" width="28" height="28" patternTransform="rotate(28)" patternUnits="userSpaceOnUse">
      <rect width="28" height="28" fill="none"/>
      <rect width="8" height="28" fill="#ffffff" opacity="0.025"/>
    </pattern>

    <filter id="soft"><feGaussianBlur stdDeviation="6"/></filter>
    <filter id="glow_heavy"><feGaussianBlur stdDeviation="12"/></filter>
    <filter id="drop_shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000000" flood-opacity="0.38"/>
    </filter>

    <clipPath id="stage_clip"><rect x="70" y="102" width="460" height="428" rx="26"/></clipPath>
    <clipPath id="img_clip"><rect x="74" y="106" width="452" height="420" rx="22"/></clipPath>
  </defs>

  <!-- 1. 主体卡面与背景 -->
  <rect width="{W}" height="{H}" rx="32" fill="url(#spotlight)"/>
  <rect width="{W}" height="{H}" rx="32" fill="url(#dotgrid)"/>
  <rect width="{W}" height="{H}" rx="32" fill="url(#stripes)"/>

  <!-- 卡砖边缘倒角折射高光线 -->
  <rect x="8" y="8" width="584" height="824" rx="26" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.12"/>
  <line x1="40" y1="9" x2="280" y2="9" stroke="#ffffff" stroke-width="2" opacity="0.45" stroke-linecap="round"/>

  <!-- 2. 稀有度外框光效 -->
  {rarity_fx}

  <!-- 3. 顶部信息头 -->
  <g transform="translate(44, 46)">
    <!-- 潮玩微标 -->
    <rect x="0" y="0" width="48" height="20" rx="6" fill="#000000" opacity="0.3"/>
    <text x="24" y="14" font-size="10" font-weight="800" fill="{accent}" text-anchor="middle"
          letter-spacing="1" font-family="PingFang SC, Noto Sans SC, sans-serif">S1</text>
    <text x="56" y="16" font-size="20" font-weight="800" fill="#ffffff" opacity="0.98"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(series.get('name', ''))}</text>
    <text x="0" y="38" font-size="12" fill="#ffffff" opacity="0.65"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(series.get('tagline', ''))}</text>
  </g>
  {rarity_badge}

  <!-- 4. 食物 3D 展示橱窗 (Showcase Pod) -->
  <g filter="url(#drop_shadow)">
    <!-- 展台外包围微框 -->
    <rect x="68" y="100" width="464" height="432" rx="28" fill="none" stroke="#ffffff" stroke-width="2" opacity="0.25"/>
    <!-- 展台内衬毛玻璃白底 -->
    <rect x="70" y="102" width="460" height="428" rx="26" fill="url(#stage_glass)"/>
    <!-- 顶部天光高光反射 -->
    <path d="M 70 140 Q 300 170 530 140 L 530 102 L 70 102 Z" fill="#ffffff" opacity="0.35"/>
    <!-- 食物物理落地暗部阴影 -->
    <ellipse cx="300" cy="454" rx="168" ry="24" fill="url(#food_shadow)"/>
    <!-- 展台底部微光台基线 -->
    <ellipse cx="300" cy="510" rx="190" ry="8" fill="#cbd5e1" opacity="0.6"/>
    <!-- 官方实物图片 -->
    <image href="{esc(inline_image(fact.get('image', ''), embed))}" x="74" y="106" width="452" height="392"
           preserveAspectRatio="xMidYMid meet" clip-path="url(#img_clip)"/>
  </g>

  <!-- 5. 商品主信息区 -->
  <text x="54" y="582" font-size="{name_size}" font-weight="800" fill="#ffffff"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(name)}</text>
  
  <!-- 风味与情绪文案 -->
  <text x="54" y="618" font-size="17" font-weight="500" fill="#ffffff" opacity="0.92"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(lines[0])}</text>
  {'<text x="54" y="644" font-size="17" font-weight="500" fill="#ffffff" opacity="0.92" font-family="PingFang SC, Noto Sans SC, sans-serif">' + esc(lines[1]) + '</text>' if len(lines) > 1 else ''}

  <!-- 分割线 -->
  <line x1="54" y1="658" x2="546" y2="658" stroke="#ffffff" stroke-width="1" opacity="0.15"/>

  <!-- 6. 属性药丸胶囊 (Stat Capsules) -->
  {''.join(capsules_svg)}
  {basis_note}

  <!-- 7. 底部认证与价格信息条 -->
  <g transform="translate(54, 786)">
    <!-- 卡号与防伪极简条形码装饰 -->
    <g transform="translate(0, 0)">
      <text x="0" y="0" font-size="16" font-weight="700" fill="#ffffff" opacity="0.8"
            font-family="PingFang SC, Noto Sans SC, monospace">{esc(exp.get('cardNo', ''))}</text>
      <!-- 极简微缩条形码装饰线 -->
      <g opacity="0.38" transform="translate(0, 8)">
        <rect x="0" y="0" width="3" height="10" fill="#ffffff"/>
        <rect x="5" y="0" width="1" height="10" fill="#ffffff"/>
        <rect x="8" y="0" width="4" height="10" fill="#ffffff"/>
        <rect x="14" y="0" width="2" height="10" fill="#ffffff"/>
        <rect x="18" y="0" width="1" height="10" fill="#ffffff"/>
        <rect x="21" y="0" width="5" height="10" fill="#ffffff"/>
        <rect x="28" y="0" width="2" height="10" fill="#ffffff"/>
        <rect x="32" y="0" width="4" height="10" fill="#ffffff"/>
        <rect x="38" y="0" width="1" height="10" fill="#ffffff"/>
        <rect x="41" y="0" width="3" height="10" fill="#ffffff"/>
        <rect x="46" y="0" width="1" height="10" fill="#ffffff"/>
        <rect x="49" y="0" width="4" height="10" fill="#ffffff"/>
      </g>
    </g>

    <!-- 真实价格徽牌 -->
    <g transform="translate(492, 0)">
      <rect x="-106" y="-22" width="106" height="36" rx="10" fill="#ffffff" opacity="0.12"/>
      <rect x="-106" y="-22" width="106" height="36" rx="10" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.25"/>
      <text x="-53" y="4" font-size="22" font-weight="800" fill="#ffffff" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">{('¥%g' % price) if price is not None else ''}</text>
    </g>
  </g>

  <!-- 8. 底部免责声明 -->
  <text x="300" y="825" font-size="11" fill="#ffffff" opacity="0.4" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">非官方产品 · 参赛作品 · 数据取自麦当劳官方MCP · {esc(meta.get('drawId', ''))}</text>
</svg>
'''


def render_box(payload, embed=True):
    """端盒（Box Set）高级展柜大卡：

    将一餐的主食、副食、饮品如潮玩套组（Multi-Figure Set）般展示。
    """
    series = payload.get("series", {})
    box = payload.get("box", {})
    meta = payload.get("meta", {})
    base = series.get("palette", {}).get("base", "#1E8E7E")
    accent = series.get("palette", {}).get("accent", "#F2E8CF")
    slots = box.get("slots", [])
    main = next((s for s in slots if s["experience"].get("slot") == "main"), slots[0] if slots else {})
    rest = [s for s in slots if s is not main]

    rows = []
    for i, s in enumerate(rest):
        f, e = s["fact"], s["experience"]
        y = 484 + i * 106
        rows.append(f'''
    <!-- 副食槽位 {i + 1} -->
    <g transform="translate(40, {y})">
      <rect x="0" y="0" width="520" height="96" rx="18" fill="#000000" opacity="0.25"/>
      <rect x="0" y="0" width="520" height="96" rx="18" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.15"/>
      <!-- 小展台图片底托 -->
      <rect x="10" y="8" width="80" height="80" rx="14" fill="#ffffff" opacity="0.96"/>
      <ellipse cx="50" cy="80" rx="30" ry="5" fill="#000000" opacity="0.22"/>
      <image href="{esc(inline_image(f.get("image", ""), embed))}" x="12" y="10" width="76" height="76"
             preserveAspectRatio="xMidYMid meet" clip-path="url(#sub_img_clip)"/>
      <!-- 文字 -->
      <rect x="104" y="16" width="60" height="18" rx="6" fill="#ffffff" opacity="0.15"/>
      <text x="134" y="29" font-size="11" font-weight="700" fill="#ffffff" opacity="0.85" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(e.get("slotLabel", ""))}</text>
      <text x="172" y="30" font-size="11" fill="{accent}" opacity="0.9" font-family="PingFang SC, Noto Sans SC, sans-serif">◆ {esc(e.get("rarityLabel", ""))}</text>
      <text x="104" y="58" font-size="{20 if len(f.get('name', '')) <= 12 else 17}" font-weight="700" fill="#ffffff"
            font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(f.get("name", ""))}</text>
      <text x="502" y="56" font-size="22" font-weight="800" fill="#ffffff" text-anchor="end"
            font-family="PingFang SC, Noto Sans SC, sans-serif">¥{f.get("price", 0):g}</text>
    </g>''')

    clips = "".join(f'''<clipPath id="sub_clip{i}"><rect x="12" y="{494 + i * 106}" width="76" height="76" rx="12"/></clipPath>'''
                    for i in range(len(rest)))

    kcal = box.get("totalKcal")
    kcal_text = f"{kcal} kcal（{box.get('kcalCovered')} 项官方数据）" if kcal else "官方表未覆盖"
    main_name = main.get("fact", {}).get("name", "")
    saving = box.get("totalSaving") or 0
    saving_text = (f"比原价省 ¥{saving:g}" if saving > 0 else f"共 {len(slots)} 件 · 单品现价累加")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <radialGradient id="box_spotlight" cx="30%" cy="20%" r="80%">
      <stop offset="0%" stop-color="{shade(base, 1.4)}"/>
      <stop offset="45%" stop-color="{base}"/>
      <stop offset="90%" stop-color="{shade(base, 0.35)}"/>
      <stop offset="100%" stop-color="#0a080d"/>
    </radialGradient>
    <pattern id="box_grid" width="24" height="24" patternUnits="userSpaceOnUse">
      <rect width="24" height="24" fill="none"/>
      <circle cx="12" cy="12" r="1.2" fill="#ffffff" opacity="0.08"/>
    </pattern>
    <filter id="box_shadow"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#000000" flood-opacity="0.35"/></filter>
    <clipPath id="main_box_clip"><rect x="42" y="112" width="516" height="258" rx="22"/></clipPath>
    <clipPath id="sub_img_clip"><rect x="12" y="10" width="76" height="76" rx="12"/></clipPath>
  </defs>

  <!-- 1. 背景 -->
  <rect width="{W}" height="{H}" rx="32" fill="url(#box_spotlight)"/>
  <rect width="{W}" height="{H}" rx="32" fill="url(#box_grid)"/>
  <rect x="12" y="12" width="576" height="816" rx="26" fill="none" stroke="#ffffff" stroke-width="1.5" opacity="0.2"/>

  <!-- 2. 头部 -->
  <g transform="translate(40, 46)">
    <rect x="0" y="0" width="68" height="22" rx="7" fill="#ffffff" opacity="0.18"/>
    <text x="34" y="15" font-size="11" font-weight="800" fill="#ffffff" text-anchor="middle"
          letter-spacing="1" font-family="PingFang SC, Noto Sans SC, sans-serif">BOX SET</text>
    <text x="78" y="17" font-size="22" font-weight="800" fill="#ffffff"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(series.get('name', ''))} · 端盒</text>
    <text x="0" y="42" font-size="13" fill="#ffffff" opacity="0.7"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(box.get('structure', ''))}｜{esc(series.get('tagline', ''))}</text>
  </g>

  <!-- 右上角专属编码勋章 -->
  <rect x="424" y="44" width="136" height="32" rx="16" fill="#000000" opacity="0.35"/>
  <rect x="424" y="44" width="136" height="32" rx="16" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.2"/>
  <text x="492" y="65" font-size="12" font-weight="800" fill="#ffffff" text-anchor="middle" letter-spacing="1"
        font-family="PingFang SC, Noto Sans SC, monospace">{esc(box.get('boxId', 'BOX'))}</text>

  <!-- 3. 主食核心展台 -->
  <g filter="url(#box_shadow)">
    <rect x="40" y="110" width="520" height="262" rx="24" fill="#ffffff" opacity="0.96"/>
    <path d="M 40 140 Q 300 165 560 140 L 560 110 L 40 110 Z" fill="#ffffff" opacity="0.4"/>
    <ellipse cx="300" cy="340" rx="170" ry="18" fill="#000000" opacity="0.25"/>
    <image href="{esc(inline_image(main.get('fact', {}).get('image', ''), embed))}" x="42" y="112" width="516" height="248"
           preserveAspectRatio="xMidYMid meet" clip-path="url(#main_box_clip)"/>
  </g>

  <!-- 主食铭牌 -->
  <rect x="40" y="386" width="520" height="84" rx="16" fill="#000000" opacity="0.25"/>
  <rect x="40" y="386" width="520" height="84" rx="16" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.15"/>
  <rect x="54" y="398" width="52" height="18" rx="6" fill="#ffffff" opacity="0.15"/>
  <text x="80" y="411" font-size="11" font-weight="700" fill="#ffffff" opacity="0.9" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">主食</text>
  <text x="114" y="412" font-size="11" fill="{accent}" opacity="0.9" font-family="PingFang SC, Noto Sans SC, sans-serif">✦ {esc(main.get('experience', {}).get('rarityLabel', ''))}</text>
  <text x="54" y="446" font-size="22" font-weight="800" fill="#ffffff"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(main_name[:16])}</text>
  <text x="542" y="444" font-size="24" font-weight="800" fill="#ffffff" text-anchor="end"
        font-family="PingFang SC, Noto Sans SC, sans-serif">¥{main.get('fact', {}).get('price', 0):g}</text>

  <!-- 4. 副食与饮品槽位 -->
  {''.join(rows)}

  <!-- 5. 底部整盒核算总台 -->
  <line x1="40" y1="708" x2="560" y2="708" stroke="#ffffff" stroke-width="1" opacity="0.18"/>
  <text x="40" y="736" font-size="12" fill="#ffffff" opacity="0.65" font-family="PingFang SC, Noto Sans SC, sans-serif">整盒总计 (SET TOTAL)</text>
  <text x="40" y="788" font-size="44" font-weight="900" fill="#ffffff" font-family="PingFang SC, Noto Sans SC, sans-serif">¥{box.get('totalPrice', 0):g}</text>

  <g transform="translate(560, 742)">
    <text x="0" y="0" font-size="12" font-weight="600" fill="#ffffff" opacity="0.75" text-anchor="end"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(kcal_text)}</text>
    <text x="0" y="24" font-size="13" font-weight="700" fill="{accent}" text-anchor="end"
          font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(saving_text)}</text>
  </g>

  <text x="300" y="825" font-size="11" fill="#ffffff" opacity="0.4" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">非官方产品 · 参赛作品 · 组合价为单品现价累加，以下单页为准</text>
</svg>
'''


def render_package(series, mood=None):
    """渲染经典的麦当劳风格立体盲盒包装盒（MCD Unopened Mystery Box）：

    融入经典麦当劳标志性元素：
      - 开心乐园餐经典双拱提手 (Gable Top Handle)
      - 标志性热烈红与薯条金黄撞色 (Red & Golden Yellow)
      - 散落金黄汉堡白芝麻底纹 (Sesame Seed Texture)
      - 问号橱窗衬托金黄汉堡/薯条轮廓剪影 (Silhouette)
      - 经典外卖红黄锯齿安全封条 (Zigzag Takeout Seal)
    """
    sid = series.get("id", "box")
    sname = series.get("name", "麦泡泡")
    tagline = series.get("tagline", "今日美味，由此开箱")
    base = "#DA291C"   # 经典麦当劳标志红
    accent = "#FFBC0D" # 经典薯条金黄

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <!-- 背景聚光灯：深邃暗红到黑 -->
    <radialGradient id="pkg_bg" cx="50%" cy="25%" r="80%">
      <stop offset="0%" stop-color="#3b0f15"/>
      <stop offset="55%" stop-color="#140609"/>
      <stop offset="100%" stop-color="#050203"/>
    </radialGradient>

    <!-- 盒体立体光感：中央明艳，两侧深邃 -->
    <radialGradient id="box_surface" cx="50%" cy="25%" r="75%">
      <stop offset="0%" stop-color="#fa382c"/>
      <stop offset="60%" stop-color="#da291c"/>
      <stop offset="100%" stop-color="#8a1107"/>
    </radialGradient>

    <linearGradient id="box_gold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="35%" stop-color="#ffbc0d"/>
      <stop offset="70%" stop-color="#f39c12"/><stop offset="100%" stop-color="#b86a04"/>
    </linearGradient>

    <linearGradient id="tape_zigzag" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ffbc0d"/><stop offset="50%" stop-color="#ffd166"/><stop offset="100%" stop-color="#f39c12"/>
    </linearGradient>

    <!-- 芝麻点阵纹理 -->
    <pattern id="sesame_dots" width="30" height="30" patternUnits="userSpaceOnUse">
      <ellipse cx="6" cy="6" rx="2" ry="3" fill="#fff4d0" opacity="0.22" transform="rotate(25 6 6)"/>
      <ellipse cx="21" cy="21" rx="2" ry="3" fill="#fff4d0" opacity="0.22" transform="rotate(-30 21 21)"/>
    </pattern>

    <filter id="box_3d"><feDropShadow dx="0" dy="28" stdDeviation="30" flood-color="#000000" flood-opacity="0.68"/></filter>
  </defs>

  <!-- 1. 背景 -->
  <rect width="{W}" height="{H}" rx="32" fill="url(#pkg_bg)"/>

  <!-- 2. 顶部系列潮流标 -->
  <text x="300" y="58" font-size="12" font-weight="800" fill="{accent}" letter-spacing="4" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">MCDONALD\'S REAL IN-STORE FOOD</text>
  <text x="300" y="92" font-size="28" font-weight="900" fill="#ffffff" letter-spacing="2" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(sname)} · 盲盒</text>
  <text x="300" y="118" font-size="13" fill="#ffffff" opacity="0.75" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(tagline)}</text>

  <!-- 3. 立体麦当劳开心乐园盒身 (Happy Meal Style Gable Box) -->
  <g filter="url(#box_3d)" transform="translate(125, 145)">
    <!-- 盒体物理投影 -->
    <ellipse cx="175" cy="530" rx="170" ry="24" fill="#000000" opacity="0.7"/>

    <!-- 开心乐园餐经典双拱提手 (Gable Handle) -->
    <path d="M 65 38 L 285 38 Q 285 -10 175 -10 Q 65 -10 65 38 Z" fill="#eb2c1e" stroke="rgba(255,255,255,0.4)" stroke-width="2"/>
    <!-- 拱中镂空把手 -->
    <path d="M 120 24 Q 120 4 175 4 Q 230 4 230 24 Q 230 30 175 30 Q 120 30 120 24 Z" fill="#0a0305" opacity="0.55"/>

    <!-- 盒体主方块 -->
    <rect x="20" y="36" width="310" height="470" rx="24" fill="url(#box_surface)"/>
    <rect x="20" y="36" width="310" height="470" rx="24" fill="url(#sesame_dots)"/>
    <rect x="20" y="36" width="310" height="470" rx="24" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="2"/>

    <!-- 两侧经典向外扩散的高光线条 -->
    <line x1="22" y1="38" x2="36" y2="504" stroke="#ffffff" stroke-width="4" opacity="0.18"/>
    <line x1="328" y1="38" x2="314" y2="504" stroke="#ffffff" stroke-width="4" opacity="0.18"/>

    <!-- 顶部麦泡泡徽标 -->
    <text x="175" y="68" font-size="12" font-weight="900" fill="#ffffff" letter-spacing="3" text-anchor="middle"
          font-family="PingFang SC, Noto Sans SC, sans-serif">★ PopMc · S1 ★</text>

    <!-- 问号橱窗：内含汉堡轮廓剪影 -->
    <g transform="translate(45, 82)">
      <rect x="0" y="0" width="260" height="280" rx="20" fill="#0b0406" opacity="0.85"/>
      <rect x="0" y="0" width="260" height="280" rx="20" fill="none" stroke="{accent}" stroke-width="2.5" opacity="0.9"/>
      
      <!-- 汉堡神秘剪影 -->
      <path d="M 130 65 Q 60 65 60 105 L 200 105 Q 200 65 130 65 Z" fill="{accent}" opacity="0.12"/>
      <path d="M 58 115 L 202 115 Q 210 125 202 135 L 58 135 Q 50 125 58 115 Z" fill="{accent}" opacity="0.12"/>
      <path d="M 65 150 L 195 150 Q 195 180 130 180 Q 65 180 65 150 Z" fill="{accent}" opacity="0.12"/>

      <!-- 潮玩大问号 -->
      <text x="130" y="195" font-size="132" font-weight="900" fill="url(#box_gold)" text-anchor="middle"
            font-family="Impact, PingFang SC, sans-serif">?</text>
      <text x="130" y="238" font-size="11" font-weight="800" fill="{accent}" text-anchor="middle" letter-spacing="3"
            font-family="PingFang SC, Noto Sans SC, sans-serif">WHO IS INSIDE</text>
    </g>

    <!-- 经典外卖红黄锯齿安全封条 (Zigzag Takeout Seal) -->
    <g transform="translate(20, 382)">
      <rect x="0" y="0" width="310" height="38" fill="url(#tape_zigzag)"/>
      <text x="155" y="24" font-size="12" font-weight="900" fill="#140808" letter-spacing="3" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">✦ 麦麦开盒 · 现制美味 ✦</text>
    </g>

    <!-- 底部认证与池子说明 -->
    <g transform="translate(45, 436)">
      <text x="130" y="24" font-size="13" font-weight="800" fill="#ffffff" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(sname)} · 现制在售池</text>
      <text x="130" y="44" font-size="10" fill="{accent}" opacity="0.9" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">AUTHENTIC MCDONALD\'S REAL FOOD</text>
    </g>
  </g>

  <!-- 底部开盒引导 -->
  <text x="300" y="784" font-size="18" font-weight="800" fill="{accent}" letter-spacing="2" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">晃动盲盒 · 探寻今日美味</text>
  <text x="300" y="820" font-size="11" fill="#ffffff" opacity="0.45" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">非官方产品 · 参赛作品 · 盲盒为概念视觉设计，内含真实麦当劳在售餐品</text>
</svg>
'''
def main():
    ap = argparse.ArgumentParser(description="高级盲盒卡面与包装渲染器")
    ap.add_argument("--card", default="-", help="draw.py 输出的 JSON 文件，- 表示 stdin")
    ap.add_argument("--out", default="-", help="输出 SVG 路径，- 表示 stdout")
    ap.add_argument("--package", default="", help="系列 ID，渲染对应的未开箱盲盒包装盒")
    ap.add_argument("--no-embed", action="store_true",
                    help="不把商品图内联成 data URI（默认内联，确保 <img> 引用不裂图）")
    ap.add_argument("--slot", default="main",
                    choices=["main", "side", "drink", "box"],
                    help="当输入是端盒 JSON 时，渲染哪一部分（box=整盒大卡）")
    args = ap.parse_args()

    # 1. 如果请求渲染未开封盲盒包装
    if args.package:
        here = os.path.dirname(os.path.abspath(__file__))
        data_path = os.path.join(here, "..", "data", "series.json")
        defs = json.load(open(data_path, encoding="utf-8")).get("series", [])
        s = next((x for x in defs if x["id"] == args.package), None)
        if not s:
            s = {"id": args.package, "name": "麦泡泡盲盒", "tagline": "美味开盒",
                 "palette": {"base": "#8B1E2D", "accent": "#F2C14E"}}
        svg = render_package(s)
        if args.out == "-":
            print(svg)
        else:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(svg)
            print(args.out)
        return

    # 2. 正常卡片或端盒渲染
    raw = sys.stdin.read() if args.card == "-" else open(args.card, encoding="utf-8").read()
    card = json.loads(raw)
    if not card.get("ok", True):
        sys.exit("这张不是卡片：%s" % card.get("reason"))

    embed = not args.no_embed
    if card.get("box"):
        if args.slot == "box":
            svg = render_box(card, embed=embed)
        else:
            slot = next((s for s in card["box"]["slots"]
                         if s["experience"].get("slot") == args.slot), None)
            if slot is None:
                sys.exit(f"这个端盒里没有 {args.slot} 位")
            card = dict(card, fact=slot["fact"], experience=slot["experience"])
            svg = render(card, embed=embed)
    else:
        svg = render(card, embed=embed)

    if args.out == "-":
        print(svg)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(svg)
        print(args.out)


if __name__ == "__main__":
    main()
