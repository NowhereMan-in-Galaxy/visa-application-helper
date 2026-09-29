# Spec 007：这次行程的信息（每件办事自己的一份）

- 状态：第 1 步完成、项目主实测通过（2026-09-29）。第 2 步完成（2026-09-29）：自动测试通过，等项目主实测（第 2 步验收第 2 条）
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
| `purpose` 目的 | `purpose` 目的（按官网选项的写法填，例如 Tourism / Business） | text |
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

## 第 2 步：说一句话或读材料，让 Agent 整理成行程信息（用户确认后才存）

依据：项目主实测第 1 步后（2026-09-29）："希望材料可以读出来，或者用户可以用自然语言描述一下这次办理签证的目的、时间……
旅行就要行程单、机票、住宿；商务就要各种邀请函、时间、行程安排。"

项目主同意（2026-09-29）放宽"Agent 不读材料内容"这一条，**只在下面的范围里**。

### 2a. 行程信息补两组、一个字段

按常见签证表格和材料清单补齐（旅游看行程单、机票、住宿；商务看邀请函、活动、日程）：

| 组 | 字段 | 类型 |
|---|---|---|
| `transport` 交通（新） | `arrival_flight` 去程航班 / 车次、`departure_flight` 返程航班 / 车次 | text |
| `itinerary` 行程安排（新） | `itinerary`：`[{start_date 开始, end_date 结束, city 城市, plan 安排}]` | 列表 |
| `host`（改） | 新增 `host_organization` 单位 / 机构；`host_name` 的标签改成"联系人姓名" | text |

- 组的默认顺序：purpose、dates、transport、itinerary、stay、host、funding、companions。签证类攻略默认问全部 8 组。
- 同义词表加 `trip.arrival_flight`（"arrival flight / flight number"……，排除 departure / return）、`trip.departure_flight`（反之）、
  `trip.host_organization`（"inviting organisation / company / institution"）；`trip.host_name` 排除 organisation / company 这类词。
  `itinerary` 是列表，不进同义词表，只出现在对照清单和 Agent 读的参考里。

### 2b. 办事页：「这次行程」一块顶部加"让 Agent 整理"

```
这次行程
┌──────────────────────────────────────────────────────┐
│ [输入框：用几句话说说这次行程……]                        │
│ 读材料：[✓ 邀请函] [✓ 酒店订单] [ ] 护照首页             │
│                                    [ 让 Agent 整理 ]  │
│ （对话记录、确认卡片出现在这里）                          │
└──────────────────────────────────────────────────────┘
目的 / 日期 / 交通 / ……（第 1 步的输入框）
```

- 输入框的 placeholder 给一个例子；**不加说明文字**。
- 「读材料」列出这件事的材料（见 2c），每份一个勾选框。默认勾上"一次性材料"（记录的 `for_track` 是这件事，或词表类型 `reusable: false`）；
  长期材料（护照等）默认不勾。格式不支持的不列。
- 输入框为空、也没勾材料时按钮不可点；输入框为空但勾了材料时，发给 Agent 的话是"读我勾选的材料"。
- 用 `AgentChat.create({kind: "trip_extract", ...})`，对话窗口整页只建一份，重画办事页时挂回原处（不丢对话）；可以接着说话补充（同一个 session）。
- Agent 的提议用第 1 步已有的确认卡片（逐项"空 → 新值"）；卡片标题改为"整理出的这次行程"，确认后提示"✓ 已存进这件办事"并重画办事页。
- 收起状态（一行摘要）不显示这个框；点"修改"展开后才有。

### 2c. 哪些材料算"这件事的材料"

`trip_materials(track, records)`（放在 `src/core/trip.py`）：
- 记录 id 出现在 `track.matches` 的任一列表里（用户确认过挂在这件事上），**或者**记录的 `for_track == track.id`；
- 有 `file_ref`，后缀是 `.pdf .txt .md .docx .png .jpg .jpeg .webp` 之一（`compute_track_view` 里算，不碰文件系统；文件在不在、是不是落在材料根目录里面，由 `read_track_material` 读的时候检查）。
- `TrackView` 增加 `trip_materials: [{id, type, sublabel, one_off}]`（不含路径）。

