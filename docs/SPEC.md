# 麦泡泡 PopMc · 开发规格说明书（SPEC）

> 版本：v1.1 · 2026-10-24
> 面向对象：直接照此实现即可交付。所有字段名、参数约束均来自 2026-10-24 对麦当劳 MCP 的真实调用回放。
>
> ⚠️ **实现基线**：[`DESIGN-DECISIONS.md`](./DESIGN-DECISIONS.md)。本文档与它冲突时以后者为准。
> 代码已在 `skill/popmc/scripts/` 落地，`draw.py` 的输出结构即事实标准。

---

## 1. 架构总览

```
┌───────────────────────────────────────────────────────────────┐
│ WorkBuddy / 任意 MCP Client                                     │
│  用户：「不知道吃什么，抽一个」                                   │
└───────────────────────────┬───────────────────────────────────┘
                            │ SKILL.md（渐进式披露：只在需要时读 references/）
┌───────────────────────────▼───────────────────────────────────┐
│ 麦泡泡 Skill 层                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ 编排器       │  │ 抽盒引擎      │  │ 卡面渲染器          │    │
│  │ (LLM+SKILL) │→│ draw.py      │→│ render_card.py     │    │
│  └─────────────┘  └──────────────┘  └────────────────────┘    │
│         │                 │                    │              │
│         │          ┌──────▼───────┐     ┌──────▼───────┐      │
│         │          │ 系列定义      │     │ 收集册        │      │
│         │          │ data/*.json  │     │ collection.json│     │
│         │          └──────────────┘     └──────────────┘      │
└─────────┼─────────────────────────────────────────────────────┘
          │ MCP (Streamable HTTP, https://mcp.mcd.cn)
┌─────────▼─────────────────────────────────────────────────────┐
│ 麦当劳 MCP Server                                               │
│  query-nearby-stores → query-meals → calculate-price →         │
│  create-order ；list-nutrition-foods ；query-meal-detail        │
└───────────────────────────────────────────────────────────────┘
```

**设计原则**

1. **确定性与随机性分离**：随机只在 `draw.py` 里发生，且是**种子可复现**的；LLM 绝不参与随机决策（否则不可复现、不可审计）。
2. **数据与玩法分离**：系列规则、稀有度规则、文案模板全部在 `data/*.json` 与 `references/*.md`，改内容不改代码。
3. **降级优先**：任一 MCP 失败都必须产出可用结果，不允许抛错到用户面前。

---

## 2. 仓库与 Skill 包结构

```text
mcbox/                                  # 参赛仓库根
├── README.md                           # 必须（介绍/安装/示例/目标用户）
├── CONTEST_DECLARATION.md              # 必须（官方原文，一字不改）
├── MCP_INTEGRATION.md                  # 必须（Server/Tool/流程/业务价值）
├── mcp-config.example.json             # 必须（仅环境变量占位符）
├── workbuddy.md                        # WorkBuddy 专项奖励（对话上下文导出）
├── LICENSE                             # MIT
├── docs/
│   ├── PRD.md
│   ├── SPEC.md                         # 本文件
│   └── CONTENT-SPEC.md                 # 系列矩阵 / 文案模板 / 视觉规范
└── skill/
    └── mcbox/
        ├── SKILL.md                    # 技能主文件（<200 行，渐进式披露）
        ├── references/
        │   ├── mcp-tools.md            # 工具契约与踩坑清单
        │   ├── series-schema.md        # 系列文件 schema
        │   ├── copywriting.md          # 拆盒文案库 + 禁忌词
        │   └── compliance.md           # 合规检查清单
        ├── scripts/
        │   ├── draw.py                 # 抽盒引擎（单抽 / 端盒 / 概率 / 模拟）
        │   ├── render_card.py          # 卡面 SVG 渲染（单卡 + 端盒版式 + 外盒）
        │   ├── animate_unbox.py        # 泡泡玛特开盒动效生成器（逐帧渲染与 GIF 合成）
        │   ├── collection.py           # 收集册读写 / 人格卡
        │   └── make_assets.py          # 一键重建卡面、动图与预览页
        └── data/
            ├── series.json             # 系列定义（7 个系列，含时段限定）
            ├── rarity.json             # 稀有度权重与保底
            └── moods.json              # 情绪 → 系列权重 / 文案语气
```

