#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦泡泡 PopMc · 引擎自检（标准库 unittest，无需安装任何依赖）

运行:
  cd skill/popmc && python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

spec = importlib.util.spec_from_file_location("draw", os.path.join(ROOT, "scripts", "draw.py"))
draw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw)

POOL = os.path.join(ROOT, "fixtures", "query_meals.sample.json")
NUT = os.path.join(ROOT, "fixtures", "nutrition.raw.txt")
NIGHT = "18:39"
MORNING = "08:00"


def pool_of(series_id, **kw):
    items, _ = draw.load_menu(POOL)
    nut = draw.parse_nutrition(open(NUT, encoding="utf-8").read())
    series, cfg, cards, raw, cand, after = draw.build_series_pool(
        series_id, items, nut, now=kw.pop("now", NIGHT), **kw)
    return series, cfg, cards, raw, cand, after, items, nut


class TestNormalize(unittest.TestCase):
    def test_category_newline(self):
        """MCP 分类名带换行符，必须归一化，否则系列匹配全失效"""
        self.assertEqual(draw.norm("巨无霸\n牛鱼肉堡"), "巨无霸牛鱼肉堡")
        self.assertEqual(draw.norm("小食拼盘\n/多人餐"), "小食拼盘多人餐")
        self.assertEqual(draw.norm("麦咖啡™"), "麦咖啡")

    def test_money(self):
        self.assertEqual(draw.money("47.5"), 47.5)
        self.assertEqual(draw.money(None), 0.0)


class TestNutritionParse(unittest.TestCase):
    def setUp(self):
        with open(NUT, encoding="utf-8") as f:
            self.table = draw.parse_nutrition(f.read())

    def test_parse_basic(self):
        self.assertEqual(self.table["巨无霸"]["energyKcal"], 513)
        self.assertEqual(self.table["巨无霸"]["proteinG"], 27)

    def test_official_note_kept(self):
        """官方'能量约X'描述必须原样保留，不能用自造比喻替换"""
        self.assertEqual(self.table["芝士安格斯厚牛堡"]["officialNote"], "能量约鲈鱼1条")

    def test_name_normalized(self):
        """全角括号要保留（否则与菜单名对不上），但 ™ / 换行要清掉"""
        self.assertIn("纯牛奶（盒装）", self.table)
        self.assertNotIn("™", "".join(self.table))

    def test_no_crash_on_header(self):
        self.assertGreater(len(self.table), 30)


class TestFilter(unittest.TestCase):
    def test_non_food_rejected(self):
        """菜单里混着周边，抽到一条丝巾是事故"""
        for name in ("麦当劳限定丝巾", "旋旋水手帽", "联名复古棒球帽"):
            self.assertFalse(draw.is_food(name, 34.9), name)

    def test_condiment_rejected(self):
        self.assertFalse(draw.is_food("韩式烟熏芝士风味酱", 3))
        self.assertTrue(draw.is_food("蘸酱麦麦脆汁鸡", 11.9))


class TestTimeGate(unittest.TestCase):
    """时段闸门：早餐系列不能在晚上被抽出来（SPEC 4.1 step1 / D9）"""

    def test_breakfast_closed_at_night(self):
        s, *_ = pool_of("breakfast", now=NIGHT)
        self.assertFalse(s["_availableNow"])
        self.assertEqual(s["_window"], ["05:00", "10:30"])

    def test_breakfast_open_in_morning(self):
        s, *_ = pool_of("breakfast", now=MORNING)
        self.assertTrue(s["_availableNow"])

    def test_all_day_series_always_open(self):
        for hp in ("05:00", "09:30", "13:00", "18:39", "23:50"):
            s, *_ = pool_of("chicken", now=hp)
            self.assertTrue(s["_availableNow"], hp)

    def test_window_wraps_midnight(self):
        self.assertTrue(draw.in_window((21 * 60, 5 * 60), 23 * 60))
        self.assertTrue(draw.in_window((21 * 60, 5 * 60), 2 * 60))
        self.assertFalse(draw.in_window((21 * 60, 5 * 60), 12 * 60))

    def test_bucket_boundaries(self):
        self.assertEqual(draw.time_bucket(10 * 60 + 29)[0], "breakfast")
        self.assertEqual(draw.time_bucket(10 * 60 + 30)[0], "lunch")
        self.assertEqual(draw.time_bucket(18 * 60 + 39)[0], "dinner")


