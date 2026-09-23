# Feature Specification: 攻略 → 办事流程（Track）

**Created**: 2026-09-23

**Status**: Draft（数据结构已定，Phase A 可以开始实现）

**Input**: 项目主的产品思考（2026-09-23 对话）：签证/办事这类行政流程繁琐、让人焦虑。三个痛点：①不同事情反复提交同样的基础材料；②收藏了网上攻略，但自己对照着准备依然很慢；③最难的一步是弄清楚"到底要办什么"。解决思路：用 AI 把非结构化的攻略（图文）解析成结构化的"办事流程（Track）"，匹配材料库实现复用，最后产出一份照着做就行的清单。项目主将该方向的具体设计全权委托给协作 Agent 决定。

## 与已有文档的关系

- **取代并扩展** `specs/001-visa-material-hub/spec.md` 的 User Story 2（"用自然语言/图片生成材料清单"）。差别：001 US2 只产出"材料清单"，且只服务签证；本 spec 产出"步骤 + 材料"的完整流程，适用于任何办事类别（签证 / 工作 / 社保 / 银行补贴 / 其他），输入不只是官网说明，也包括小红书/知乎等攻略。001 US3（为缺失材料建文件夹）不受影响，之后改为依赖本 spec 的 Track 输出。
- **遵守** `docs/SPEC-mvp.md` 第 2 条（核心库 vs Agent 层）：AI 只负责"读懂攻略"和"不认识的材料名归类"两件事，产出落成 YAML 文件；之后的匹配、状态、倒排时间、清单渲染全部是确定性代码，不再调用模型。
- **遵守** `AGENTS.md` 第 3 条：攻略原文放材料根目录（仓库外）；仓库里的 Track 只存结构和不超过 60 字的原文摘录。

## 核心概念（给新手的解释）

- **攻略（Guide）**：你收藏的一篇图文，可能是小红书截图、知乎长文、官网页面。内容杂乱，步骤和材料混在一起。
- **办事流程（Track）**：从一篇或多篇攻略里整理出来的、结构化的"要做哪几步、每步需要什么材料"。一件具体要办的事（例如"2026 年底办日本旅游签"）对应一个 Track。
- **材料需求（Requirement）**：Track 里的一条"需要某种材料"，例如"近 6 个月银行流水"。它**不是**材料本身，而是对材料的要求。
- **材料记录（MaterialRecord）**：001 里已有的概念，是你手上真实的一份材料（的元数据）。
- **匹配**：把"需求"和"记录"连起来。连上了就是"已有"，这就是"材料复用"的实现方式——同一份护照记录可以同时满足三个 Track 的需求，不用录三遍。
- **材料类型词表**：一份"标准材料名 + 各种叫法"的对照表，例如标准名"在职证明"，叫法有"工作证明""单位证明""employment letter"。匹配靠它把五花八门的叫法对齐。

## 数据流总览

```
攻略原文（文字/截图/链接）
   │  ① AI 抽取（Agent 层，每篇攻略只做一次）
   ▼
Track 草稿（YAML，status: draft）── 用户逐条确认/修改 ──▶ Track（status: active）
   │
   │  ② 需求 → 材料类型：先查词表（代码）；查不到才问 AI，
   │     AI 的建议经用户确认后写回词表，下次不再问
   ▼
   ③ 需求 → 材料记录：纯代码（按材料类型 + 新鲜度规则）
   ▼
   ④ 清单 / 下一步 / 倒排时间：纯代码渲染
```

## 数据结构（已定，执行 Agent 按此实现，不要自行增删字段）

### 1. Track 文件：`materials_index/tracks/<track-id>.yaml`

示例（全部虚构）：