> **为什么脚本用 Python 标准库**：零依赖意味着任何人 clone 下来就能跑，评审和用户不用 `pip install`。所有 I/O 用 `json`、随机用 `hashlib`+`hmac`，不引入 numpy。

---

## 3. 数据模型

### 3.1 系列定义 `data/series.json`

```json
{
  "schemaVersion": "1.0.0",
  "series": [
    {
      "id": "beef-universe",
      "name": "牛堡宇宙",
      "code": "BU",
      "season": "S1",
      "palette": { "base": "#8B1E2D", "accent": "#F2C14E", "glow": "#FF6B4A" },
      "match": {
        "categories": ["巨无霸牛鱼肉堡", "安格斯MAX厚牛堡"],
        "tagsAny": ["100%纯牛肉", "100%安格斯牛肉", "麦香鱼系列"],
        "excludeNameKeywords": ["套餐", "四件套", "三件套", "随心选", "随心配"],
        "excludeTags": ["麦金卡"]
      },
      "pinned": [{ "productCode": "1100", "rarity": "SSR", "title": "图腾·巨无霸" }],
      "minPoolSize": 5
    }
  ]
}
```

**要点**

- `categories` 必须使用**归一化后**的分类名（见 §4.3 的 `\n` 处理）。
- `pinned` 是唯一的人工干预点，用于保证"有一个值得追的目标"。
- `minPoolSize`：池容量不足时触发并池或降级（FR-13）。

### 3.2 稀有度 `data/rarity.json`

```json
{
  "tiers": [
    { "id": "N",   "label": "常驻", "weight": 70.0,  "frame": "plain" },
    { "id": "R",   "label": "人气", "weight": 22.0,  "frame": "silver" },
    { "id": "SR",  "label": "当期", "weight": 6.5,   "frame": "gold" },
    { "id": "SSR", "label": "图腾", "weight": 1.5,   "frame": "prism" }
  ],
  "pity": { "R_or_above_every": 10, "SSR_every": 50 },
  "rules": {
    "R":  { "tagsAny": ["爆款", "人气", "经典", "100%纯牛肉"], "discountRatioGte": 1.4 },
    "SR": { "tagsAny": ["上新"] }
  }
}
```

判定顺序（短路）：`pinned` → `SR`（tags 含上新）→ `R`（tags 命中或折扣比 ≥1.4）→ `N`。
> 折扣比 = `originalPrice / currentPrice`（都是**元**字符串，需转 float）。

### 3.3 卡片产出：三层结构（最终形态）

`draw.py` 的 stdout 就是这张卡，**三层物理隔离**，任何字段放错层视为 bug（见 DESIGN-DECISIONS D1）。

