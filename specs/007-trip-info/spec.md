# Spec 007：这次行程的信息（每件办事自己的一份）

- 状态：第 1 步开发中（2026-09-29）
- 依据：项目主在 ImmiAccount 上实测后："每次办签证的 purpose 不一样，导致很多细节信息没法自动填写造成卡点，
  agent 也只能读这个页面的信息，而没办法读桌面本地的这次的准备材料的信息（邀请函内容之类的）"。
  讨论后项目主决定（2026-09-29）：**开始办事的时候问**；读材料按"只读这件事对应的文件、在办事页上、结果由用户确认"；插件接上这件事。
- 相关：spec 002（攻略与办事）、003（基本信息）、005（填表引擎）、006（插件）。

## 问题

数据有三层，缺了中间一层：

| 层 | 放什么 | 例子 |
|---|---|---|
| 基本信息（spec 003） | 长期不变，所有办事共用 | 姓名、护照、工作单位 |
| **这次行程（本 spec）** | 每件办事不一样，办完就没用 | 目的、往返日期、住哪、邀请人、谁出钱、同行人 |
| 材料库 | 文件 | 邀请函、酒店订单、银行流水 |

以前"这次行程"的信息哪里都不存：填表时每次都要问，插件和 Agent 都填不了。

## 第 1 步：开始办时问，存在这件办事里

### 数据：`Track.trip`（`src/core/trip.py` 的 `TripInfo`）

全部字段可空。分 6 组，组名是攻略里用的 key：

| 组 | 字段 | 类型 |
|---|---|---|
| `purpose` 目的 | `purpose` 目的（官网选项的写法，例如 Tourism / Business） | text |
| | `purpose_detail` 具体做什么（例如参加某个会议） | textarea |
| `dates` 日期 | `arrival_date` 计划入境日期、`departure_date` 计划离境日期 | date |
| | `arrival_city` 入境城市 | text |
| `stay` 住处 | `stay_name` 酒店 / 住处名称、`stay_phone` 电话 | text |
| | `stay_address` 地址（和基本信息同一个 `Address`：street / city / province / postal_code / country） | 对象 |
| `host` 邀请人 / 联系人 | `host_name` 姓名或机构名、`host_relationship` 关系、`host_phone`、`host_email` | text |
| | `host_address` 地址（`Address`） | 对象 |
| `funding` 费用 | `payer` 谁出钱：`self` 自己 / `host` 邀请方 / `employer` 单位 / `family` 家人 / `other` 其他 | select |
| | `payer_detail` 说明（例如父母的姓名） | text |
| `companions` 同行人 | `companions`：`[{name 姓名, relationship 关系}]` | 列表 |

- 存在 Track 文件里（材料根目录 `tracks/<id>.yaml` 的 `trip:`），和这件办事一起删除；**不写进基本信息**。
- 旧的 Track 文件没有 `trip:`，读出来是空的 `TripInfo`，不报错。

### 哪些攻略要问

- 攻略 YAML 可以写 `trip: [purpose, dates, stay, host, funding, companions]` 里的任意几组（顺序即显示顺序）。
- 不写时：`category: 签证` 的攻略问全部 6 组；其他分类（补贴等）不问。写 `trip: []` 表示不问。
- 校验（`python -m core.guides`）：`trip` 里只能出现上面 6 个组名，不能重复。

### 接口

- `GET /api/tracks/{id}` 的 `TrackView` 增加 `trip`（当前值）和 `trip_groups`（`[{key, label, fields: 同 describe 的字段描述}]`，只含这件事要问的组）。
- `PUT /api/tracks/{id}/trip`：body 是 `TripInfo` 的一部分（只放要改的字段；对象逐键合并，列表整体替换，同 `update_profile_fields`）。
  字段名不对 / 值不合法 → 422，文件不变。返回新的 `TrackView`。

### 界面（办事页）

- 攻略的判断题下面加一块「这次行程」，按 `trip_groups` 分组列出输入框；改了就保存（失焦 / 选择时）。
- 刚开始办、一项都没填时展开；填过之后收成一行摘要（"目的：Tourism · 2026-10-01 → 10-15 · 住处：……"），点"修改"展开。和判断题的收起方式一样。
- 没有 `trip_groups` 的办事不显示这一块。