```yaml
id: example-japan-tourist-2026          # 小写字母/数字/连字符；example- 前缀表示示例数据
title: 日本单次旅游签证
category: 签证                           # 签证 | 工作 | 社保 | 银行补贴 | 其他
status: active                           # draft（AI 刚生成，未经用户确认）| active | done | archived
deadline: 2026-12-01                     # 可选；整件事最晚完成日期
application_id: null                     # 可选；关联 001 的 VisaApplication.id，非签证类留空

sources:                                 # 这个 Track 从哪些攻略整理出来
  - id: g1
    title: 上海送签日本单次旅游签全流程
    url: https://example.com/post/123    # 可选，仅 http/https
    guide_ref: guides/japan-visa-g1.md   # 可选；相对材料根目录的路径，原文存仓库外

requirements:
  - id: r-bank
    material_type: bank_statement        # 必须是词表里的 key；词表查不到时填 null 并在 raw_name 留原叫法
    raw_name: 近半年银行流水              # 攻略里的原叫法
    freshness_days: 30                   # 可选；递交时该材料开具不能超过多少天（机械可判断）
    note: 需覆盖近 6 个月，余额建议 5 万以上   # 可选；无法机械判断的要求写这里
    matched_record: null                 # 匹配到的 MaterialRecord.id；null 表示缺
    match_confirmed: false               # 用户是否确认过这个匹配
    evidence: [{source: g1, quote: "流水要近半年的，我是交材料前一周去打的"}]

steps:
  - id: s-bank
    title: 去银行打流水
    where: 线下 · 任意支行柜台            # 自由文本：线下地点 / 网站地址 / App 名
    requirements: [r-bank]               # 这一步产出或用到的需求 id
    depends_on: []                       # 必须先完成的 step id
    estimate: 30 分钟                     # 可选，自由文本
    done: false
    evidence: [{source: g1, quote: "…"}]

conflicts:                               # 多篇攻略说法不一致时，原样摆出来，不替用户选
  - about: r-bank.freshness_days
    claims:
      - {source: g1, quote: "一个月内开的就行"}
      - {source: g2, quote: "要求 15 天内"}
    resolution: null                     # 用户选定后写入其结论，例如 "以领馆官网为准：30 天"

uncertain: [r-bank.note]                 # AI 自己没把握的字段路径，前端要提示用户核对
```

规则（可机械检查）：
- `requirements[].id`、`steps[].id`、`sources[].id` 在同一文件内唯一。
- `steps[].requirements`、`steps[].depends_on`、`evidence[].source`、`conflicts[].claims[].source` 引用的 id 必须存在。
- `depends_on` 不能成环。
- `evidence[].quote` 不超过 60 个字符（防止把整篇攻略搬进仓库）。
- `material_type` 非 null 时必须存在于词表；为 null 时 `raw_name` 必填。
- `match_confirmed: true` 时 `matched_record` 必须非 null 且该记录存在。

### 2. 材料类型词表：`materials_index/material_types.yaml`

```yaml
- key: bank_statement
  name: 银行流水
  category: financial_snapshot           # 对应 001 的 MaterialCategory
  aliases: [银行流水, 流水, 银行对账单, bank statement]
- key: employment_letter
  name: 在职证明
  category: employment_doc
  aliases: [在职证明, 工作证明, 单位证明, employment letter]
```

- `key` 全局唯一；任一 alias 只能出现在一个条目里（否则匹配有歧义）。
- 别名比较时忽略大小写和首尾空格，其余必须完全相等（**不做模糊匹配**，模糊的交给 AI + 用户确认）。

### 3. MaterialRecord 新增一个可选字段

`material_type: str | None`——该记录属于词表里的哪个 key。旧记录没有这个字段时，匹配代码用记录的 `type` 字段去词表别名里查，查到即视为该类型。

## 各环节职责