```json
{
  "ok": true,
  "series": { "id": "chicken", "name": "脆鸡江湖", "code": "CH", "season": "S1",
              "tagline": "咔嚓声，是开箱的预告",
              "palette": { "base": "#D2461F", "accent": "#F5A623", "glow": "#FFB03A" },
              "disclaimer": "系列为本项目原创体验主题，非麦当劳官方系列。" },

  "fact": {
    "productCode": "521952",
    "name": "龙焰鸡腿堡",
    "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_521952_320.png",
    "price": 15.9,
    "originalPrice": 24.0,
    "saving": 8.1,
    "kind": "main",
    "category": "鸡肉汉堡卷",
    "tags": ["上新", "韩式辣椒黄油风味"],
    "nutrition": null,
    "nutritionNote": "",
    "nutritionMatch": null,
    "source": "mcd-mcp.query-meals@2026-10-24 18:22:17"
  },

  "experience": {
    "cardNo": "CH-06/12",
    "seriesCode": "CH",
    "rarity": "SR",
    "rarityLabel": "当期",
    "pinnedTitle": "",
    "flavorText": "韩式辣椒黄油风味。这批里有它。",
    "tone": "soft",
    "rarityNote": "分级是本项目玩法设定，仅影响卡面视觉与文案，不代表官方发行量、限量或稀缺性。"
  },

  "meta": {
    "drawId": "20261024-7fc994-07",
    "seedHash": "b32859442ad40101dd0b1cb6f7976d0c",
    "poolFingerprint": "da4c34d407233e8a",
    "poolSize": 12,
    "mode": "default",
    "tier": "SR",
    "nonce": "7",
    "dayKey": "2026-10-24",
    "engine": "mcbox-draw/1.0",
    "storeCode": "1450713",
    "queriedAt": "2026-10-24 18:22:17"
  },

  "warnings": [],
  "disclaimer": "非官方产品 · 参赛作品。商品信息以麦当劳官方渠道实时结果为准。"
}
```

**字段归属规则**

| 层 | 只能来自 | 缺失时 |
|---|---|---|
| `fact` | MCP 返回（`query-meals` / `list-nutrition-foods`） | `null`，**不补齐**、不估算 |
| `experience` | 本项目 `series.json` / `rarity.json` / `moods.json` / `TEMPLATES` | 永不缺失，必须有默认值 |
| `meta` | 引擎运行态（种子、指纹、模式） | 永不缺失 |

`kind` 枚举：`main`（主食/汉堡）/ `combo`（套餐，`nutrition` 恒为 `null`）/ `side` / `drink` / `dessert`。

**失败输出**（`ok:false`，exit code 2）：

```json
{
  "ok": false,
  "reason": "budget_too_low",
  "detail": "在预算 ¥10 与排除条件（无）下，系列「牛堡宇宙」没有符合的餐品。该系列当前最便宜的几项：麦香鱼¥22.5, …",
  "relax": [{ "action": "raise_budget", "to": 22.5 }, { "action": "drop_excludes" },
            { "action": "switch_series", "to": "combo" }],
  "disclaimer": "…"
}
```

`reason` 枚举：`no_store` / `store_closed` / `empty_menu` / `budget_too_low` / `all_excluded` /
`series_unavailable` / `series_not_found` / `auth_failed` / `rate_limited`。

### 3.4 收集册 `~/.popmc/collection.json`

```json
{
  "version": 1,
  "counters": { "sinceR": 3, "sinceSSR": 12, "totalDraws": 47, "dailyNonce": { "2026-10-24": 5 } },
  "owned": {
    "chicken": { "9900016073": { "firstAt": "2026-10-24T18:40:11+08:00", "count": 1 } }
  },
  "blacklist": ["香菜", "牛肉"],
  "persona": { "beef": 21, "fried": 14, "sweet": 8, "coffee": 4 }
}
```

> 只存商品码与时间，**不存**手机号、地址、Token（NFR-05）。

---

## 4. MCP 调用契约（含真实踩坑）

### 4.1 调用链（到店自取，P0 主链路）

| 步骤 | Tool | 关键参数 | 取什么 |
|---|---|---|---|
| 1 | `now-time-info` | — | 当前时段（用于"早/午/下午茶/夜宵"分桶） |
| 2 | `query-nearby-stores` | `beType=1`, `searchType=2`, `city`, `keyword` | `storeCode`（到店场景无 `beCode`） |
| 3 | `query-meals` | `storeCode`, `orderType=1`, `beType=1` | `categories[]` / `meals{}` |
| 4 | `list-nutrition-foods` | — | 营养表（每进程只拉 1 次，缓存） |
| 5 | `calculate-price` | `storeCode`, `orderType=1`, `beType=1`, `items[]` | 金额（**单位：分**）、`takeWayList[].code` |
| 6 | `create-order` | 同上 + `takeWayCode` + `items[]` | 订单号、支付链接 |