### 2d. MCP 工具 `read_track_material(track_id, record_id)`

- `record_id` 必须在 `trip_materials(...)` 里，否则返回 `{"error": ...}`，不读任何文件。
- 只在 `trip_extract` 任务里能用：`agent_runner/jobs.py` 启动子进程时设环境变量 `PA_AGENT_KIND=<任务类型>`，工具检查它等于 `trip_extract`，
  否则报错（终端里的 Agent 也读不了）。另外只有 `trip_extract` 的工具白名单里有它。
- 返回：
  - `.pdf`：pypdf 取文字（最多前 10 页）；取到的文字少于 20 个字符时（扫描件），改为返回 PDF 里嵌入的图片（前 3 页、每页最大那张）；都没有返回"读不出文字"。
  - `.txt .md`：原文；`.docx`：解压 `word/document.xml`，去掉标签，段落换行。
  - `.png .jpg .jpeg .webp`：图片本身（MCP 图片内容），大于 5 MB 返回"图片太大"。
  - 文字最多 20000 字符，超出截断并注明。
- 读过哪份文件不写日志、不缓存。

### 2e. 任务类型 `trip_extract`

- 工具白名单：`get_track`、`get_guide`、`read_track_material`、`propose_trip_update` + 仓库规则的 Read。没有浏览器、没有写基本信息的工具。
- `POST /api/agent/jobs`：`kind="trip_extract"` 时 `context.track_id` 必填、必须存在（否则 422）；`context.materials` 是勾选的记录 id 列表，
  每个都必须在这件事的 `trip_materials` 里（否则 422）；第一条消息最多读 6 份。
- 用量上限 3.0。
- 提示词 `trip_extract_prompt(user_input, context)`：
  1. 用 `get_track` 看这件事（攻略、已填的行程信息 `trip`）；
  2. 依次 `read_track_material` 读勾选的材料；
  3. 只根据用户的话和材料原文，用**一次** `propose_trip_update` 提议（已有值相同的不提；和已有值不同的照样提，卡片上会显示旧值）；
     材料之间或和用户的话矛盾时不提那一项，在回答里列出来让用户定；
  4. 按目的列出这类行程通常还要、但现在还空着的几项（最多 5 项），问用户：
     旅游 → 行程安排、去返程航班、住处；商务 / 会议 → 邀请单位、联系人和电话、活动内容、谁出钱；探亲访友 → 邀请人姓名、关系、地址、电话；
  5. 中文、简短；不复述证件号；不写基本信息（基本信息的差异只在回答里提一句）。
- 确认卡片事件（SSE `proposal`）增加 `track_id`（行程提议才有），页面据此重画。

### 验收（第 2 步）

1. `uv run pytest` 通过，新增测试覆盖：
   - 新字段：旧 Track 能读；`PUT /trip` 能写 `itinerary`、`host_organization`；签证类攻略默认 8 组；
     引擎把 "Arrival flight number" 认成 `trip.arrival_flight`、"Name of inviting organisation" 认成 `trip.host_organization`；
   - `trip_materials`：确认过的、`for_track` 的都在；没确认的候选、文件不存在、路径跑出材料根目录的、不支持的后缀都不在；
   - `read_track_material`：没设 `PA_AGENT_KIND=trip_extract` 报错；不属于这件事的记录报错且不读文件；txt / docx / pdf（有文字层）读出文字；
   - `POST /api/agent/jobs` `trip_extract`：没有 track_id / 不存在 / 材料不属于这件事 → 422；正常时提示词里有 track_id 和材料 id；
   - `trip_extract` 的工具白名单正好是上面几个；jobs 启动时环境变量里有 `PA_AGENT_KIND`。
2. 项目主实测：在一件签证办事里说一句"10 月 1 日到 15 日去悉尼开会，住会场旁边的酒店，学校出钱"，确认卡片后行程信息填上；
   挂一份邀请函 PDF，勾上读，能提议出邀请单位和联系人。

## 不做

- 不从旧的办事自动复制行程信息（每次行程本来就不同）。
- 不把行程信息写回基本信息（项目主的规则：本次行程信息不写回）。
- 多段行程（去好几个国家、几段日期）：先只支持一段，放 BACKLOG。
