#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦泡泡 PopMc · 收藏册与人格卡

本地 JSON，无账号、无云端、可一键清除。只存 productCode / 次数 / 时间。
明确边界：收藏记录是"抽取历史"，不是"购买记录"（DESIGN-DECISIONS D6）。

用法:
  python3 collection.py --state ~/.popmc/collection.json stats
  python3 collection.py --state ~/.popmc/collection.json clear
"""

import argparse
import json
import os
import sys
from collections import Counter

DEFAULT = os.path.expanduser("~/.popmc/collection.json")
BUCKETS = (
    ("beef", "牛肉派", ("牛肉", "牛堡", "巨无霸", "安格斯", "吉士")),
    ("fried", "脆皮依赖", ("炸鸡", "鸡翅", "麦乐鸡", "鸡排", "脆汁鸡", "V翅", "鸡块")),
    ("sweet", "甜品续命", ("冰淇淋", "麦旋风", "新地", "派", "圆筒", "阿芙佳朵", "芝士条")),
    ("coffee", "咖啡因驱动", ("麦咖啡", "奶铁", "美式", "拿铁", "卡布", "鲜萃", "黑巧")),
    ("light", "轻食自律", ("玉米杯", "苹果片", "纯悦", "无糖", "500大卡")),
    ("share", "社交型", ("拼盘", "多人餐", "分享", "双人", "亲子", "开心乐园")),
)
PERSONA_LINES = {
    "beef": ("你和巨无霸的关系，比和同事还稳定。", "牛肉是你的底层架构。"),
    "fried": ("咔嚓声是你的开机音效。", "你不是爱吃鸡，你是爱那个声音。"),
    "sweet": ("甜味不是奖励，是基础设施。", "你的情绪管理方案是圆筒。"),
    "coffee": ("你的血液里有一条麦咖啡管线。", "困不是问题，没续上才是。"),
    "light": ("你在自律和薯条之间，保持了体面的平衡。", "玉米杯是你最后的克制。"),
    "share": ("一个人吃叫吃饭，两个人吃才叫麦门。", "你负责组局，也负责拆盒。"),
}
NOTE = "收藏是抽取历史，不代表购买记录，也不代表该商品当前仍在售。"


def load(path):
    if not os.path.exists(path):
        return {"version": 1, "counters": {}, "owned": {}, "blacklist": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bucket_of(name):
    for key, _label, kws in BUCKETS:
        if any(k in name for k in kws):
            return key
    return None


def stats(state):
    owned = state.get("owned", {})
    total = sum(v.get("count", 0) for s in owned.values() for v in s.values())
    if not total:
        print("还没有拆过盒。说一句「今天吃什么」就能开第一盒。")
        return

    counts, names = Counter(), {}
    for series_id, cards in owned.items():
        for code, rec in cards.items():
            counts[bucket_of(rec.get("name", ""))] += rec.get("count", 0)
            names[code] = rec.get("name", code)
    counts.pop(None, None)
    total_b = sum(counts.values()) or 1

    print("── 图鉴 ──")
    for series_id, cards in sorted(owned.items()):
        print(f"  {series_id:<14} 已收 {len(cards):>2} 张")
    print(f"  合计 {total} 抽 · {len(names)} 个不同商品\n")

    if not counts:
        return
    (top, top_n), = counts.most_common(1)
    label = next(l for k, l, _ in BUCKETS if k == top)
    second = counts.most_common(2)[1] if len(counts) > 1 else None
    print("── 你的麦门 DNA ──")
    print(f"  主属性：{label}（{top_n / total_b * 100:.0f}%）")
    if second:
        s_label = next(l for k, l, _ in BUCKETS if k == second[0])
        print(f"  副属性：{s_label}（{second[1] / total_b * 100:.0f}%）")
    lines = PERSONA_LINES.get(top, ("你吃得很均匀。",))
    print(f"  人格句：{lines[top_n % len(lines)]}")
    print(f"\n  {NOTE}")


def clear(path):
    if os.path.exists(path):
        os.remove(path)
        print("已清除。下次开盒会重新开始记录。")
    else:
        print("本来就没有记录。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=DEFAULT)
    ap.add_argument("cmd", choices=["stats", "clear"])
    args = ap.parse_args()
    if args.cmd == "clear":
        return clear(args.state)
    return stats(load(args.state))


if __name__ == "__main__":
    sys.exit(main())