### 4.2 参数传递铁律

- `beType=1`（到店自取）→ `orderType=1`，**绝对不要传 `beCode`**，传了会报错。
- `beType=5`（得来速）→ `orderType=1`，**必须**传 `beCode`（来自 `query-nearby-stores`）。
- `beType=2`（麦乐送）/ `beType=6`（团餐）→ `orderType=2`，必须传 `beCode`（来自 `delivery-query-stores`）。
- 预约场景才传 `reservationDate`，格式 `yyyy-MM-dd HH:mm`；非预约传了会报错。
- `create-order` 的 `takeWayCode` **只能**来自 `calculate-price` 返回的 `data.takeWayList[].code`，不可自行编造。
- 金额：`calculate-price` 返回**分**，展示前 `/100`；`query-meals` 的 `currentPrice` 是**元**字符串。两套单位混用是最高频 bug。

### 4.3 `query-meals` 返回的真实坑（必读）

1. **分类名带换行符**：实际值形如 `"巨无霸\n牛鱼肉堡"`、`"小食拼盘\n/多人餐"`、`"随心配\n1+1"`、`"500\n大卡套餐"`。
   必须归一化：`name.replace("\n", "").replace("/", "").replace("™", "").strip()`。
2. **`meals` 是 map，`categories[].meals` 只给 code + tags**：名称/价格/图片都在 `data.meals[code]` 里，需要 join。同一个 code 会出现在多个分类下 → 建池时按 code 去重。
3. **`tags` 可能缺失**（字段不存在），不能假定为 `[]`。
4. **菜单里混着非食品**：`麦当劳限定丝巾`、`联名复古棒球帽`、`按摩捶痒痒挠`、`旋旋水手帽`，以及 3 元的`韩式烟熏芝士风味酱`、`北美招牌牧场酱`（酱料不是一餐）。必须过滤，否则用户会"抽到一条丝巾"。
5. **图片有两种规格**：列表是 `_320.png`（少数是 `_320.gif`），详情是 `_600.png`。卡面用 320 即可，**不要**盲目把 `_320` 替换成 `_600`（部分 `.gif` 无 600 版）。
6. **同一 SKU 存在套餐/单品两条记录**（`巨无霸` 1100 vs `巨无霸三件套` 9900005466），建池时按 `kind` 分开，避免"端盒"里出现两个巨无霸。

### 4.4 `list-nutrition-foods` 的解析（坑中之坑）

返回 `data` 是**字符串**，不是 JSON：

```text
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  ...
  芝士安格斯厚牛堡,能量约鲈鱼1条,2914,696,32,44,43,897,150
```

解析规则：
- 用 `:` 后换行切分，每行按 `,` 切 9 段；首行 `[160]` 是条数，可忽略。
- 字段顺序固定：`productName, nutritionDescription, energyKj, energyKcal, protein, fat, carbohydrate, sodium, calcium`。
- `nutritionDescription` 为 `null` 时置空；有值时即"能量约猕猴桃2个"，直接用作 `statsNote`（这是官方原话，合规安全）。
- **名称去重**：`纯牛奶（盒装）`、`小杯玉米杯` 各出现两次，`setdefault` 保留首条。
- **匹配率天然不满**：套餐名（`巨无霸三件套`）在营养表里不存在。→ 设计上明确"套餐卡无属性，只标 `combo`"，不要模糊匹配（用模糊匹配会把"麦辣鸡腿堡"匹配到"麦辣鸡腿堡三件套"上，数据是错的）。

### 4.4.1 唯一规格后缀映射（v1.1 新增，解决"菜单名 ≠ 营养表名"）

实测：菜单叫 `可乐` / `雪碧` / `卡布奇诺`，营养表叫 `可乐中杯` / `雪碧中杯` / `卡布奇诺中杯`。
纯精确匹配会让饮料、小食卡片大面积"无属性"（实测饮品覆盖率 4/13）。

