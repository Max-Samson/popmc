# MCP 集成说明

## Server

| 项 | 值 |
|---|---|
| 地址 | `https://mcp.mcd.cn` |
| 协议 | Streamable HTTP |
| 鉴权 | `Authorization: Bearer <MCP_TOKEN>`（Token 由使用者自行在 <https://open.mcd.cn/mcp> 申请） |
| 限流 | 600 次/分钟，超限返回 429 |
| 覆盖场景 | 麦乐送点餐、到店取餐、团餐、积分兑换券、活动日历 |

配置见 [`mcp-config.example.json`](mcp-config.example.json)（仅环境变量占位符，无真实凭据）。

## 实际使用的 Tool

| Tool | 在本项目里的用途 | 调用时机 | 是否必需 |
|---|---|---|---|
| `query-nearby-stores` | 拿 `storeCode` | 每次开盒的第 2 步 | 必需 |
| `query-meals` | **构建候选池的唯一来源**（分类、商品码、标签、名称、图片、价格） | 每次开盒的第 3 步 | 必需 |
| `list-nutrition-foods` | 卡面属性 + 官方"能量约…"描述 | 每进程 1 次，缓存 | 必需 |
| `now-time-info` | 判定时段（早餐/午/下午茶/夜宵），控制系列上架 | 每次开盒的第 1 步 | 必需 |
| `calculate-price` | 只读算价，拿应付金额与 `takeWayList[].code` | 用户问"多少钱"/准备下单 | 门 1 |
| `create-order` | 下单 | 用户通过门 2 全部条件后 | 门 2 |
| `query-meal-detail` | 套餐组成（用户点开"里面有什么"时） | 按需 | 可选 |

**明确不用**：`campaign-calendar` 不作为商品来源（活动 ≠ 在售），最多用于主题命名灵感。

## 调用流程

```text
用户：「不知道吃什么」
  │
  ├─ now-time-info                 → 当前时段
  ├─ query-nearby-stores(beType=1) → storeCode
  ├─ query-meals(storeCode,1,1)    → 原始菜单 → 存 /tmp/mcbox_pool.json
  ├─ list-nutrition-foods()        → 营养表 → 存 /tmp/mcbox_nutrition.txt
  │
  ├─ [本地] draw.py                → 建池 / 硬约束过滤 / 加权抽取 / 生成卡片
  ├─ [本地] render_card.py         → SVG 收藏卡
  │
  └─ 用户说「下单」
       ├─ calculate-price(...)     → 金额（分）、takeWayList
       └─ create-order(...)        → 支付链接
```

## 参数传递规则（实际踩过的坑）

- 到店自取 `beType=1` → `orderType=1`，**不传 `beCode`**，传了报错。
- 得来速 `beType=5` → `orderType=1`，**必须**传 `beCode`。
- 外送 `beType=2` / 团餐 `beType=6` → `orderType=2`，必须传 `beCode`（来自 `delivery-query-stores`）。
- `create-order` 的 `takeWayCode` 只能取自 `calculate-price` 返回的 `data.takeWayList[].code`。
- **单位**：`query-meals.currentPrice` 是元；`calculate-price` 返回分。

细节见 [`references/mcp-tools.md`](references/mcp-tools.md)。

## 业务价值：为什么非接 MCP 不可

| 如果没有 MCP | 接了 MCP |
|---|---|
| 候选池是静态 JSON，抽到门店没有的商品 | 池子 = 当前门店**此刻**可售，抽中即可下单 |
| 价格靠记忆，可能过期 | 价格 = 门店现价，`calculate-price` 可核，端盒预算绝对不超支 |
| 图片靠扒，有版权风险 | 图片 = 官方 CDN 实拍原图，直接引用并内联展示 |
| 营养靠估 | 营养 = 官方表，精确匹配与规格后缀（如可乐对齐可乐中杯）严格对齐 |
| 上新要手动录 | `tags` 含"上新"的商品自动进入当期卡池，赛季自更新 |
| 品类碎片化 | 9 大系列涵盖主食、炸鸡、薯条、饮品、甜品、咖啡、随心配、多人餐、早餐全品类 |

**一句话**：MCP 提供"此刻真实的菜单"，麦泡泡提供"选择它的一百种有趣方式"。没有前者，盲盒只是空中楼阁。

## 数据流向与隐私

- 上行：门店编码、商品编码、数量。**不发送**用户身份信息。
- 下行：菜单、营养、价格、支付链接。
- 本地存储：`~/.popmc/collection.json`，仅 `productCode` / 名称 / 次数 / 时间。
- 不落盘：Token、手机号、详细地址。
