# Feature Specification: 共同维护的流程攻略 + 我的办事

**Created**: 2026-09-23（同日第二版：引入"攻略模板 / 我的办事"拆分）

**Status**: Draft（数据结构已定，Phase A 实现中）

**Input**: 项目主的产品思考（2026-09-23 对话）：签证/办事这类行政流程繁琐、让人焦虑。三个痛点：①不同事情反复提交同样的基础材料；②收藏了网上攻略，但自己对照着准备依然很慢；③最难的一步是弄清楚"到底要办什么"。同日确定产品形态：**做成大家共同维护的签证/办事流程攻略库**——任何人可以提交一份结构化的流程攻略；本地 Agent 辅助把杂乱的图文攻略整理成这种结构；同时有一个可以交互检视的界面，让人照着攻略一步步办、对上自己的材料。

## 与已有文档的关系

- **取代并扩展** `specs/001-visa-material-hub/spec.md` 的 User Story 2（"用自然语言/图片生成材料清单"）。001 US3（为缺失材料建文件夹）之后改为依赖本 spec 的产出。
- **遵守** `docs/SPEC-mvp.md` 第 2 条（核心库 vs Agent 层）：Agent 只负责"读懂攻略、整理成结构"；校验、匹配、状态、下一步全部是确定性代码。
- **遵守** `AGENTS.md` 第 3 条，并把它具体化为**共享区 / 个人区**的硬边界（见下）。

## 核心概念（给新手的解释）

- **流程攻略（Guide）**：一份结构化的"某类事怎么办"，例如"申根短期旅游签"。它**不属于任何具体的人**，不含任何个人信息，所以可以放进公开仓库，大家一起改、一起补。相当于菜谱。
- **我的办事（Track）**：某个人"照着某份攻略办的这一次"，例如"我 2026 年底的申根签"。它记录这个人的情况（在职、未婚）、做到了哪一步、哪条需求用了自己的哪份材料。**只存在这个人自己的电脑上。** 相当于"照着菜谱做的这一顿饭"。
- **材料需求（Requirement）**：攻略里的一条"需要某种材料"。它是对材料的**要求**，不是材料本身。
- **材料记录（MaterialRecord）**：001 已有的概念，是你手上真实的一份材料（的元数据）。
- **匹配**：把"需求"和"记录"连起来。同一份护照记录可以满足三件事的需求，不用录三遍——这就是"材料复用"。
- **材料类型词表**：一份"标准材料名 + 各种叫法"的对照表，匹配靠它对齐五花八门的叫法。它也是共享内容。

为什么要拆成两种文件：如果把"我是在职、我已经做完了第 3 步"写进攻略本身，这份攻略就没法分享了；拆开后，攻略被别人改进（例如补上一条漏掉的材料），所有照着它办事的人打开自己的 Track 都能立刻看到。

## 共享区 / 个人区（硬边界）

| | 共享区 `community/` | 个人区 `<材料根目录>/tracks/` |
|---|---|---|
| 放什么 | 流程攻略、材料类型词表、贡献说明 | 我的办事（Track） |
| 在不在 Git 仓库里 | 在，公开，接受别人提交 | 不在（材料根目录本来就被 `.gitignore` 排除或在仓库外） |
| 能不能有个人信息 | **绝对不能** | 可以（身份、婚否、进度、材料 id） |

任何代码都不能把个人区的内容写进 `community/`。

## 数据流总览

```
杂乱攻略（小红书截图、知乎长文、官网）
   │  ① 本地 Agent 按 prompt.md 整理（贡献者自己的 Claude Code / Codex 等）
   ▼
community/guides/<id>.yaml ── 校验器检查 ── 提交到仓库，大家共同维护
   │
   │  ② 用户在界面上"开始办这件事"
   ▼
<材料根目录>/tracks/<id>.yaml（我的办事）
   │  ③ 回答几个问题（facts）→ 不适用的材料自动隐藏
   │  ④ 需求 ↔ 我的材料：纯代码匹配，用户确认
   ▼
   ⑤ 界面：下一步做什么 / 缺什么 / 什么过期了 / 最终核对
```

## 数据结构（已定，执行 Agent 按此实现，不要自行增删字段）

### 1. 流程攻略：`community/guides/<guide-id>.yaml`

真实样本见 [`community/guides/schengen-tourist.yaml`](../../community/guides/schengen-tourist.yaml)。字段：