**规则：只接受"唯一 + 后缀只是规格/包装"的映射**，其余一律不匹配。

```
1. 归一化后精确相等                      → basis = "exact"
2. 营养表名以菜单名开头，且候选唯一，
   且多出来的后缀 ∈ {中杯,大杯,小杯,中,大,小,标准杯,（中杯）,（大杯）}  → basis = "suffix"
3. 菜单名以营养表名开头，且候选唯一，
   且多出来的后缀 ∈ {盒装,（盒装）,(盒装),瓶装,罐装}                → basis = "suffix"
4. 其他情况（含多候选、含非规格后缀）    → 不匹配，nutrition = null
```

反例，必须继续拒绝：
- `麦乐鸡` → `麦乐鸡4块` / `麦乐鸡5块`（多候选，份量不同）→ **不匹配**
- `薯条` → `中薯条` / `大薯条`（多候选，且杯型决定热量）→ **不匹配**
- `麦辣鸡腿堡` → `麦辣鸡腿堡三件套`（后缀不是规格，是另一个商品）→ **不匹配**

匹配成功时 `fact.nutritionMatch = {basis, officialName}`，卡面必须写出
`营养按官方营养表「可乐中杯」条目`，让用户可核对。**这是"可验证的同一商品"，不是相似度猜测。**

### 4.5 错误码与降级

| 场景 | 表现 | 降级动作 |
|---|---|---|
| 401 | Token 无效/过期 | 提示到控制台重新申请，附配置片段；**不重试** |
| 429 | >600 次/分钟 | 指数退避 1s→2s→4s，最多 2 次；仍失败则用缓存菜单 |
| 菜单为空 / 门店打烊 | `meals` 为空 | 换同城其它门店；仍空则提示"这家店现在没有可抽的" |
| 系列不在供应时段 | `availableWindow` 未覆盖当前时刻 | 返回 `series_unavailable`，附 `pick_other_series` 候选；**不得**绕过时段硬抽 |
| 某系列池 < `minPoolSize` | — | 只有该系列在 `series.json` 声明了 `widen` 才扩展同类池，并在 `warnings` 标注"跨系列"；否则只告警「可用餐品偏少，建议换系列」。**宁缺毋错，不自动并池** |
| 营养表缺失该商品 | — | `nutrition=null`，卡面显示"官方表未收录"，不编造 |

### 4.5.1 空池 triple-check（v1.1 修复）

原来只要筛完为空就报 `budget_too_low`，把"这个系列本店根本没有"也说成"你预算太低"，属于误导。
现在按三段分别判定：

```
raw 为空            → series_unavailable（本店没上 / 不在时段）
afterExcl 为空      → all_excluded（是你排除掉的）
cand 为空           → budget_too_low（预算卡住，附最便宜的三项）
```

---

## 5. 抽盒引擎规格（`scripts/draw.py`）

### 5.1 随机性与可复现

```python
seed_material = f"{day_key}|{nonce}|{series_id}|{pool_fingerprint}"
seed_hash = hmac.new(SECRET.encode(), seed_material.encode(), sha256).hexdigest()
```

- `day_key` = `YYYY-MM-DD`（本地时区）
- `nonce` = 当日该系列已抽次数（持久化递增，保证重抽必变，但可复现）
- `pool_fingerprint` = 池内 productCode 排序后拼接的 sha256 前 16 位（菜单变了，结果自然变）
- `SECRET` = 环境变量 `MCBOX_SECRET`，缺省用固定字符串（保证开箱即用；生产建议自定义）

> `seedHash` 随卡片返回，用户可截图"验真"；社区可复算，这是"抽卡不黑箱"的技术证据。
> **不使用 `random.seed()`**：Python 的 `random` 实现跨版本可能变，`hmac` 结果永远稳定。

### 5.2 抽取算法

