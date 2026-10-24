# MCP 工具契约与踩坑清单

> 所有内容来自 2026-10-24 对 `https://mcp.mcd.cn` 的真实调用回放（storeCode=1450713）。
> 参数以实际 schema 为准；本文档只记录"文档没写、但会踩"的部分。

## 调用链

```
now-time-info → query-nearby-stores → query-meals → list-nutrition-foods
                                            ↓
                                    draw.py（本地）
                                            ↓
                          calculate-price（只读） → create-order（需二次确认）
```

## 参数铁律

| beType | orderType | beCode | 说明 |
|---|---|---|---|
| 1 到店自取 | 1 | **不传** | 传了会报错。这是最高频错误 |
| 5 得来速 | 1 | 必传（来自 query-nearby-stores） | |
| 2 麦乐送 | 2 | 必传（来自 delivery-query-stores） | 还需 `addressId` |
| 6 企业团餐 | 2 | 必传 | 还需 `gmServiceCode` |

- `reservationDate` 只在预约时传，格式 `yyyy-MM-dd HH:mm`；非预约传了报错。
- `create-order` 的 `takeWayCode` **只能**来自 `calculate-price` 的 `data.takeWayList[].code`。
- **单位**：`query-meals` 的 `currentPrice` 是**元**字符串；`calculate-price` 返回**分**。混用是第二高频 bug。

## query-meals 的六个坑

1. **分类名带换行符**：`"巨无霸\n牛鱼肉堡"`、`"小食拼盘\n/多人餐"`、`"随心配\n1+1"`、`"500\n大卡套餐"`。
   → 必须 `replace("\n","").replace("/","")`，否则系列匹配全部失效。
2. **同一 code 出现在多个分类下**：`巨无霸`(1100) 同时在「人气热卖」和「巨无霸牛鱼肉堡」。
   → 按 code 去重时**必须合并 categories 与 tags**。若"先到先得"，巨无霸会因为先出现在「人气热卖」而被
     牛堡宇宙漏掉——图腾款消失，且不会报错。这是本项目真实踩过的坑。
3. **`tags` 字段可能不存在**，不能假定是 `[]`。
4. **菜单里混着非食品**：`麦当劳限定丝巾`、`旋旋水手帽`、`按摩捶痒痒挠`、`联名复古棒球帽`，
   以及 3 元的 `韩式烟熏芝士风味酱` / `北美招牌牧场酱`。→ 必须过滤，否则用户会抽到一条丝巾。
5. **图片两种情况**：列表是 `_320.png`，少数是 `_320.gif`；详情是 `_600.png`。
   → 不要盲目把 `_320` 替换成 `_600`，部分 gif 没有 600 版。卡面用 320 足够。
6. **同 SKU 有单品与套餐两条记录**（`巨无霸` 1100 / `巨无霸三件套` 9900005466）。
   → 用 `kind` 区分，端盒时排除重复主体。

## list-nutrition-foods 的解析

`data` 是**字符串**，不是 JSON：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  芝士安格斯厚牛堡,能量约鲈鱼1条,2914,696,32,44,43,897,150
```

- 按 `:` 后切行，每行按 `,` 切 9 段，字段顺序固定。
- `nutritionDescription` 为 `null` 时置空；有值时（如"能量约猕猴桃2个"）**原样保留**，这是官方原话，
  比自己编比喻既安全又好用。
- 名称会重复（`纯牛奶（盒装）`、`小杯玉米杯` 各两条）→ `setdefault` 保留首条。
- **匹配率天然不满**：套餐名（`巨无霸三件套`）在表里不存在。→ 明确"套餐卡无属性"，
  **不要**做模糊匹配（会把 `麦辣鸡翅` 匹配到 `麦辣鸡翅-2块`，热量是错的）。

## 错误码

| code | 含义 | 处理 |
|---|---|---|
| 401 | Token 无效/过期/未提供 | 提示重新申请，附配置片段，**不重试** |
| 429 | 超过 600 次/分钟 | 退避 1s→2s→4s，最多 2 次；仍失败用缓存菜单 |

## 活动日历（campaign-calendar）

只能用于**文案灵感与主题命名**，**不得**作为商品来源。
理由：活动 ≠ 在售，活动商品未必在当前门店可售，写进候选池会导致"抽到了买不了"。

## 调试点

```bash
# 直接看某门店菜单结构
curl -s https://mcp.mcd.cn -H "Authorization: Bearer $MCD_MCP_TOKEN" ...   # 或直接用 MCP Client
```

把 `query-meals` 的**原始返回**存成 `pool.json`，不要自己重组结构——`draw.py` 需要原始
`data.categories` / `data.meals` 才能复现同一套编号。