```yaml
id: schengen-tourist                     # 小写字母/数字/连字符，与文件名一致
title: 申根短期旅游签证（中国大陆护照）
category: 签证                           # 签证 | 工作 | 社保 | 银行补贴 | 其他
summary: 一句话说明适用范围              # 可选
maintainers: []                          # 可选；GitHub 用户名，不写真实姓名
updated: 2026-09-23                      # 这份攻略最后一次被修订的日期
timeline: 递签后通常 15 天出签；建议提前 1–1.5 个月递签   # 可选；一句话说明全程要多久，显示在页面最上方

sources:                                 # 这份攻略是从哪些原始资料整理出来的
  - id: g1
    title: 上海送签日本单次旅游签全流程
    url: https://example.com/post/123    # 可选，仅 http/https
    as_of: 2026-05-01                    # 可选；原始资料的信息时效。距今超过 365 天时界面提示"可能过时"

phases:                                  # 可选但强烈建议；整件事的几个大阶段，显示为页面最上方的进度条
  - id: p-online                         # 大多数签证都是：官网填表/预约（线上）→ 准备材料 → 递交（线上或线下）→ 等结果
    title: 官网填表并预约
    mode: online                         # online | offline | 不写（不明确时）
    summary: 在官网填申请表，再预约递签时间   # 可选
    estimate: 1–2 小时                    # 可选，自由文本
    duration_days: null                  # 可选；需要等待的天数 {typical, max}
    evidence: []                         # 可选

facts:                                   # 会改变清单内容的问题。攻略里只有问题，没有答案
  identity:
    question: 你目前的身份是？
    options: [在校学生, 在职, 自由职业, 退休]
    ask_if: []                           # 可选；什么情况下才问，格式同 applies_if

requirements:
  - id: r-bank
    kind: obtain                         # obtain 自己去办/去拿 | generate 可由 AI 起草 | output 完成某步后自然得到
    material_type: bank_statement        # 词表 key；认不出时填 null，raw_name 必填
    raw_name: 近半年银行流水              # 原始资料里的叫法
    optional: false                      # true = 加分项，有就交，不计入进度
    applies_if: []                       # 全部满足才生效；例 [{fact: identity, in: [在职]}]
    freshness_days: 30                   # 可选；递交时材料开具不能超过多少天
    note: 需覆盖近 6 个月                 # 可选；无法机械判断的要求
    evidence: [{source: g1, quote: "流水要近半年的"}]

steps:
  - id: s-bank
    title: 去银行打流水
    phase: p-materials                   # 定义了 phases 时必填
    where: 线下 · 任意支行柜台
    requirements: [r-bank]
    depends_on: []
    applies_if: []
    estimate: 30 分钟                     # 可选，自由文本
    duration_days: null                  # 可选；等待天数 {typical: 15, max: 45}
    evidence: [{source: g1, quote: "…"}]

checks:                                  # 材料之间的一致性要求，最终核对时逐条勾选
  - id: c-hotel-itinerary
    text: 酒店预订单的城市和日期必须与行程单一致
    involves: [r-hotel, r-itinerary]
    evidence: [{source: g1, quote: "…"}]

conflicts:                               # 原始资料之间说法不一致时原样摆出，不替用户选
  - id: k-bank-freshness
    about: r-bank.freshness_days
    claims:
      - {source: g1, quote: "一个月内开的就行"}
      - {source: g2, quote: "要求 15 天内"}

uncertain: [r-bank.note]                 # 整理者没把握的字段路径，界面提示核对
```

校验规则（全部可机械检查，`src/core/guides.py` 实现，违反任一条即该攻略"无效"）：
- `id` 与文件名（去掉 `.yaml`）一致，只含小写字母、数字、连字符。
- `sources` / `requirements` / `steps` / `checks` / `conflicts` 各自的 `id` 在文件内唯一。
- `steps[].requirements`、`checks[].involves` 引用的 requirement 必须存在；`steps[].depends_on` 引用的 step 必须存在；所有 `evidence[].source`、`conflicts[].claims[].source` 引用的 source 必须存在。
- `depends_on` 不能成环。
- 每条 requirement 至少出现在一个 step 的 `requirements` 里。
- 每条 requirement 和 step 至少有一条 `evidence`；`evidence[].quote` 不超过 60 个字符。
- `kind` 只能是 `obtain` / `generate` / `output`；`category` 只能是上面列出的五个值。
- `material_type` 非 null 时必须是词表里的 key；为 null 时 `raw_name` 不能为空。
- `applies_if[].fact`、`ask_if[].fact` 必须是 `facts` 里的键，`in` 里每个值必须在该 fact 的 `options` 里；`ask_if` 不能引用自己。
- `duration_days` 非 null 时 `typical`、`max` 为正整数且 `typical <= max`。
- `sources[].url` 非空时必须以 `http://` 或 `https://` 开头。
- 定义了 `phases` 时：每个 step 必须写 `phase` 且引用存在的阶段；每个阶段至少有一个 step；`phases[].mode` 只能是 `online` / `offline` 或不写。