class TestPool(unittest.TestCase):
    def test_dedupe_merges_categories(self):
        """巨无霸 1100 同时出现在「人气热卖」和「巨无霸牛鱼肉堡」，
        先到先得去重会把它从牛堡宇宙里静默丢掉（曾真实发生）"""
        items, _ = draw.load_menu(POOL)
        self.assertIn("巨无霸牛鱼肉堡", items["1100"]["categories"])
        self.assertIn("人气热卖", items["1100"]["categories"])

    def test_beef_universe_contains_icon(self):
        _s, _c, cards, *_ = pool_of("beef-universe")
        codes = [c["fact"]["productCode"] for c in cards]
        self.assertIn("1100", codes, "图腾款巨无霸必须在池内")
        ssr = [c for c in cards if c["experience"]["rarity"] == "SSR"]
        self.assertEqual(len(ssr), 1)
        self.assertEqual(ssr[0]["fact"]["productCode"], "1100")

    def test_combo_excluded_from_beef_singles(self):
        _s, _c, cards, *_ = pool_of("beef-universe")
        self.assertFalse([c for c in cards if "三件套" in c["fact"]["name"]])

    def test_card_no_stable(self):
        a = pool_of("chicken")[2]
        b = pool_of("chicken")[2]
        self.assertEqual([c["experience"]["cardNo"] for c in a],
                         [c["experience"]["cardNo"] for c in b])

    def test_nutrition_not_guessed(self):
        """套餐在营养表里不存在 → nutrition 必须为 null，不得按名称估算"""
        _s, _c, cards, *_ = pool_of("beef-universe")
        burger = next(c for c in cards if c["fact"]["productCode"] == "1100")
        self.assertIsNotNone(burger["fact"]["nutrition"])
        combo = next(c for c in pool_of("combo")[2] if c["fact"]["kind"] == "combo")
        self.assertIsNone(combo["fact"]["nutrition"])

    def test_rarity_labels_from_data(self):
        """档位中文名必须来自 rarity.json，不得在代码里另写一套"""
        cfg = draw.load_json("rarity.json")
        labels = {t["id"]: t["label"] for t in cfg["tiers"]}
        for c in pool_of("chicken")[2]:
            self.assertEqual(c["experience"]["rarityLabel"], labels[c["experience"]["rarity"]])


class TestHardConstraints(unittest.TestCase):
    def test_budget_is_hard(self):
        _s, _c, _cards, _raw, cand, _after, *_ = pool_of("chicken", budget=16)
        self.assertTrue(cand)
        self.assertTrue(all(i["price"] <= 16 for i in cand))

    def test_empty_pool_returns_nothing(self):
        """预算不足时必须返回空集合，由调用方走空池协议，不得放宽预算凑一个结果"""
        _s, _c, cards, *_ = pool_of("beef-universe", budget=1)
        self.assertEqual(cards, [])

    def test_exclude_keyword(self):
        _s, _c, _cards, _raw, cand, _after, *_ = pool_of("beef-universe", excludes=["牛肉"])
        self.assertTrue(all("牛肉" not in i["name"] for i in cand))

    def test_reason_distinguishes_three_failures(self):
        """空池必须分清是'没这个系列'/'被你排除了'/'预算不够'（原来全报 budget_too_low）"""
        _s, _c, _cards, raw, cand, after, *_ = pool_of("breakfast", now=NIGHT)
        self.assertEqual(raw, [], "本店无早餐 → raw 空")

        _s, _c, _cards, raw, cand, after, *_ = pool_of("dessert", now=NIGHT,
                                                       excludes=["圆筒", "冰淇淋", "派", "麦旋风", "爆爆珠"])
        self.assertTrue(raw)
        self.assertEqual(after, [], "排除后为空 → all_excluded")

        _s, _c, _cards, raw, cand, after, *_ = pool_of("beef-universe", now=NIGHT, budget=1)
        self.assertTrue(after)
        self.assertEqual(cand, [], "预算筛空 → budget_too_low")


class TestDeterminism(unittest.TestCase):
    def setUp(self):
        s, cfg, cards, *_ = pool_of("chicken")
        self.series, self.cfg, self.cards = s, cfg, cards

    def _draw(self, nonce, avoid=None):
        c = {"sinceR": 0, "sinceSSR": 0, "totalDraws": 0}
        card, _c2, meta = draw.do_draw(self.series, self.cfg, self.cards, nonce, c,
                                       "default", "neutral", avoid=avoid)
        return card, meta

    def test_same_seed_same_card(self):
        a, ma = self._draw(7)
        b, mb = self._draw(7)
        self.assertEqual(a["fact"]["productCode"], b["fact"]["productCode"])
        self.assertEqual(ma["seedHash"], mb["seedHash"])

    def test_different_nonce_moves(self):
        seen = {self._draw(n)[0]["experience"]["cardNo"] for n in range(1, 25)}
        self.assertGreater(len(seen), 1)

    def test_fingerprint_changes_with_pool(self):
        self.assertNotEqual(draw.fingerprint(self.cards), draw.fingerprint(self.cards[:3]))

    def test_avoid_prevents_repeat(self):
        """再抽一次不能原地打转：抽过的卡要从候选里让开"""
        first, _ = self._draw(1)
        code = first["fact"]["productCode"]
        for n in range(2, 12):
            card, _m = self._draw(n, avoid=[code])
            self.assertNotEqual(card["fact"]["productCode"], code, f"nonce={n} 又抽到同一张")