### 填表：引擎和插件认得"这次行程"

- 同义词表 `community/form_fields.yaml` 增加 `trip.*` 路径（例如 `trip.purpose` ← "purpose of (your) trip / visit / stay"；
  `trip.arrival_date` ← "intended date of arrival / arrival date"；`trip.stay_address.*` ← "address where you will stay"……）。
- `plan()` 增加参数 `trip: TripInfo | None`：`trip.*` 的值从这里取；没给时这些格子算"资料里没有"。
- 插件侧边栏顶部加「这件事」下拉框：列出正在办的事；按网址猜一个（这件事的攻略里有官网链接和当前网址同域名的，最近创建的优先），
  用户改选后按网站记住（`chrome.storage.local`）。选"不关联"时和以前一样。
- `/api/ext/plan`、`/api/ext/capture` 增加可选 `track_id`：
  - plan：用这件事的 `trip` 填 `trip.*` 格子；
  - capture：`trip.*` 的差异照样列出，保存时写进这件事（`PUT` 同一套合并），其余写进基本信息。
- 对照清单 `/api/fill-helper?track_id=` 多一组「这次行程」。
- 「让 Agent 补填」：context 带 `track_id`；prompt 告诉 Agent 用 `get_fill_reference(track_id)`（多出「这次行程」一组）；
  Agent 可以用新工具 `propose_trip_update(track_id, changes)` 提议改行程信息（和 `propose_profile_update` 一样要用户确认）。

### 验收（第 1 步）

1. `uv run pytest` 通过，新增测试覆盖：
   - 旧 Track 文件（没有 `trip:`）能读；`PUT /trip` 部分更新、对象逐键合并、非法字段 422 且文件不变；
   - 签证类攻略默认 6 组、补贴类 0 组、`trip: [purpose]` 只有 1 组、`trip: [nope]` 校验报错；
   - 引擎：`Purpose of trip`、`Intended date of arrival`、住处地址的格子认成 `trip.*`，给了 `trip` 就进计划、没给就在 missing；
   - 接口：plan / capture 带 `track_id` 时用 / 写这件事的 `trip`；capture 保存时 `trip.*` 写进 Track，其他写进基本信息；
   - `fill_assist` 的工具里有 `propose_trip_update`、`get_track`。
2. 项目主实测：开始办一件签证事项，在办事页填好目的和日期；在官网上选中这件事后"填本页"，目的和日期能填上。

## 第 2 步：从材料里读出行程信息（用户确认后才存）

项目主同意（2026-09-29）放宽"Agent 不读材料内容"这一条，**只在下面的范围里**：

- **只读这件事对应的文件**：Track 的 `matches` 里挂着的材料记录指向的文件（例如邀请函、酒店订单），不能读材料根目录里的其他文件。
- **只在办事页上、用户点了才读**：「这次行程」一块加按钮「从材料里读」，用户勾选读哪几份后，调起 Agent 任务（新任务类型 `trip_extract`）。
  插件里的 Agent **不读**文件，只用已经存下来的行程信息。
- **结果要确认**：Agent 用 `propose_trip_update` 提议，页面上逐项显示"空 → 新值"，用户确认后才写。
- 读文件用新 MCP 工具 `read_track_material(track_id, record_id)`：
  - 检查 `record_id` 确实挂在这件事的 `matches` 里，否则报错；
  - PDF 取文字（没有文字层的扫描件返回"读不出文字"，不做 OCR）；图片不读；
  - 只有 `trip_extract` 任务能用（和 `submit_form_fills` 一样按环境变量限制）。
- `docs/SPEC-mvp.md` 的安全约束同步改写："Agent 默认不读材料内容；唯一例外是 spec 007 第 2 步"。

第 2 步的细节（按钮位置、PDF 取文字用哪个库、`trip_extract` 的 prompt）在第 1 步完成后补充进本 spec 再做。

## 不做

- 不从旧的办事自动复制行程信息（每次行程本来就不同）。
- 不把行程信息写回基本信息（项目主的规则：本次行程信息不写回）。
- 多段行程（去好几个国家、几段日期）：先只支持一段，放 BACKLOG。
