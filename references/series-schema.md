# 系列文件 schema（怎么加一个新系列）

改 `data/series.json` 即可，**不需要改代码**。

## 字段

```json
{
  "id": "chicken",                  // 唯一，命令行 --series 用这个
  "name": "脆鸡江湖",                // 展示名，必须原创，不得与官方产品名/活动名相同
  "code": "CH",                      // 编号前缀，生成 CH-07/12
  "season": "S1",
  "tagline": "咔嚓声，是开箱的预告",   // 卡面副标题，≤14 字
  "availableWindow": ["05:00", "10:30"],  // 可选，供应时段（左闭右开，支持跨零点如 21:00-05:00）
  "palette": { "base": "#D2461F", "accent": "#F5A623", "glow": "#FFB03A" },
  "match": {
    "categories": ["炸鸡", "蘸酱炸鸡", "鸡肉汉堡卷"],  // 归一化后的分类名，子串匹配
    "kinds": ["drink"],                              // 可选，硬条件：只取这些品类
    "tagsAny": ["上新"],                              // 可选，命中任一标签即纳入
    "excludeNameKeywords": ["套餐", "件套"],           // 名称包含即剔除
    "excludeTags": ["麦金卡"]                          // 标签命中即剔除
  },
  "widen": { "kinds": ["combo"] },   // 可选，池子不足 minPoolSize 时并入同类，标注"跨系列"
  "pinned": [
    { "productCode": "1440", "rarity": "SSR", "title": "图腾·麦辣鸡腿堡",
      "copy": "辣得有分寸。江湖规矩，先脆后香。" }
  ],
  "minPoolSize": 4
}
```

## 时段限定（`availableWindow`）

早餐系列必须写，否则半夜也能抽出早餐。

```json
"availableWindow": ["05:00", "10:30"]
```

- 左闭右开：`05:00` 起，`10:30` 止（10:30 整已经不供应）。
- 跨零点写成 `["21:00", "05:00"]`，引擎按"start > end 即跨天"处理。
- 未覆盖当前时刻时，引擎返回 `reason: "series_unavailable"` 并附当前可用的其它系列，
  **不会**替你绕过时段。老字段 `availableHours: [5, 11]` 仍兼容，但新系列请用 `availableWindow`。

## 池子不足时的 `widen`

某门店可能只上了 1 个拼盘，导致「分享派对」只有 1 张卡。声明 `widen` 后，
当 `可用餐品 < minPoolSize` 时，引擎会把匹配 `widen` 规则的商品并入，并在 `warnings` 写"跨系列"。

```json
"widen": { "kinds": ["combo"] }
```

**刻意不默认开启**：并池会让"系列"名不副实。只有语义确实相近的系列才加：
分享派对 → 其它套餐、随心搭子 → 其它套餐。早餐**永远不要**加 widen。

## 匹配逻辑（按顺序）

```
1. kinds 存在 → 商品 kind 必须在 kinds 内（硬条件）
2. categories 存在 → 商品的任一 category 命中任一 category 关键词（子串），或命中 tagsAny
3. categories 与 kinds 都为空 → 必须命中 tagsAny
4. 命中 excludeTags / excludeNameKeywords → 剔除
5. 排序：price desc, productCode asc（保证编号稳定）
```

`category` 是**归一化后**的，例如：
`巨无霸牛鱼肉堡`、`安格斯MAX厚牛堡`、`炸鸡`、`蘸酱炸鸡`、`鸡肉汉堡卷`、`小食甜品其他`、
`麦咖啡`、`随心配1+1`、`大堡口福单人餐`、`500大卡套餐`、`小食拼盘多人餐`、`开心乐园`、`饮品`。

## 稀有度判定（`data/rarity.json`，全局规则）

```
pinned 白名单 → SR（tags 含"上新"）→ R（tags 命中 或 折扣比≥1.4 或 价格≥系列 P70）→ N
```

`pricePercentileGte` 的作用：保证任何系列都有"值得追"的档位，不依赖人工逐个标注。
一个池子里大约 30% 会落到 R。

## 新增系列的检查清单

- [ ] `id` 不重复，`code` 是 2 个大写字母
- [ ] `name` 是原创中文，且**不等于**任何麦当劳官方产品名/活动名
- [ ] `tagline` ≤14 字，不出现"官方/限量/联名"
- [ ] 时段限定系列必须写 `availableWindow`，并用 `--now 08:00` / `--now 20:00` 各验一次
- [ ] 至少 1 个 `pinned`（图腾款），并写 `copy`
- [ ] 跑 `--odds` 确认池容量 ≥ `minPoolSize`，且四档不空（SR 为空是允许的）
- [ ] 跑 `--simulate 5000` 确认分布正常
- [ ] 跑 `scripts/make_assets.py` 重建卡面，确认新系列图正常
- [ ] 更新 `docs/CONTENT-SPEC.md` 的系列矩阵表