class TestDistribution(unittest.TestCase):
    def test_pity_raises_ssr(self):
        """SSR 权重 1.5%，但 50 抽保底会把实际概率抬到 ≈2%；
        对外公示必须用含保底的实际值，而不是裸权重"""
        _s, cfg, cards, *_ = pool_of("beef-universe")
        counters, ssr, n = {"sinceR": 0, "sinceSSR": 0}, 0, 5000
        for i in range(n):
            card, counters, _m = draw.do_draw({"id": "t"}, cfg, cards, i, counters, "default", "neutral")
            if card["experience"]["rarity"] == "SSR":
                ssr += 1
        self.assertGreater(ssr / n, 0.015, "保底应把 SSR 实际概率抬到权重之上")
        self.assertLess(ssr / n, 0.06)

    def test_pity_guarantee(self):
        """连续 50 抽必出 SSR"""
        _s, cfg, cards, *_ = pool_of("beef-universe")
        counters, hit = {"sinceR": 0, "sinceSSR": 0}, False
        for i in range(50):
            card, counters, _m = draw.do_draw({"id": "t"}, cfg, cards, i, counters, "default", "neutral")
            if card["experience"]["rarity"] == "SSR":
                hit = True
        self.assertTrue(hit)

    def test_measure_is_called_by_odds(self):
        """--odds 必须给出含保底的实际概率，不能只报裸权重"""
        _s, cfg, cards, *_ = pool_of("chicken")
        actual = draw.measure(cfg, cards, n=3000)
        self.assertAlmostEqual(sum(actual.values()), 1.0, places=2)


class TestDegeneratePools(unittest.TestCase):
    """退化池：只有一个等级、只有一张卡、全部被避开时都不能崩"""

    def _cards(self, series_id, keep=None):
        _s, _cfg, cards, *_ = pool_of(series_id)
        return [c for c in cards if keep is None or c["experience"]["rarity"] == keep]

    def test_single_ssr_pool_never_crashes(self):
        """回归：池里只有 SSR 卡时，抽到 N 档会走到不存在的档位 → 除零。
        （曾真实抛 ZeroDivisionError: integer modulo by zero）"""
        _s, cfg, _all, *_ = pool_of("beef-universe")
        cards = self._cards("beef-universe", "SSR")
        self.assertEqual(len(cards), 1)
        for nonce in range(1, 60):
            card, _c, _m = draw.do_draw(_s, cfg, cards, nonce,
                                        {"sinceR": 0, "sinceSSR": 0}, "default", "neutral")
            self.assertEqual(card["experience"]["rarity"], "SSR")

    def test_pick_tier_always_exists(self):
        _s, cfg, cards, *_ = pool_of("chicken")
        for tier in ("N", "R", "SR", "SSR"):
            sub = self._cards("chicken", tier)
            if not sub:
                continue
            for seed in range(30):
                got = draw.pick_tier(cfg["tiers"], sub, {"sinceR": 0, "sinceSSR": 11},
                                     cfg["pity"], f"seed{seed}")
                self.assertIn(got, {c["experience"]["rarity"] for c in sub})

    def test_all_avoided_falls_back_to_pool(self):
        _s, cfg, cards, *_ = pool_of("dessert")
        codes = [c["fact"]["productCode"] for c in cards]
        card, _c, meta = draw.do_draw(_s, cfg, cards, 1, {"sinceR": 0, "sinceSSR": 0},
                                      "default", "neutral", avoid=codes)
        self.assertIn(card["fact"]["productCode"], codes)
        self.assertEqual(meta["avoided"], len(codes))


