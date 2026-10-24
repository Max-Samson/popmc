# 麦泡泡 PopMc · 卡面画廊与图片映射指南 (CARD GALLERY)

> 本文档内置在 `skill/popmc` 内部，记录全部已生成的卡面图片资产路径与呈现规则。  
> 无论是向用户播报抽盒结果，还是在对话中展示系列预览，均可直接取用本目录下的资产。

---

## 一、内置图片资产结构

Skill 内置资产集中存放于 `skill/popmc/assets/` 下：

```text
skill/popmc/assets/
├── cards/                  # 18 款高保真卡面 SVG（含内联 base64 官方实物图）
│   ├── beef-universe-SSR.svg    # 图腾·巨无霸
│   ├── beef-universe-R.svg      # 人气·不素之霸双层牛堡
│   ├── beef-universe-N.svg      # 常驻·麦香鱼
│   ├── chicken-SR.svg           # 当期·龙焰鸡腿堡
│   ├── chicken-R.svg            # 人气·薄皮焦香V翅
│   ├── chicken-N.svg            # 常驻·麦辣鸡翅
│   ├── fries-snack-SSR.svg      # 图腾·经典大薯条
│   ├── fries-snack-R.svg        # 人气·脆脆薯条
│   ├── drinks-soda-SSR.svg      # 图腾·麦当劳奶昔
│   ├── drinks-soda-R.svg        # 人气·100% 苹果汁
│   ├── dessert-R.svg            # 人气·经典奥利奥麦旋风
│   ├── dessert-N.svg            # 常驻·香芋派
│   ├── coffee-R.svg             # 人气·卡布奇诺
│   ├── combo-R.svg              # 人气·大堡口福三件套
│   ├── party-R.svg              # 人气·堡堡随心拼
│   ├── box-chicken.svg          # 端盒全套展柜卡（主食+副食+饮品）
│   └── package-chicken.svg      # 开心乐园立体盲盒包装盒（开盒前）
└── unbox/                  # 泡泡玛特开盒动图 (GIF)
    ├── unboxing-ssr.gif         # 巨无霸全流程开盒动图 (2.6MB)
    └── unboxing-chicken.gif     # 龙焰鸡腿堡全流程开盒动图 (2.4MB)
```

---

## 二、各系列代表性卡面对应速查

| 系列名称 | 代码 | 代表性商品 | 对应内置图片路径 | 视觉特点 |
|---|---|---|---|---|
| **未开封盲盒** | `BOX` | 经典开心乐园盒 | `assets/cards/package-chicken.svg` | 双拱提手、金黄白芝麻底纹、大问号 |
| **开盒动图** | `GIF` | 巨无霸开盒过程 | `assets/unbox/unboxing-ssr.gif` | 晃盒听声、撕条、神光爆发、卡牌飞升 |
| **端盒一餐** | `SET` | 脆鸡+薯饼+饮品 | `assets/cards/box-chicken.svg` | 三件套展台、分项总价、总能量 |
| **牛堡宇宙** | `BU` | 巨无霸 (SSR) | `assets/cards/beef-universe-SSR.svg` | 全息彩虹流光外框、图腾勋章 |
| **脆鸡江湖** | `CH` | 龙焰鸡腿堡 (SR) | `assets/cards/chicken-SR.svg` | 香槟金边流光、当期勋章 |
| **金黄薯界** | `FS` | 经典大薯条 (SSR) | `assets/cards/fries-snack-SSR.svg` | 经典红黄薯条盒配色、金色图腾 |
| **气泡星海** | `SD` | 麦当劳奶昔 (SSR) | `assets/cards/drinks-soda-SSR.svg` | 冰爽深蓝气泡底色、金色图腾 |
| **甜品星球** | `SW` | 经典奥利奥麦旋风 (R) | `assets/cards/dessert-R.svg` | 藕粉马卡龙色系、银钛微闪 |
| **麦咖啡星系**| `CF` | 卡布奇诺 (R) | `assets/cards/coffee-R.svg` | 深褐燕麦色调、咖啡豆纹理 |
| **随心搭子** | `CL` | 大堡口福 (R) | `assets/cards/combo-R.svg` | 薄荷绿、超值组合铭牌 |
| **分享派对** | `PT` | 堡堡随心拼 (R) | `assets/cards/party-R.svg` | 紫金开黑炫彩 |

---

## 三、对话中图片播报调用规则

1. **单抽结果展示**：
   - 动态环境：优先展示动态图 `assets/unbox/unboxing-ssr.gif` 或刚渲染生成的卡面 SVG；
   - 静态环境：直接通过卡面渲染器输出到当前目录并引用。
2. **端盒结果展示**：
   - 优先展示 `assets/cards/box-chicken.svg` 或即时生成的 `box.svg`，呈现三格展台。
3. **开盒前预热展示**：
   - 当用户在选择系列时，可展示未开封的盲盒外盒 `assets/cards/package-chicken.svg`，强化期待感。