### 2. 我的办事：`<材料根目录>/tracks/<track-id>.yaml`

```yaml
id: schengen-tourist-20260923            # 创建时生成：<guide-id>-<YYYYMMDD>，重名时追加 -2、-3…
guide: schengen-tourist                  # 照着哪份攻略办
title: 2026 年底去法国                    # 用户自己起的名字，默认等于攻略 title
created: 2026-09-23
deadline: 2026-12-01                     # 可选
facts: {identity: 在职, married: 否}      # 用户的回答；没回答的键不出现
done_steps: [s-copy-ids]                 # 已完成的步骤 id
matches:                                 # 用户确认过的匹配；没确认的不出现
  r-passport: [passport-bio-page, passport-visa-page, passport-stamped-pages]
done_checks: [c-hotel-itinerary]         # 最终核对里已勾选的项
completed: 2026-10-20                    # 办完的日期，由服务端自动维护，用户不直接编辑
```

- **办完**：所有生效的步骤都已完成、且没有"取决于还没回答的问题"的步骤。每次修改步骤或回答问题后，服务端重新判断：刚满足时记下当天日期；已经记过的日期不因之后的保存而改变；一旦又有没做完的步骤就清空。
- **用时** = `completed`（没办完则取今天）− `created`，单位天。首页按"办理中 / 已办完"分组，已办完的一组显示平均、最快、最慢用时。

- 攻略被别人修订后，Track 里引用了已不存在的 step / requirement / check / fact 的条目：**读取时忽略，不报错，不自动删**（用户可能还要切回旧版本）。
- 写入只经过 API，每次写入整文件覆盖；文件不存在时 API 返回 404，不自动创建。

### 3. 材料类型词表：`community/material_types.yaml`

```yaml
normalize:                               # 查词表前，对"叫法"和"别名"两边都依次删除这些正则匹配到的片段
  - '原件'
  - '复印件'
types:
  - key: passport_full_copy
    name: 护照全部页复印件
    category: passport_scan              # 对应 001 的 MaterialCategory；不属于四大类时填 null
    aliases: [护照复印件, 护照所有页]
    parts: [passport_bio_page, passport_visa_page, passport_stamped_pages]   # 可选；组合类型，只允许一层
```

- `key` 全局唯一；每个 part 必须是存在的、自身没有 `parts` 的 key。
- 匹配规则：叫法和别名都先经过 `normalize` 规则处理，再忽略大小写、去掉所有空白字符后**完全相等**才算命中。不做模糊匹配。
- 两个不同 key 的别名在规范化之后相同 → 词表无效，加载时报错并指出冲突的两个 key。
- **本条取代试验 #1 留下的待决问题 4**：采用方案 A（确定性去修饰规则）；方案 B（界面上批量确认 AI 的归类建议）随 Phase B 的本地 Agent 能力一起做。

### 4. MaterialRecord 新增一个可选字段

`material_type: str | None`——该记录属于词表里的哪个 key。没有这个字段时，用记录的 `type` 走词表匹配规则推断。

## 状态计算（`src/core/tracks.py`，纯函数，`today` 作为参数传入）

**fact 是否要问**：`ask_if` 为空，或其中每个条件都满足 → 要问；否则不问，且该 fact 视为"不适用"。

**条件判定**（`applies_if` 的每一条）：引用的 fact 不适用 → 不满足；已回答 → 答案在 `in` 里才满足；未回答 → "未定"。整组条件：任一不满足 → 不生效；否则任一未定 → 未定；否则生效。