```
draw(pool, tiers, counters):
  1. 若 counters.sinceSSR + 1 >= pity.SSR_every        → 强制 SSR
  2. 否则若 counters.sinceR   + 1 >= pity.R_or_above   → 在 R/SR/SSR 池中按权重抽
  3. 否则                                               → 按 tiers.weight 抽等级
  4. 该等级池为空 → 逐级回落（SSR→SR→R→N）
  5. 在命中等级的池内均匀抽 1 个：idx = H(seed, tier)[0:8] % len(tier_pool)
  6. 更新 counters
```

**注意**：先抽等级再抽卡，意味着每张卡的真实概率 = `tier.weight / len(tier_pool)`。必须由 `--odds` 子命令算出来给用户看（合规要求）。

### 5.3 CLI 契约

```bash
python3 draw.py --pool pool.json --series chicken [--budget 30] [--mood "累"] [--commit]
python3 draw.py --pool pool.json --box --budget 45        # 端盒
python3 draw.py --pool pool.json --suggest-series --mood "累"
python3 draw.py --pool pool.json --odds                   # 每张卡的真实概率（含保底实测）
python3 draw.py --pool pool.json --simulate 10000         # 蒙特卡洛自检
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--pool` | 必填 | `query-meals` 原始返回 |
| `--series` | 空 | 空则按情绪 + 时段加权抽样 |
| `--budget` | `0` | 单品上限；`--box` 时为**整盒**上限 |
| `--exclude` / `--remember-exclude` | 空 | 前者本次生效，后者写入 `state.blacklist` 长期生效 |
| `--nonce` | 空 | **空则按本地当日计数自增**（v1.1）。只有复现时才手动指定 |
| `--now` | 本机时间 | `HH:MM`，用于时段闸门与测试 |
| `--state` | `~/.popmc/collection.json` | 保底计数 / 收藏 / 排除词 / 最近抽到 |
| `--commit` | 关 | 关时只推进 nonce 与保底计数，不写收藏 |
| `--mode` | `default` | `fair` = 候选内均匀，无等级 |
| `--split-dir` | 空 | 端盒时把每件另存为单卡 JSON，便于逐张渲染 |

输入 `pool.json`（由编排层用 `query-meals` 结果生成）：

```json
{ "storeCode": "1450713", "datetime": "...", "data": { "categories": [...], "meals": {...} } }
```

输出 stdout 为单个 JSON；stderr 只放调试信息。**stdout 必须是纯 JSON**，便于 LLM 解析。

### 5.3.1 连续抽盒去重（v1.1 修复）

原来 `nonce` 完全靠调用方手动递增，LLM 一旦忘记，"再抽一次"会拿到**一模一样的卡**；
且即便 nonce 变了，等级池里同一张卡仍会被反复命中（实测 5 连抽出现 3 次同款）。

修复两处：
1. `nonce` 由 `state.counters.dailyNonce[day]` 自增，同一台机器同一天必然递增；
2. `state.recent` 保存最近 4 个 `productCode`，抽卡时先避开；
   若该等级已全被避开，则退到**整池**里没抽过的卡（宁可变档也不重复），整池都抽过才允许重复。

### 5.4 端盒（FR-04，v1.1 已实现）

```
端盒(budget):
  1. 主食池 = 系列内 main/combo（系列没有主食时退到全店主食），先过预算与排除
  2. 预留 = 最便宜小食 + 最便宜饮料；主食只在 (price + 预留 ≤ budget) 里抽
     全都装不下 → 退到最便宜主食，结构降级为 1 件
  3. 小食池 = 全店 side ∩ (price + 最便宜饮料 ≤ 剩余预算)
  4. 饮料池 = 全店 drink ∩ (price ≤ 抽完小食后的剩余)
  5. 任一段抽不出就降级（3 件→2 件→1 件），写进 warnings，不超预算
  6. 总价 = 单品现价累加（四舍五入到分）；总热量只累加有官方营养数据的项
```

输出 `box` 段：

