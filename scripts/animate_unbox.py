#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦泡泡 PopMc · 泡泡玛特风格开盒动效生成器 (GIF & 交互动效) v2.0

将盲盒抽卡结果转化为一段完整的开盒动效：
  1. 摇盒听声阶段（0% - 25%）：盲盒在聚光灯下左右晃动颠簸、期待感拉满；
  2. 撕条开箱阶段（25% - 45%）：封条裂开、金色闪光迸发、盒盖掀起弹开；
  3. 神光升腾阶段（45% - 70%）：盒口迸发 8 芒金色天光与粒子，高保真食物卡破光而出飞升居中；
  4. 华丽定格阶段（70% - 100%）：完整高保真卡牌完全展露（含 4 格属性胶囊、防伪条形码、展台光影），全息流光扫过定格。

输出：
  - `unboxing.gif`：全平台兼容（微信、网页、GitHub 均可直接动）的高画质 GIF
"""

import argparse
import base64
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PYTHON_ENV = "/Users/mingshenshuai/.workbuddy/binaries/python/envs/default/bin/python3"

# 引入已有的卡面渲染库
sys.path.insert(0, HERE)
import render_card

W, H = 500, 700


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def shade(hex_color, factor):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(v * factor))) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_full_card_components(card_payload):
    """从 render_card.render 中提取完整的 defs 和主体 g，以便嵌入动效画卷中。"""
    full_svg = render_card.render(card_payload, embed=True)
    # 提取 <defs>...</defs>
    defs_match = re.search(r'<defs>(.*?)</defs>', full_svg, re.DOTALL)
    defs_content = defs_match.group(1) if defs_match else ""

    # 提取所有主体图元（跳过外层 svg 声明）
    body = full_svg
    body = re.sub(r'<\?xml.*?\?>', '', body)
    body = re.sub(r'<svg[^>]*>', '', body)
    body = re.sub(r'<defs>.*?</defs>', '', body, flags=re.DOTALL)
    body = re.sub(r'</svg>\s*$', '', body)
    return defs_content, body


def render_unboxing_frame(card_payload, t, card_defs, card_body):
    """根据时间进度 t (0.0 ~ 1.0) 渲染单个动画帧。

    W=500, H=700，中央基准点 (250, 360)。
    """
    series = card_payload.get("series", {})
    fact = card_payload.get("fact", {})
    exp = card_payload.get("experience", {})

    base = series.get("palette", {}).get("base", "#8B1E2D")
    accent = series.get("palette", {}).get("accent", "#F2C14E")
    rarity = exp.get("rarity", "N")
    sname = series.get("name", "麦泡泡")
    badge_label = exp.get("rarityLabel") or render_card.LABEL.get(rarity, "")

    # 1. 计算动效变量
    box_visible = True
    box_opacity = 1.0
    box_rot = 0.0
    box_dy = 0.0
    lid_open_y = 0.0
    lid_scale_y = 1.0
    tape_cut = 0.0
    burst_opacity = 0.0
    burst_rot = 0.0

    card_visible = False
    card_opacity = 0.0
    card_scale = 0.20
    card_y = 480
    card_rot = 0.0

    # 阶段 1：摇盒 (0.00 ~ 0.24)
    if t < 0.24:
        p = t / 0.24
        box_rot = math.sin(p * math.pi * 4) * 6.0
        box_dy = -abs(math.sin(p * math.pi * 4)) * 7.0
        status_text = "摇一摇 · 听听里面装的什么..."
    # 阶段 2：撕开封条与开盖 (0.24 ~ 0.44)
    elif t < 0.44:
        p = (t - 0.24) / 0.20
        box_rot = 0.0
        box_dy = 0.0
        tape_cut = min(1.0, p * 1.6)
        lid_open_y = -p * 68.0
        lid_scale_y = max(0.15, 1.0 - p * 0.8)
        burst_opacity = min(1.0, p * 2.0)
        burst_rot = p * 45.0
        status_text = "咔嚓！封条解开，神光显现！"
    # 阶段 3：食物卡升腾飞升 (0.44 ~ 0.70)
    elif t < 0.70:
        p = (t - 0.44) / 0.26
        tape_cut = 1.0
        lid_open_y = -68.0 - p * 24.0
        lid_scale_y = 0.1
        box_opacity = max(0.0, 1.0 - p * 1.3)
        burst_opacity = max(0.2, 1.0 - p * 0.5)
        burst_rot = 45.0 + p * 60.0

        card_visible = True
        card_opacity = min(1.0, p * 2.2)
        # 弹簧缓冲飞升曲线
        card_scale = 0.22 + (0.65 - 0.22) * (1 - math.cos(p * math.pi * 0.5))
        card_y = 480 - (480 - 360) * (1 - math.cos(p * math.pi * 0.5))
        card_rot = (1.0 - p) * 8.0 * math.sin(p * math.pi * 2)
        status_text = f"正在揭晓：{badge_label} 藏品！"
    # 阶段 4：定格展示 (0.70 ~ 1.00)
    else:
        p = (t - 0.70) / 0.30
        box_visible = False
        card_visible = True
        card_opacity = 1.0
        # 完整比例放大约到 0.68，适配 500x700 画面
        card_scale = 0.65 + 0.03 * math.sin(p * math.pi)
        card_y = 360
        card_rot = 0.0
        burst_opacity = max(0.0, 0.35 - p * 0.35)
        status_text = f"★ 恭喜抽中【{fact.get('name', '')}】！"

    # 光芒放射射线 (Ray Burst)
    rays = []
    if burst_opacity > 0.01:
        for i in range(12):
            ang = burst_rot + i * 30
            rad = ang * math.pi / 180
            x1 = 250 + math.cos(rad) * 40
            y1 = 340 + math.sin(rad) * 40
            x2 = 250 + math.cos(rad) * 280
            y2 = 340 + math.sin(rad) * 280
            rays.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                        f'stroke="url(#burst_gold)" stroke-width="6" opacity="{burst_opacity * 0.75:.2f}" stroke-linecap="round"/>')

    # 生成盒子 SVG 碎片
    box_svg = ""
    if box_visible:
        tape_left_x = 20 - tape_cut * 140
        tape_right_x = 160 + tape_cut * 140
        box_svg = f'''
    <g id="box_assembly" opacity="{box_opacity:.2f}" transform="translate(250, {360 + box_dy:.1f}) rotate({box_rot:.1f}) translate(-140, -210)">
      <!-- 盒体物理投影 -->
      <ellipse cx="140" cy="435" rx="135" ry="16" fill="#000000" opacity="0.5"/>

      <!-- 麦当劳经典开心乐园餐双拱提手 (Lid Arch) -->
      <g transform="translate(0, {lid_open_y:.1f}) scale(1, {lid_scale_y:.2f})">
        <path d="M 45 38 L 235 38 Q 235 -8 140 -8 Q 45 -8 45 38 Z" fill="#eb2c1e" stroke="rgba(255,255,255,0.4)" stroke-width="1.8"/>
        <path d="M 95 24 Q 95 5 140 5 Q 185 5 185 24 Q 185 28 140 28 Q 95 28 95 24 Z" fill="#0c0406" opacity="0.5"/>
      </g>

      <!-- 麦当劳经典红盒主方体 (含芝麻底纹) -->
      <rect x="15" y="36" width="250" height="380" rx="20" fill="#da291c"/>
      <rect x="15" y="36" width="250" height="380" rx="20" fill="url(#grid_dots)"/>
      <rect x="15" y="36" width="250" height="380" rx="20" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="2"/>

      <!-- 顶部小徽标 -->
      <text x="140" y="62" font-size="11" font-weight="900" fill="#ffffff" letter-spacing="2" text-anchor="middle"
            font-family="PingFang SC, Noto Sans SC, sans-serif">★ PopMc · S1 ★</text>

      <!-- 问号橱窗（带汉堡轮廓） -->
      <g transform="translate(35, 74)">
        <rect x="0" y="0" width="210" height="224" rx="16" fill="#0c0406" opacity="0.85"/>
        <rect x="0" y="0" width="210" height="224" rx="16" fill="none" stroke="#ffbc0d" stroke-width="2" opacity="0.9"/>
        <!-- 汉堡微轮廓 -->
        <path d="M 105 55 Q 50 55 50 85 L 160 85 Q 160 55 105 55 Z" fill="#ffbc0d" opacity="0.12"/>
        <path d="M 48 95 L 162 95 Q 170 102 162 110 L 48 110 Q 40 102 48 95 Z" fill="#ffbc0d" opacity="0.12"/>
        <path d="M 55 125 L 155 125 Q 155 145 105 145 Q 55 145 55 125 Z" fill="#ffbc0d" opacity="0.12"/>
        <!-- 大金问号 -->
        <text x="105" y="160" font-size="108" font-weight="900" fill="url(#box_gold)" text-anchor="middle"
              font-family="Impact, PingFang SC, sans-serif">?</text>
        <text x="105" y="196" font-size="9" font-weight="800" fill="#ffbc0d" text-anchor="middle" letter-spacing="2"
              font-family="PingFang SC, Noto Sans SC, sans-serif">WHO IS INSIDE</text>
      </g>

      <!-- 经典红黄外带锯齿安全封条撕开 -->
      <g opacity="{max(0.0, 1.0 - tape_cut):.2f}">
        <rect x="15" y="310" width="250" height="32" fill="url(#tape_grad)"/>
        <text x="140" y="330" font-size="10" font-weight="900" fill="#140808" letter-spacing="2" text-anchor="middle"
              font-family="PingFang SC, Noto Sans SC, sans-serif">✦ 麦麦开盒 · 现制美味 ✦</text>
      </g>

      <!-- 底部系列 -->
      <text x="140" y="375" font-size="13" font-weight="800" fill="#ffffff" text-anchor="middle" opacity="0.95"
            font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(sname)} · 今日在售</text>
      <text x="140" y="394" font-size="9" fill="#ffd166" opacity="0.85" text-anchor="middle" letter-spacing="1"
            font-family="PingFang SC, Noto Sans SC, sans-serif">AUTHENTIC MCDONALD\'S REAL FOOD</text>
    </g>
    '''
    # 生成高保真完整卡牌飞升与定格层 (嵌入原始 600x840 的完整卡牌，做变换缩放)
    card_svg = ""
    if card_visible:
        card_svg = f'''
    <g id="full_card_assembly" opacity="{card_opacity:.2f}"
       transform="translate(250, {card_y:.1f}) scale({card_scale:.4f}) rotate({card_rot:.1f}) translate(-300, -420)">
      {card_body}
    </g>
    '''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <radialGradient id="stage_bg" cx="50%" cy="30%" r="85%">
      <stop offset="0%" stop-color="{shade(base, 1.45)}"/>
      <stop offset="45%" stop-color="{base}"/>
      <stop offset="85%" stop-color="{shade(base, 0.35)}"/>
      <stop offset="100%" stop-color="#070508"/>
    </radialGradient>
    <linearGradient id="box_gold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ffd166"/><stop offset="50%" stop-color="#ffffff"/><stop offset="100%" stop-color="#d49b22"/>
    </linearGradient>
    <linearGradient id="burst_gold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#fff275"/><stop offset="50%" stop-color="#ffb703"/><stop offset="100%" stop-color="#fb8500"/>
    </linearGradient>
    <linearGradient id="tape_grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#ffb703"/><stop offset="50%" stop-color="#ffd166"/><stop offset="100%" stop-color="#fb8500"/>
    </linearGradient>
    <pattern id="grid_dots" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="10" cy="10" r="1.1" fill="#ffffff" opacity="0.08"/>
    </pattern>
    {card_defs}
  </defs>

  <!-- 背景 -->
  <rect width="{W}" height="{H}" rx="28" fill="url(#stage_bg)"/>
  <rect width="{W}" height="{H}" rx="28" fill="url(#grid_dots)"/>
  <rect x="8" y="8" width="{W - 16}" height="{H - 16}" rx="22" fill="none" stroke="#ffffff" stroke-width="1" opacity="0.12"/>

  <!-- 顶部状态栏 -->
  <text x="250" y="44" font-size="11" font-weight="800" fill="{accent}" letter-spacing="3" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">POPMART STYLE · UNBOXING</text>
  <text x="250" y="70" font-size="18" font-weight="800" fill="#ffffff" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">{esc(status_text)}</text>

  <!-- 神光放射层 -->
  <g id="rays_layer">
    {''.join(rays)}
  </g>

  <!-- 盲盒外盒 -->
  {box_svg}

  <!-- 揭晓的高保真完整卡牌 -->
  {card_svg}

  <!-- 底部微标 -->
  <text x="250" y="{H - 24}" font-size="10" fill="#ffffff" opacity="0.4" text-anchor="middle"
        font-family="PingFang SC, Noto Sans SC, sans-serif">麦泡泡 PopMc · 基于麦当劳官方MCP实时抽取 · 真实在售食物盲盒</text>
</svg>
'''


def make_gif(card_payload, output_gif_path, total_frames=24, fps=10):
    """生成全流程平滑的 GIF 动图。"""
    temp_dir = tempfile.mkdtemp(prefix="mcbox_frames_")
    frame_files = []
    print(f"[info] 正在准备高保真组件与计算 {total_frames} 帧开盒动画...")

    # 提取高保真卡牌组件
    card_defs, card_body = extract_full_card_components(card_payload)

    try:
        # 1. 批量生成 SVG 帧文件
        svg_paths = []
        for i in range(total_frames):
            t = i / float(total_frames - 1)
            svg_content = render_unboxing_frame(card_payload, t, card_defs, card_body)
            svg_path = os.path.join(temp_dir, f"frame_{i:03d}.svg")
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            svg_paths.append(svg_path)

        # 2. 调用 Chrome Headless 批量转成高清 PNG
        for i, svg_path in enumerate(svg_paths):
            png_path = os.path.join(temp_dir, f"frame_{i:03d}.png")
            cmd = [
                CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                f"--screenshot={png_path}", f"--window-size={W},{H}",
                f"file://{svg_path}"
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            frame_files.append(png_path)

        # 3. 使用 Pillow 读取并合成高质量动画 GIF
        print("[info] 正在合成 GIF 动图并优化调色板...")
        script = f'''
import sys
from PIL import Image

frame_paths = {json.dumps(frame_files)}
out_path = "{output_gif_path}"
fps = {fps}

images = [Image.open(p).convert("RGBA") for p in frame_paths]

# 设置帧停留时长：普通帧 100ms，最后一帧停留 2200ms (供欣赏抽中结果)
durations = [int(1000 / fps)] * len(images)
durations[-1] = 2200

# 优化转换为自适应 256 色调色板
rgb_images = []
for im in images:
    bg = Image.new("RGB", im.size, (15, 12, 18))
    bg.paste(im, mask=im.split()[3])
    p_img = bg.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    rgb_images.append(p_img)

rgb_images[0].save(
    out_path,
    save_all=True,
    append_images=rgb_images[1:],
    duration=durations,
    loop=0,
    optimize=True
)
print("[ok] GIF 保存成功:", out_path)
'''
        subprocess.run([PYTHON_ENV, "-c", script], check=True)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"[done] 开盒动效图制作完毕: {output_gif_path} ({os.path.getsize(output_gif_path) // 1024} KB)")


def main():
    ap = argparse.ArgumentParser(description="生成泡泡玛特风格开盒动图 (GIF)")
    ap.add_argument("--card", required=True, help="draw.py 输出的卡片 JSON")
    ap.add_argument("--out", default="unboxing.gif", help="输出 GIF 路径")
    ap.add_argument("--frames", type=int, default=24, help="总帧数（默认 24 帧，约 2.4 秒）")
    ap.add_argument("--fps", type=int, default=10, help="每秒帧率（默认 10）")
    args = ap.parse_args()

    payload = json.load(open(args.card, encoding="utf-8"))
    make_gif(payload, args.out, total_frames=args.frames, fps=args.fps)


if __name__ == "__main__":
    main()