**需求状态**，按顺序判定，命中即停：
1. `not_applicable`：条件不生效。界面隐藏，不计进度。
2. `undecided`：条件未定。界面提示先回答问题，不计进度。
3. `missing`：没有候选记录（组合类型：任一 part 没有记录）；或类型无法确定——`material_type` 为 null 时先用 `raw_name` 走词表匹配规则推断，推断不出才算"未归类"，界面单独标注。
4. `stale`：有记录，但设了 `freshness_days` 且记录 `obtained_date` 距今超过该天数，或记录状态为"已过期"（组合类型：任一 part 满足即算）。
5. `unconfirmed`：有合格记录，但 Track 的 `matches` 里没有这条需求。
6. `ready`：`matches` 里有这条需求，且其中每条记录都存在。

**判定用哪几条记录**：`matches` 里有这条需求、且其中每条记录都还存在时，用已确认的记录；否则用候选记录。`missing` / `stale` 都基于这组记录判断。

**候选记录**：`materials_index/` 里以 `example-` 开头的虚构示例记录不参与匹配。同类型、且已拿到手（`obtained_date` 非空；状态为"待补"的占位记录不算）的记录里 `obtained_date` 最新的一条（没有日期的排最后）；组合类型：有直接标成该组合类型的记录时优先用它，否则每个 part 各取一条。用户确认时，把候选写入 `matches`。

**步骤**：条件判定同上；`available` = 生效、未完成、`depends_on` 中每个**生效的**步骤都已完成（不生效的依赖视为已满足）。**下一步** = 攻略中顺序最靠前的 `available` 步骤；没有则为 null。

**进度** = `ready` 需求数 / (非 optional 且状态不是 `not_applicable`、`undecided` 的需求数)。

**阶段状态**：阶段内生效的步骤全部完成 → `done`；"下一步"落在这个阶段 → `current`；没有生效的步骤 → `skipped`；其余 → `upcoming`。没有"下一步"时（问题没答完或全部做完），第一个 `upcoming` 的阶段改为 `current`，保证进度条上总能看出走到了哪。

## 分阶段计划

### Phase A：结构落地 + 可交互检视（当前）
- `community/`：`README.md`（贡献说明）、`material_types.yaml`、`guides/schengen-tourist.yaml`（由试验 #1 转换）。
- `src/core/material_types.py`、`src/core/guides.py`（模型 + 校验）、`src/core/tracks.py`（Track 读写 + 状态计算）。
- API：
  - `GET /api/guides` → 每份攻略的摘要和校验结果（无效的攻略也列出来，附错误，不让一份坏攻略拖垮整个服务）。
  - `GET /api/guides/{id}` → 完整攻略 + 每条需求的标准材料名。
  - `GET /api/tracks`、`POST /api/tracks`（body: `guide`、可选 `title`、`deadline`）。
  - `GET /api/tracks/{id}` → 合并后的视图：facts（含是否要问）、需求（含状态、候选记录）、步骤（含是否生效/完成/可做）、下一步、进度、checks、conflicts、`stale_sources`。
  - `POST /api/tracks/{id}/requirements/{requirement}/upload`（multipart：`file` 必填；可选 `obtained_date` 默认今天、`part` 组合类型必填、`sublabel`）→ 新建一条材料记录进个人材料库（`material_type` 为需求的类型或所选 part；`category` 取词表，词表为 null 时用新增的 `other`），丢弃该需求旧的确认，材料凑齐时自动确认。
  - `POST /api/tracks/{id}/export` → 把状态为 `ready` 的材料**复制**到 `<材料根目录>/exports/<track-id>-<YYYYMMDD-HHMMSS>/`（已存在则加 `-2`…），文件名 `<两位序号>-<需求名>[-<部分名>]<原后缀>`，附 `清单.txt`（已导出 / 已确认但找不到文件 / 还没备齐）。`file_ref` 解析后不在材料根目录内的一律拒绝复制。
  - `PUT /api/tracks/{id}/facts/{fact}`（body: `value`，null 表示清除）、`PUT /api/tracks/{id}/steps/{step}`（body: `done`）、`PUT /api/tracks/{id}/matches/{requirement}`（body: `confirmed`，true 写入当前候选，false 删除）、`PUT /api/tracks/{id}/checks/{check}`（body: `done`）。
