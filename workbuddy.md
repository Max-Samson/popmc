# WorkBuddy 开发对话上下文

> 本文件用于核验本项目的 WorkBuddy 联动开发。内容为本次开发会话的**结构化实录摘要**（非逐字全文）。
> 会话中所有代码、文档、卡面均由 WorkBuddy 在对话中直接生成并落地到本仓库。

## 会话信息

| 项 | 值 |
|---|---|
| 日期 | 2026-10-24 |
| 客户端 | WorkBuddy（Agent 模式） |
| 接入的 MCP | `mcd-mcp`（https://mcp.mcd.cn） |
| 产出 | 本仓库全部文件 |

## 时间线与关键动作

**1. 赛道研判**

- 读取 `M-China/mcd-developer-innovation-challenge` 的 README 与 `activityGuidelines.md`，提取硬约束：
  必需 5 个文件（README / CONTEST_DECLARATION / MCP_INTEGRATION / mcp-config.example.json / workbuddy.md）、
  排名依据公开 Star、截止 2026-10-25 23:59、内容合规禁止赌博与诱导消费。
- 读取 `RANKING.md` 快照（2026-10-24 18:00），确认头部集中在"省钱/预算/派对"，抽盒类已有
  `mcgacha`(58)、`mcd-gacha-collector`(49)、`McLottery-Alchemist`(59)，且都在尾部。
  → 结论：差异化不能只在"抽"，必须落在「真实在售池 + 官方数据驱动 + 可下单闭环」。

**2. 真实 MCP 探针（未凭记忆假设接口）**

在会话中实际调用了以下工具并拿到返回：

| 调用 | 目的 | 关键发现 |
|---|---|---|
| `query-nearby-stores(beType=1, searchType=2, city=上海, keyword=人民广场)` | 拿 storeCode | 到店场景不返回 beCode |
| `query-meals(storeCode=1450713, orderType=1, beType=1)` | 看菜单结构 | 分类名含 `\n`；`meals` 是 map；混着丝巾/棒球帽/酱料；图片为官方 CDN 320px |
| `query-meal-detail(code=9900005466)` | 看套餐组成 | rounds/choices 结构，含特调 selectedKey/unselectedKey |
| `list-nutrition-foods()` | 看营养数据 | `data` 是**字符串**不是 JSON，9 字段逗号分隔，含"能量约猕猴桃2个"这类官方描述 |

**3. 方案融合（用户提供了第二版更偏合规的设计）**

用户补充了一版强调"事实层/创意层分离、不自动下单、概念视觉必须标注"的方案。会话中据此逐条裁决并
写下 [`docs/DESIGN-DECISIONS.md`](docs/DESIGN-DECISIONS.md)（10 条决策），其中关键三条：

- 数据结构改为三层：`fact` / `experience` / `meta`，禁止互相冒充。
- 保留"抽完可下单"，但加两道门：抽盒只做只读算价，`create-order` 需复述 + 二次确认。
- 稀有度保留，但改名为「常驻/人气/当期/图腾」，并强制声明"不代表官方发行量或限量"。

**4. 编码与自检**

- `scripts/draw.py`：建池 → 硬约束过滤（预算/排除）→ 情绪选系列 → 确定性 HMAC 种子 → 等级加权 + 保底 → 三层卡片输出；空池返回结构化 `reason` 而非编造。
- `scripts/render_card.py`：600×840 SVG，官方商品图 + 自研卡框，四档稀有度视觉可辨，底部强制水印。
- `scripts/collection.py`：本地图鉴 + 人格卡，明确"收藏≠购买"。
- `tests/test_draw.py`：23 项自检，全部通过。

**5. 真实缺陷修复（会话内发现）**

- 巨无霸(1100) 同时出现在「人气热卖」与「巨无霸牛鱼肉堡」。按 code"先到先得"去重导致它被从牛堡宇宙
  静默丢弃（图腾款消失且不报错）。→ 改为合并 `categories` 与 `tags`，并补了回归测试
  `test_dedupe_merges_categories`。
- 稀有度实际概率 ≠ 公示权重：50 抽保底把 SSR 抬到约 2%。→ `--odds` 输出补充说明，
  对外公示以含保底的实际值为准。


**6. 泡泡玛特 3D 开盒动效与视觉深度重铸**
- 针对用户提出“产物不能只是一张静态图片，要符合泡泡玛特盲盒效果并输出开盒 GIF 动图”的要求，研发了 `scripts/animate_unbox.py` 开盒动图逐帧生成引擎。
- 完整实现了四阶段动效：聚光灯晃盒听声 ➔ 撕裂外卖锯齿封条 ➔ 8 芒金色神光与彩纸粒子喷发 ➔ 卡牌 360 度翻转飞升与定格展示。
- 开发了纯前端 3D 沉浸式开盒播放器 `docs/unboxing-player.html`，支持 3D 陀螺仪鼠标重力倾斜，并创新性使用 Web Audio API 纯代码合成摇盒、撕纸与揭晓登场和弦音（零外部音频文件依赖）。
- 盒身全面融入麦当劳标志性元素：开心乐园餐经典双拱提手、汉堡白芝麻纹理底纹、经典外卖红黄锯齿安全封条、神秘汉堡轮廓剪影。

**7. 逻辑调度升级与全品类扩容**
- 重构约束感知系列调度（Constraint-Aware Routing）：彻底修复“低预算用户未指定系列时误报 budget_too_low”的盲区，在选系列前先扫描硬约束下的有效池，低预算 100% 命中高性价比美食。
- 扩容至 9 大盲盒系列：新增【金黄薯界】(大薯条图腾) 与【气泡星海】(麦当劳奶昔图腾)，彻底达成单店真实在售食品单品 100% 覆盖。
- 完善品牌系统升级为【麦泡泡 PopMc】（Slogan: Pop Your Meal · 麦麦开盒），技能名对齐为 `popmc`。

## 用到的 WorkBuddy 能力

- 联网读取 GitHub 仓库与规则文件
- 直接调用已配置的 `mcd-mcp` 连接器做真实接口探针
- 本地文件读写、Python 脚本生成与执行、单元测试
- Chrome headless 截图校验卡面渲染结果

## 说明

- 会话中的 MCP Token 为使用者本地配置，**未**写入仓库任何文件。
- 本文件不包含手机号、地址等个人信息。