```json
{
  "box": {
    "boxId": "20261024-CH-B01",
    "structure": "主食+小食+饮料",
    "slots": [ { "fact": {...}, "experience": { "slot": "main", "slotLabel": "主食", ... } } ],
    "totalPrice": 38.5, "totalOriginalPrice": 38.5, "totalSaving": 0,
    "totalKcal": 369, "kcalCovered": "2/3",
    "note": "组合总价为本项目按单品现价累加的结果，实际金额以下单页为准。"
  }
}
```

硬规则：
- **总价永远 ≤ 预算**（有预算时），降级结构而不是超预算。
- 盒内三件 `productCode` 互不相同。
- 主食用 `slot=main` 抽种子，小食/饮料用 `slot=side/drink`，三者独立可复现。
- 小食/饮料文案**不得**沿用主食系列的钩子（否则清水会被写成"咔嚓一声"）。
- 端盒不新增任何"套餐优惠价"，只做现价累加——**打折是官方的事，不是本项目编的**。

去重、预算、结构三件事都在引擎里做，LLM 只负责表达。

---

## 6. 卡面渲染规格（`scripts/render_card.py`）

输出 `SVG`（600×840，2:2.8 卡牌比例），图层自底向上：

| 层 | 内容 | 数据来源 |
|---|---|---|
| L0 | 背景渐变（系列 `palette.base`→深色） | series.json |
| L1 | 斜向条纹 / 噪点纹理（`<pattern>` 生成） | 程序化 |
| L2 | 稀有度光框（N 无/R 银/SR 金+流光/SSR 虹彩+粒子） | rarity.json |
| L3 | 商品图（官方 CDN，`<image>` + 圆角裁切 + 白色底衬托） | MCP `image` |
| L4 | 商品名（粗体，自动缩字号）+ 英文系列名 | Card.name |
| L5 | 属性条（能量/蛋白质/脂肪/碳水），无数据时显示"组合 · 含 N 件" | nutrition |
| L6 | 编号 `CH-07/14` + 稀有度徽章 + 底部声明一行 | Card |
| L7 | 底部强制水印：`非官方产品 · 参赛作品` | 固定文案 |

**合规硬约束**

- 禁止使用任何麦当劳官方包装设计稿、Logo 组合、"金拱门"图形作为设计元素；卡片**只**使用 MCP 返回的商品实拍图（这属于官方数据的一部分）。
- 卡片不得出现"官方""联名""限定发售"等暗示授权的词。
- 生成字体用系统字体栈，不内嵌商用字体文件（避免字体版权）。

**工程硬约束：商品图必须内联**

`<image href="https://menu-img.mcd.cn/...">` 这种写法在被 `<img src="../assets/cards/chicken-SR.svg">` 引用时，
浏览器会拒绝加载外部资源，结果是**一张裂图**（GitHub README 与 HTML 预览页都是这种引用方式）。

因此渲染器默认把图片下载并内联为 `data:image/png;base64,`：

| 项 | 行为 |
|---|---|
| 缓存 | `~/.popmc/imgcache/<sha1(url)>.<ext>`，二次渲染 <10ms |
| 超时 | 6s；失败**不中断抽盒**，回落原始 URL + stderr 警告 |
| 关闭 | `--no-embed` |
| 图片内容 | 官方 CDN 原图，**零加工**，只换传输方式 |
| 体积 | 单卡 ~50-100KB（原 ~6KB） |

---

## 7. 编排层（SKILL.md）设计

SKILL.md 只做三件事，其余全部下沉到 `references/`：

1. **触发条件**：用户表达"不知道吃什么 / 随便 / 抽一个 / 盲盒 / 拆盒 / 图鉴"时进入。
2. **六步主流程**（固定顺序，不可跳步）：

```
① 定场景 → ② 定门店 → ③ 拉池 → ④ 拆盒 → ⑤ 落卡 → ⑥ 成单
```

3. **输出格式契约**：拆盒播报必须是 4 段（洗牌一句 → 揭晓一句 → 卡面 → 结论+下单引导一句），禁止输出"以下是 5 个选项"。