- 前端 `web/guides.html`：攻略库列表 → 攻略预览 → "开始办这件事" → 我的办事详情（回答问题、勾步骤、确认材料、最终核对）。
- 命令行校验：`PYTHONPATH=src uv run python -m core.guides`（仓库根目录运行）校验 `community/` 下全部内容，有错误时退出码非 0（给贡献者和将来的 CI 用）。

### Phase B：Agent 接入（分三级，逐级做，见下方"Agent 接入方案"）
- **B1 项目自带 Agent 指令（skills）：已实现。** `.claude/skills/guide-author/SKILL.md`（整理攻略）、
  `.claude/skills/errand-helper/SKILL.md`（问答，写操作先复述确认）；官网填表指引仍待 Phase D。
- **B2 本地 MCP 服务：已实现。** `src/agent_tools/mcp_server.py`（官方 `mcp` SDK，stdio 传输）注册了
  `list_guides`、`get_guide`、`list_tracks`、`get_track`、`set_fact`、`set_step_done`、`confirm_match`、
  `validate_community` 八个工具，逻辑在 `src/agent_tools/tools.py`（直接调用 `src/core`，不经过
  HTTP）；仓库根目录 `.mcp.json` 已配置好项目级 MCP server。不提供删除、不提供读取材料文件内容的工具。
- B3 界面里的"问 Agent"：本地服务调起用户自己安装的 Agent CLI，结果流式显示在页面上。**尚未实现**，
  需要先完成下方"B3 的安全前提"。
- **不在应用里内嵌模型 API**（原 Phase C 方案作废）：Agent 能力来自用户自己本地的 Agent，应用本身不需要 API key、不产生模型费用，也不会把任何内容发给第三方。

### Phase D：官网填表指引（见下方"官网填表指引"）

### Phase C：体验打磨
- 倒排时间（按 `deadline` 和 `duration_days`、`freshness_days` 算每一步最晚/最早什么时候做）。
- 材料库每条记录显示"被哪些 Track 用到"。
- 工作台首页整合 Track 列表，替代 localStorage 版"新建办事"。

## Agent 接入方案（2026-09-23 定方向，B1 → B2 → B3 逐级实现）

Agent 在这个项目里要做三件事：①把杂乱攻略整理成流程攻略；②回答"我这种情况要不要交 X"之类的问题；③在官网上辅助填表。它们都需要"理解"能力，属于 Agent 层；应用本身只提供数据和确定性操作。

| 级别 | 用户怎么用 | 应用要提供什么 | 代价 / 风险 |
|---|---|---|---|
| **B1 项目自带指令** | 在项目文件夹里打开自己的 Claude Code / Codex，说"帮我把这篇攻略整理成流程"，Agent 按项目里的 skill 工作 | `.claude/skills/<名字>/SKILL.md`（需要把 `.gitignore` 里的 `.claude/` 改成只忽略非 skills 部分）；`AGENTS.md` 里写入口说明 | 零基础设施；但要切到终端，不够顺 |
| **B2 本地 MCP 服务** | 同上，但 Agent 不再直接改 YAML，而是调用"列出攻略 / 读我的办事 / 确认材料 / 上传"等工具 | 一个 MCP server，复用 `src/core` 和现有 API 的逻辑；只暴露必要操作，不暴露删除 | Agent 操作变得可靠、可校验；Claude Code、Codex、Cursor 等都能接 |
| **B3 界面里"问 Agent"** | 在办事页面点"问 Agent"，输入问题，回答直接显示在页面里 | 本地服务用子进程调起用户已安装、已登录的 Agent CLI 的非交互模式（例如 Claude Code 的 `claude -p`，只放行 B2 的 MCP 工具），把输出流式推给页面 | 最顺；用的是用户自己的订阅/额度，应用仍不持有任何 key。**安全前提见下** |

B3 的安全前提（实现 B3 之前必须先做）：
- **已实现**（`src/api/app.py` 里的 `anti_csrf` 中间件，测试见 `tests/unit/test_security.py`）：Origin / Sec-Fetch-Site / Host 校验。规则——① 所有请求：`Host` 头去掉端口后必须是 `127.0.0.1` / `localhost` / `::1`（含 `[::1]`）/ `testserver`（TestClient 用）之一，否则 403，防 DNS 重绑定；② 写请求（POST/PUT/PATCH/DELETE）：带 `Origin` 时其 `scheme://host:port` 必须与本次请求 `Host` 对应的源完全一致（正确处理默认端口；`localhost` 与 `127.0.0.1` 视为不同源），带 `Sec-Fetch-Site` 且值为 `cross-site` 或 `same-site` 时拒绝，两个头都没有（curl、本机 Agent 进程）则放行；③ GET/HEAD/OPTIONS 只做①。
  **威胁模型**：防的是"浏览器里的恶意网页对本机服务发起的请求"（CSRF）和"域名被解析劫持指向本机"（DNS 重绑定）；不防本机上其他能直接发 HTTP 请求的进程（curl、本地脚本、本地 Agent 进程）——这些请求本来就在信任边界内，是 B2/B3 依赖的正常路径。
