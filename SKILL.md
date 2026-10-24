---
name: popmc
description: >
  麦泡泡 PopMc——把麦当劳门店"此刻真实在售"的菜单变成一盒可以拆的食物盲盒。
  当用户说"不知道吃什么/今天吃什么/随便来一个/帮我抽一个/开个盲盒/拆盒/抽一餐/凑一顿/看图鉴/我的麦门 DNA"，
  或表达选择困难、想在预算内被安排一顿时使用。基于麦当劳 MCP 实时菜单抽取，极速输出动效与高保真卡牌，
  并可在用户明确确认后进入点餐。
  注意：抽盒结果不自动下单；商品、价格、营养一律以 MCP 实时返回为准。
user-invocable: true
metadata:
  scope: workspace
  integration: mcd-mcp
  version: "1.2.0"
---

# 麦泡泡 PopMc (麦当劳潮玩食物盲盒)

把「今天吃什么」变成一次**秒级响应、有惊喜、能收藏、可下单**的极速开盒。

**一句话原则**：盲盒负责制造惊喜，MCP 负责提供事实，你负责表达情绪。三者不得互相冒充。

---

## ⚡ 极速加载策略（Fast-Path：首轮零等待）

**核心交互底线：严禁在首轮开盒前盘问用户！**
用户只要表达“不知道吃什么/抽一个”，智能体**绝不中途停下来问用户“你自取还是外送？你在哪个城市？”**，必须**首轮直接出开盒卡牌**！

- **默认场景**：到店自取（90% 高频场景）；
- **默认门店**：优先从当前会话提取，若无则调用 `query-nearby-stores` 快速取就近第 1 家；
- **本地缓存加速**：首次调用 `query-meals` 成功后存入 `/tmp/popmc_pool_<storeCode>.json`。15 分钟内“再抽一次/换系列”直接复用本地池，**0 网络延迟瞬时出卡（<50ms）**；
- **免调接口**：时段判定（早餐/午餐/晚餐）由 Python 引擎本地精准完成，**禁止调用 `now-time-info`**。

---

## 🏃 极速三步主流程

### ① 极速拉池（有缓存读缓存，无缓存查一次）
```bash
# 检查本地是否有 15 分钟内的有效菜单缓存：/tmp/popmc_pool_<storeCode>.json
# 若无，则并发或顺次获取：
query-nearby-stores(beType=1, searchType=2, city="<城市或自动>", keyword="<地标或空>")
query-meals(storeCode, orderType=1, beType=1) -> 存入 /tmp/popmc_pool_<storeCode>.json
```

### ② 瞬时抽盒（50毫秒完成计算）
```bash
# 单抽（自动按情绪抽选系列，结果 JSON 内部已包含 assets 图片秒级引用）
python3 scripts/draw.py --pool /tmp/popmc_pool_<storeCode>.json --mood "<用户原话>" [--budget 30] [--exclude 牛肉]

# 端盒（主食 + 小食 + 饮料，整盒预算硬约束）
python3 scripts/draw.py --pool /tmp/popmc_pool_<storeCode>.json --box --budget 45 --mood "<用户原话>"
```

### ③ 秒级图文输出
直接读取返回结果中的 `d['assets']['unboxGif']` 或 `d['assets']['cardSvg']` 贴出卡片！
无需现场等待二次渲染。如需另存最新定制卡片，可后台异步执行 `render_card.py`。

---

## 🎯 极简输出格式（三行干货流，绝不废话）

摒弃冗长说教，只呈现最有冲击力的盲盒结果：

```markdown
正在摇匀本店 132 个美味可能… 开！

![盲盒开箱](assets/unbox/unboxing-ssr.gif)

### 🍔【牛堡宇宙 · 图腾】巨无霸 · ¥25.5
> 两层牛肉，一个宇宙。传说就该这样出场。
- **官方营养**：513 kcal ｜ 蛋白质 27g ｜ 脂肪 26g
- **门店现价**：¥25.5 (单点实价)

👉 **就它了，要下单吗？**
*(默认基于当前门店·到店自取，如需换店、换系列或改外送随时告诉我)*
```

如果是端盒：
```markdown
给你凑好了一整盒！主食+小食+饮料一次满足：

![端盒全套展柜](assets/cards/box-chicken.svg)

### 🍱【端盒组合】板烧鸡腿堡 + 经典大薯条 + 可口可乐
- **整盒总计**：¥46.5 (预算 ¥50 内锁定)
- **官方热量**：929 kcal (3/3项有官方数据)

👉 **三件齐了，要直接下单吗？**
```

---

## 🛡️ 两道门（合规底线）

```text
门 1（只读）：抽盒 -> 展示真实价格 -> 允许 calculate-price 算总价
门 2（写入）：create-order 必须满足 ①用户说下单 + ②复述商品及金额 + ③用户确认
```
**默认结束语永远是“要下单吗？”，绝不是“已为您下单”。**

---

## 🚫 禁忌清单
- ❌ 绝不在用户说“抽一个”时反问“自取还是外送？”
- ❌ 绝不输出“以下是 5 个选项请选择”
- ❌ 绝不用臆造的商品替代 MCP 真实菜单
- ❌ 绝不调用冗余的 `now-time-info` 接口

---

## 📚 细节索引
- 查阅 61 款在售美食清单与属性：`references/food-catalog.md`
- 查阅全部内置卡面与动图映射：`references/card-gallery.md`
- MCP 接口调用规范与踩坑注意：`references/mcp-tools.md`