| 环节 | 层 | 输入 → 输出 | 说明 |
|---|---|---|---|
| ① 攻略 → Track 草稿 | Agent | 攻略原文 → `status: draft` 的 Track YAML | Phase A 由 Claude Code 按 `prompt.md` 手动执行；Phase C 才接进网页 |
| ② 原叫法 → 材料类型 | 核心库优先，Agent 兜底 | `raw_name` → 词表 key | 词表命中直接用；未命中才问 AI，用户确认后把新叫法追加进 `aliases` |
| ③ 需求 → 材料记录 | 核心库 | Track + 材料库 → 每条需求的匹配候选 | 同 `material_type` 的记录中，选 `obtained_date` 最新的一条；若设了 `freshness_days` 且截至今天已超期，标为"需重新开具" |
| ④ 清单渲染 | 核心库 | Track + 匹配结果 → 视图数据 | 包括"下一步"（所有依赖都完成、自身未完成的步骤中排最前的一个）和进度（已有/总需求） |

需求的展示状态只有四种，由代码按顺序判定：
1. `missing` 缺：没有任何同类型记录；
2. `stale` 需重新开具：有记录，但设了 `freshness_days` 且记录的 `obtained_date` 距今超过该天数，或记录本身状态是"已过期"；
3. `unconfirmed` 待确认：有合格记录，但 `match_confirmed` 为 false；
4. `ready` 已有：有合格记录且已确认。

## 分阶段计划

### Phase A：数据结构落地 + 手动抽取（不需要 API key）
- `src/core/tracks.py`：Track / Requirement / Step 等 pydantic 模型、读取 `materials_index/tracks/*.yaml`、校验上面"规则"一节的每一条、计算四种需求状态和"下一步"。
- `src/core/material_types.py`：读取词表、别名查找。
- `materials_index/material_types.yaml`：先录入覆盖 001 四大类的常用类型（至少 8 条）。
- `materials_index/tracks/example-japan-tourist-2026.yaml`：虚构示例。
- `specs/002-guide-to-track/prompt.md`：给 Claude Code 用的抽取指令。
- API：`GET /api/tracks`（列表 + 每个 Track 的进度）、`GET /api/tracks/{id}`（完整 Track + 每条需求的状态和候选记录）。
- 用 3 篇以上真实攻略手动跑抽取，记录结构不够用的地方，回来修订本 spec。

### Phase B：前端围绕 Track 重做
- 工作台首页：主操作是"贴攻略"；事项列表 = Track 列表，显示进度"已有 x / 共 y"和"下一步"。
- Track 详情：步骤时间线，每步挂材料状态；冲突和 `uncertain` 字段醒目提示；逐条确认匹配。
- 材料库：每条记录显示"被哪些 Track 用到"。
- 工作台里 localStorage 版"新建办事"改为创建 Track 文件（写接口在本阶段设计）。

### Phase C：网页内接入 AI
- `src/agent/extract_track.py`：调用模型 API，输出必须通过 Phase A 的校验器，否则把错误回喂模型重试最多 2 次，仍失败则展示错误、不写文件。
- 发送给模型的只有攻略原文和词表；**不发送材料记录、个人资料或任何文件内容**。
- API key 放 `config.yaml`（已在 `.gitignore`）。

## Phase A 验收标准

- [ ] `uv run pytest tests/` 全部通过，且新增测试覆盖：规则一节每条规则各有至少 1 个"违规被拒绝"的用例；四种需求状态各有至少 1 个用例；"下一步"在有依赖、无依赖、全部完成三种情况下各有 1 个用例。
- [ ] 示例 Track 能被 `GET /api/tracks/example-japan-tourist-2026` 读出，返回每条需求的 `state` 字段，取值只能是 `missing` / `stale` / `unconfirmed` / `ready`。
- [ ] 词表中任意 alias 重复时，服务启动或加载时报错并指出冲突的两个 key。
- [ ] 至少 3 个由真实攻略抽取出的 Track 通过校验（这些 Track 若含个人信息，只能放材料根目录；仓库里只放虚构示例）。
- [ ] 本 feature 所有改动中不出现真实姓名、证件号、金额。

## 明确不做

- 不做自动爬取小红书/知乎（登录墙、平台规则、维护成本）；输入一律由用户粘贴文字、上传截图或提供链接。
- 不做模糊字符串匹配；认不出的叫法一律走"AI 建议 + 用户确认 + 写回词表"。
- 不自动解决攻略间的冲突。