- Agent 只能用白名单里的工具；任何写文件、上传、提交表单的动作都要在页面上由用户点确认。
- 在 B3 做好之前，页面上可以先放"复制给 Agent"按钮：把当前办事的上下文（攻略 id、下一步、缺哪些材料）拼成一段提示词，用户粘贴到自己的 Agent 里。

## 官网填表指引（Phase D，方向已定，数据结构待细化）

观察：大多数签证流程都是"官网填表"+"准备材料"两大块，区别只在递交是线上还是线下。材料这一块由现有的流程攻略负责；填表这一块新增**填表指引**：`community/forms/<form-id>.yaml`，被攻略里的步骤引用（step 新增可选字段 `form: <form-id>`）。

填表指引记录的是**表单的结构**，不含任何人的答案：官网地址；按页面顺序列出每个字段——页面上的原文标签、中文解释、该怎么填（例如"按护照上的拼音填，姓在前"）、答案来自哪里（个人资料的哪个字段 / 哪个 fact / 需要自己写）、常见坑。

怎么得到这份结构：
- **人工看网页源代码不可行**：签证表单通常要登录、分很多页、字段随前面的回答动态出现，源代码里看到的是一堆标记，不是填表流程。
- **推荐由 Agent 带着浏览器走一遍**（呼应 `docs/SPEC-mvp.md` 第 2 条"探索一次、复用多次"）：用户自己登录官网，Agent 逐页读字段、记录结构，写成填表指引；**只记结构，不记录用户填的任何值**；到签名、付款、提交之前一律停下。记录一次，所有人复用。
- 之后的"辅助填表"（MVP 第 2 项）在同一份指引上工作：读用户本机的个人资料，逐页填入，提交前让用户确认。

## Phase A 验收标准

- [ ] `uv run pytest tests/` 全部通过，新增测试覆盖：攻略校验规则每条至少 1 个"违规被拒绝"用例；词表别名冲突（含规范化后冲突）被拒绝；六种需求状态各至少 1 个用例（含组合类型缺一个 part 判 `missing`）；`ask_if` 不满足时相关需求判 `not_applicable`；"下一步"在有依赖、依赖不生效、全部完成三种情况各 1 个用例。
- [ ] `PYTHONPATH=src uv run python -m core.guides` 对仓库现有 `community/` 内容输出 0 个错误、退出码 0。
- [ ] 本地服务启动后，浏览器打开 `/guides.html`：能看到申根攻略 → 开始办 → 回答"身份：在职"后只剩在职相关材料 → 勾选一个步骤后刷新页面仍保持勾选 → 能确认一条材料匹配。
- [ ] `git ls-files community` 列出的文件里没有真实姓名、证件号、金额；Track 文件只出现在材料根目录下。

## 明确不做

- 不自动爬取小红书/知乎；输入一律由贡献者自己提供。
- 不做模糊字符串匹配。
- 不自动解决原始资料之间的冲突。
- 不在应用内调用模型 API（见 Phase B）。

## 待决问题（不要擅自决定，先提方案）

- **`where` 随某个 fact 变化**（例如申请国不同，预约网站不同）：暂不支持，观察更多攻略后再定。
- **填表指引的具体字段**：Phase D 开始时，先用一个真实官网（候选：澳大利亚 ImmiAccount 访客签证 600、法国 France-Visas）走一遍，再定格式。
- **攻略版本**：攻略被修订后，已有 Track 是否要提示"攻略有更新"、是否允许锁定旧版本。Phase A 只做"忽略已不存在的条目"。
- **个人材料索引的位置**：`materials_index/records/` 目前在仓库里（只含元数据）。项目转为公开的共同维护仓库后，个人材料索引应迁出到材料根目录，否则每个贡献者都会把自己的材料元数据提交上来。迁移方案单独讨论。