class TestBox(unittest.TestCase):
    """端盒（SPEC §5.4）：主食+小食+饮料，永不超预算"""

    def _box(self, series_id="chicken", budget=0.0, excludes=None, nonce=1):
        series, cfg, _cards, *_rest = pool_of(series_id)
        items, nut = _rest[-2], _rest[-1]
        labels = {t["id"]: t["label"] for t in cfg["tiers"]}
        return draw.build_box(series, cfg, labels, items, nut, budget,
                              excludes or [], nonce, "neutral", "default")

    def test_structure_three_slots(self):
        box, reason, _d = self._box(budget=0)
        self.assertIsNone(reason)
        self.assertEqual(box["structure"], "主食+小食+饮料")
        self.assertEqual(len(box["slots"]), 3)

    def test_never_over_budget(self):
        for b in (25, 32, 40, 55, 80):
            box, reason, _d = self._box(budget=b)
            self.assertIsNone(reason, b)
            self.assertLessEqual(box["totalPrice"], b + 1e-9, f"预算 {b} 被超出")

    def test_no_duplicate_items_in_box(self):
        for n in range(1, 8):
            box, _r, _d = self._box(budget=0, nonce=n)
            codes = [c["fact"]["productCode"] for c in box["slots"]]
            self.assertEqual(len(codes), len(set(codes)))

    def test_slots_not_same_kind(self):
        box, _r, _d = self._box()
        kinds = [c["fact"]["kind"] for c in box["slots"]]
        self.assertEqual(kinds[0] in ("main", "combo"), True)
        self.assertEqual(len(set(kinds)), 3)

    def test_total_is_sum_of_parts(self):
        box, _r, _d = self._box()
        self.assertAlmostEqual(box["totalPrice"],
                               round(sum(c["fact"]["price"] for c in box["slots"]), 2))
        # 营养覆盖不保证满：套餐/部分新品在官方营养表里没有记录时必须留空
        covered, total = box["kcalCovered"].split("/")
        self.assertEqual(int(total), len(box["slots"]))
        self.assertLessEqual(int(covered), int(total))
        if int(covered) == 0:
            self.assertIsNone(box["totalKcal"], "一条营养数据都没有时不得编造总热量")

    def test_tiny_budget_degrades_not_explodes(self):
        """预算只够一份主食时，降级成 1 件，而不是超预算硬凑三件"""
        box, reason, _d = self._box(budget=16)
        self.assertIsNone(reason)
        self.assertEqual(box["structure"], "主食")
        self.assertLessEqual(box["totalPrice"], 16)

    def test_zero_available_main_reports_reason(self):
        box, reason, detail = self._box(budget=1)
        self.assertIsNone(box)
        self.assertEqual(reason, "budget_too_low")
        self.assertTrue(detail)


class TestStateAndMemory(unittest.TestCase):
    def test_nonce_autoincrements(self):
        """原来 nonce 要调用方手动加，LLM 一旦忘记，'再抽一次'会拿到同一张卡"""
        state = {}
        day = "2026-10-24"
        self.assertEqual(draw.next_nonce(state, day), 1)
        self.assertEqual(draw.next_nonce(state, day), 2)
        self.assertEqual(draw.next_nonce(state, day), 3)
        self.assertEqual(draw.next_nonce(state, day, "99"), 99)

    def test_blacklist_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "collection.json")
            state = {"blacklist": ["牛肉"]}
            draw.save_state(path, state)
            self.assertEqual(draw.load_state(path)["blacklist"], ["牛肉"])

    def test_corrupt_state_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(draw.load_state(path), {})


class TestCopySafety(unittest.TestCase):
    def test_no_forbidden_words(self):
        for sid in ("beef-universe", "chicken", "dessert", "party", "combo"):
            for c in pool_of(sid)[2]:
                text = draw.flavor_text(c, "neutral")
                self.assertFalse(any(w in text for w in draw.FORBIDDEN), f"{sid}: {text}")

    def test_disclaimers_present(self):
        for attr in ("DISCLAIMER", "RARITY_NOTE", "SERIES_NOTE", "BOX_NOTE", "COLLECT_NOTE"):
            self.assertTrue(getattr(draw, attr))

    def test_side_slot_no_series_hook(self):
        """端盒里的小食/饮料不该继承主食系列的钩子（清水被写成'咔嚓一声'）"""
        card = {"fact": {"productCode": "1", "name": "纯悦", "tags": [], "kind": "drink"},
                "experience": {"rarity": "R", "seriesCode": "CH", "slot": "drink"}}
        text = draw.flavor_text(card, "neutral")
        self.assertNotIn("咔嚓", text)


class TestPayload(unittest.TestCase):
    def test_three_layers_present(self):
        s, cfg, cards, *_ = pool_of("chicken")
        card, _c, meta = draw.do_draw(s, cfg, cards, 1, {"sinceR": 0, "sinceSSR": 0},
                                      "default", "neutral")
        payload = draw.ok_payload(s, card, meta)
        for key in ("ok", "series", "fact", "experience", "meta", "disclaimer"):
            self.assertIn(key, payload)
        self.assertEqual(payload["series"]["disclaimer"], draw.SERIES_NOTE)
        self.assertEqual(payload["experience"]["rarityNote"], draw.RARITY_NOTE)
        # fact 层不得混入体验字段
        for bad in ("rarity", "flavorText", "cardNo", "rarityNote"):
            self.assertNotIn(bad, payload["fact"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