**渐进式披露表**

| 何时读 | 文件 |
|---|---|
| 需要调用 MCP 前 | `references/mcp-tools.md` |
| 需要新增/修改系列 | `references/series-schema.md` |
| 生成 `flavorText` 时 | `references/copywriting.md` |
| 输出前自检 | `references/compliance.md` |
| 用户问"概率/保底" | `references/compliance.md` + `draw.py --odds` |

---

## 8. 测试计划

| 类型 | 用例 | 通过标准 |
|---|---|---|
| 单元 | `normalize_category("巨无霸\n牛鱼肉堡")` | → `巨无霸牛鱼肉堡` |
| 单元 | 折扣比计算（"47.5"/"26.9"） | → 1.766，判 R |
| 单元 | 非食品过滤（丝巾/棒球帽/酱料） | 全部 `is_food=False` |
| 单元 | 营养表解析 | 字段齐全、去重、官方话术原样保留 |
| 单元 | 规格后缀映射 | `可乐→可乐中杯` 命中；`麦乐鸡`/`薯条` 多候选时**不**命中 |
| 单元 | 时段闸门 | 早餐系列 18:39 不可用、08:00 可用、跨零点窗口正确 |
| 单元 | 空池三段判定 | raw/afterExcl/cand 分别产生三种 `reason` |
| 单元 | 端盒 | 3 件不重样、总价 ≤ 预算、总价=分项和、小预算降级不超支 |
| 单元 | nonce 自增 / 排除词记忆 / 坏 state 不崩 | 全部通过 |
| 统计 | `--simulate 10000` | 各档实际频率与公示偏差 <2% |
| 统计 | `--odds` | 输出的"含保底实际"与模拟一致（SSR ≈2.8%，非裸权重 1.5%） |
| 复现 | 同 seed 连跑 2 次 | `drawId` 与 `cardNo` 完全一致 |
| 复现 | 连抽 10 次 | 相邻两次不重复同一商品 |
| 集成 | 真门店全链路 | 抽中 code 必在 `query-meals` 返回内 |
| 异常 | 伪造 401 / 429 / 空菜单 | 三条降级文案均可读、不中断 |
| 合规 | 扫全仓库 | 无 Token 明文、无真实手机号、无"官方联名"字样 |

当前：`python3 -m unittest discover -s tests` → **44 项全绿**。

---

## 9. 交付清单（提交前逐项打勾）

- [ ] `README.md` — 含 GIF 演示、安装三步、目标用户、免责声明
- [ ] `CONTEST_DECLARATION.md` — 官方原文，**一个字符都不改**
- [ ] `MCP_INTEGRATION.md` — 列出用到的 6 个 Tool + 调用时序图 + 业务价值
- [ ] `mcp-config.example.json` — `Bearer ${MCD_MCP_TOKEN}`，无真实值
- [ ] `workbuddy.md` — WorkBuddy 对话上下文
- [ ] `LICENSE` — MIT
- [ ] 仓库 **Public**
- [ ] Issue 报名：标题与正文**不换行**，链接**不用 Markdown 语法**
- [ ] 截图/录屏放在 `docs/assets/`，路径相对引用（GitHub 可渲染）

---

## 10. 已知风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 门店实时菜单与营养表名称不匹配 | 部分卡无属性 | 显示"数据待补"，不做模糊匹配（宁缺毋错） |
| 套餐无营养数据占比高 | 卡面属性覆盖率低 | 端盒链路由"套餐卡"承担，属性卡由单品承担，两类卡分工 |
| 29 小时内做不完 | 报名失败 | P0 只保留六步主链路；卡面渲染可先降级为纯 CSS 文本卡 |
| 抽盒品类已有 4 个项目 | 星数难涨 | README 首屏用「抽完就能买」一句话打差异化，对比图只讲自己不讲别人 |
| 盲盒合规解读争议 | 审核风险 | 全链路价格确定、无付费抽奖、概率公示、五处免责声明 |
