# 004 界面里的 Agent：从帖子新建攻略 + 简单追问

- **状态**：项目主已确认（2026-09-28）。第 1 步（地基 + 只读追问）已完成，见文末"进展"
- **对应**：路线图第 5 项；spec 002"Agent 接入方案"里的 B3
- **前提（已具备）**：本地服务的防跨站请求校验（spec 002"B3 的安全前提"）；MCP 工具（`src/agent_tools/mcp_server.py`）；skill `xhs-reader`、`guide-author`

## 与已有文档的关系

- 攻略的数据结构、抽取规则、校验命令：不变，仍以 `specs/002-guide-to-track/spec.md` 和 `prompt.md` 为准。
- 读小红书的方式：不变，按 `.claude/skills/xhs-reader/SKILL.md`（不登录、一次最多 6 条）。
- 本 spec 只规定：界面上怎么调起 Agent、Agent 能动什么、用户怎么确认。

## 名词解释（给新手）

- **Claude Code 命令行（CLI）**：在终端里运行的 `claude`。它可以被别的程序调用：`claude -p "问题"` 表示"问一句、答完就退出"（非交互模式）。
- **子进程**：本地服务在后台启动的另一个程序。这里就是本地服务替你运行 `claude -p ...`。
- **流式输出**：Agent 边干活边把进度一条条传回页面（"正在读第 2 篇…"），不用等全部做完。页面用 SSE（服务器推送事件）接收。
- **草稿**：Agent 整理出来、还没被你保存进攻略库的攻略文件。

## 已定的决定（2026-09-28 项目主确认）

1. **主要用途是"从帖子新建攻略"**，其次是简单追问。界面优先服务前者。
2. **界面形式**：右侧抽屉 + 快捷按钮。每页右下角一个「问 Agent」按钮；抽屉顶部是和当前页面相关的快捷按钮，下面可以自由输入。
3. **Agent 在本机运行**：本地服务调起用户自己已安装、已登录的 Claude Code CLI。项目**不保存任何 API key**，用量算在用户自己的订阅里。
4. **不加 API key 模式**（第一版）：记入 BACKLOG。调起 Agent 的代码写成可替换的一层（见"模块划分"），以后加 API 或其他 Agent 只换这一层。
5. **三类写操作，三种确认方式**：

   | 类别 | 例子 | 方式 |
   |---|---|---|
   | ① 写共享区 | 新建攻略、给词表加别名 | Agent 只能写**草稿**；页面预览，用户点「保存到攻略库」才写进 `community/`；词表别名逐条勾选。**不自动 git 提交** |
   | ② 改自己的办事进度 | 勾步骤、回答问题、隐藏步骤、加备注 | 直接改；抽屉里显示"已勾上：递交材料 [撤销]" |
   | ③ 改基本信息 | 更新手机号 | 弹确认卡片（旧值 → 新值），点确认才写入 |

6. **先做这件事，再公开仓库**（路线图第 7 项）。
7. **实验已通过（2026-09-28）**：`claude -p --chrome` 在后台运行时能调用 Claude in Chrome 工具（17 秒返回）。一次很小的调用，CLI 报告的 `total_cost_usd` 约 0.5（每次都要加载项目上下文）；新建一份攻略预计是它的数倍。
8. **计费**：用 claude.ai 账号登录（订阅）时，`total_cost_usd` 只是按 API 价格折算的参考数，**不另外收费**，计入订阅的用量额度；和在终端里用是同一个账号、同一份额度。区别只在于每次新任务都重新加载上下文，所以追问要接着同一个会话（`--resume`），不要每句都新开。**风险**：如果环境里设置了 `ANTHROPIC_API_KEY`，CLI 会改走 API 按量扣费——`/api/agent/status` 要报告登录方式，界面据此提示（见"没装 Claude Code 时"一节后的"登录方式提示"）。

## 界面

### 抽屉（`guides.html`、`my.html` 两个页面都有）

```
┌──────────────────────────┬───────────────────┐
│ （原页面，不变）            │ Agent         ✕   │
│                          │ ───────────────── │
│                          │ [快捷按钮 1]       │
│                          │ [快捷按钮 2]       │
│                          │ ───────────────── │
│                          │ 对话 / 进度 / 卡片  │
│                          │                   │
│                 [问Agent] │ [输入…        ⏎] │
└──────────────────────────┴───────────────────┘
```

各页面的快捷按钮（第一版）：

| 页面 | 快捷按钮 |
|---|---|
| 攻略库首页 | 「从帖子新建攻略」 |
| 攻略详情 / 草稿预览 | 「按我说的修改这份草稿」（仅草稿）、「这份攻略说了什么」 |
| 我的办事 | 「我还缺什么？」「下一步做什么？」 |
| 我的资料 → 基本信息 | 「查查我的基本信息还缺什么」 |

抽屉知道当前页面是哪份攻略 / 哪件办事，把 id 作为上下文传给 Agent。

### 新建攻略的流程

1. **输入**：抽屉切到"新建攻略"。一个大文本框，可以粘贴：小红书分享文字（含链接）、帖子正文、或别的网页文字；可选填"这是关于什么的"（例如"在美 F-1 办阿根廷签证"）。按钮「开始整理」。
   - 链接超过 6 条时，按钮不可点，提示"一次最多 6 条"。
2. **进度**：抽屉里显示阶段清单，每完成一步打勾：`读取帖子（2/5）→ 整理 → 校验 → 完成`；有「取消」按钮。出错或遇到验证码时停下，显示原因。
3. **结果**：页面跳到草稿预览（和正式攻略的详情页长得一样，顶部有"草稿"横幅），抽屉里显示：
   - 校验结果（✓ / ✗ 及错误）
   - "词表认不出的叫法"及 Agent 的建议，每条一个勾选框（默认不勾）
   - 攻略里的 `uncertain` 和 `conflicts` 摘要
   - 按钮：「保存到攻略库」（校验有 ✗ 时不可点）、「丢弃草稿」；输入框可以继续说"把第 3 步拆开"之类，Agent 修改同一份草稿
   - 本次用量（折合美元，来自 CLI 的 `total_cost_usd`；订阅用户计入额度）
4. **保存后**：提示"已保存到攻略库，还没提交到 git"。git 提交仍在终端里做（按 AGENTS.md 逐文件检查）。

### 追问（简单问答）

- 点快捷按钮或输入问题，回答流式显示在抽屉里。
- 同一个抽屉里的后续提问接着同一次对话（CLI 的 `--resume <session_id>`）；关闭抽屉或切换页面后重新开始。
- Agent 做了 ② 类修改时，抽屉里出现一行"已勾上：递交材料 [撤销]"，页面内容同时刷新。
- Agent 想做 ③ 类修改时，抽屉里出现确认卡片；用户点「确认修改」后才写入。

### 没装 Claude Code 时

`/api/agent/status` 返回不可用时，「问 Agent」按钮仍在，但抽屉里显示：①"没有检测到 Claude Code，装好并登录后刷新本页"及安装说明链接；②「复制给 Agent」按钮：把当前上下文（页面、攻略 / 办事 id、要做的事、应读的 skill）拼成一段提示词复制到剪贴板，用户粘贴到自己的 Agent 里。

### 登录方式提示

`/api/agent/status` 另外返回 `auth_method`（来自 `claude auth status`：`claude.ai` 订阅 / API key / 未登录）和 `api_key_env`（环境里是否设置了 `ANTHROPIC_API_KEY`，只报告有没有，**不读取、不返回它的值**）。
- 订阅登录：抽屉里用量显示为"本次折合约 $X（订阅用户计入额度，不另收费）"。
- 走 API key：抽屉顶部常驻黄色提示"当前按 API 用量计费，会产生实际费用"，第一次开始任务前要用户点一次「我知道了」。
- 未登录：按"没装 Claude Code 时"处理，提示先在终端里运行 `claude` 登录。

## Agent 能动什么（权限）

后台调起的 Agent **只能**使用下面的工具（`--allowedTools` 白名单，其余一律拒绝；`--permission-mode` 为不弹权限询问的模式，未列入白名单的直接拒绝）：

| 任务 | 允许的工具 |
|---|---|
| 新建 / 修改攻略 | `Read`（读仓库里的规则和词表）；Claude in Chrome 读取类工具（`tabs_context_mcp`、`tabs_create_mcp`、`navigate`、`javascript_tool`、`computer` 的截图、`get_page_text`、`tabs_close_mcp`）；新增 MCP 工具 `save_guide_draft`、`validate_guide_draft` |
| 追问 | `Read`；现有 MCP 读取工具；② 类写工具（`set_step_done`、`set_fact`、`set_hidden`、`set_note`、`add_pitfall`、`add_custom_step`、`add_custom_material`、`confirm_match`）；③ 类只允许"提议"工具 `propose_profile_update` |

- **不给** `Write`、`Edit`、`Bash`：Agent 不能直接写任何文件、不能跑命令。攻略只能通过 `save_guide_draft` 写进草稿区；校验通过 `validate_guide_draft` 做。
- 新建攻略时浏览器必须是**未登录**小红书的状态，规则照搬 `xhs-reader`；Agent 发现已登录就停止并报告。
- 调用时加 `--max-budget-usd`（默认 5，可在 `config.yaml` 的 `agent.max_budget_usd` 调整），超出即停止。

## 数据与存储

- **草稿区**：`<材料根目录>/drafts/guides/<id>.yaml`。放在材料根目录（被 git 忽略），因为草稿还没经过用户检视，不能进仓库。
- **发布**：`POST /api/guide-drafts/{id}/publish` 由本地服务（确定性代码，不是 Agent）完成：重新校验 → 通过则写到 `community/guides/<id>.yaml` → 删除草稿。
- **词表别名**：Agent 在草稿结果里给出建议 `[{raw_name, suggest_key}]`；用户勾选后由 `POST /api/vocab/aliases` 写进 `community/material_types.yaml`（确定性代码：追加到对应 key 的 `aliases`，然后重新加载校验；撞名则整体拒绝）。**第一版只支持"加别名到已有 key"**，新增 key 仍在终端里做。
- **② 类修改的撤销记录**：`<材料根目录>/agent/activity.jsonl`，每行一次写操作：时间、工具名、参数、修改前的值。`POST /api/agent/undo/{activity_id}` 按记录恢复。只保留最近 200 条。
- **③ 类提议**：`<材料根目录>/agent/pending-profile.json`，`propose_profile_update` 只写这里；用户确认后由 `POST /api/agent/profile-proposals/{id}/confirm` 调用现有的基本信息写入逻辑。

## 接口（新增）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/agent/status` | `{available, cli_path, cli_version, auth_method, api_key_env}`：检测 `claude` 是否在 PATH 里、能否运行、用什么方式登录 |
| POST | `/api/agent/jobs` | 开始一次任务：`{kind: "create_guide" \| "edit_draft" \| "ask", context: {page, guide_id?, track_id?, draft_id?}, input: 文本, session_id?}` → `{job_id}`。同一时间只允许 1 个任务在跑，否则 409 |
| GET | `/api/agent/jobs/{job_id}/events` | SSE 事件流：`progress`（阶段、说明）、`text`（回答文字片段）、`activity`（② 类修改，含撤销 id）、`proposal`（③ 类提议）、`draft`（草稿 id + 校验结果 + 别名建议）、`done`（`session_id`、用量）、`error` |
| POST | `/api/agent/jobs/{job_id}/cancel` | 结束子进程 |
| POST | `/api/agent/undo/{activity_id}` | 撤销一条 ② 类修改 |
| POST | `/api/agent/profile-proposals/{id}/confirm` · `/reject` | 处理 ③ 类提议 |
| GET | `/api/guide-drafts/{id}` | 草稿预览（格式同 `GET /api/guides/{id}`，多一个 `draft: true`） |
| POST | `/api/guide-drafts/{id}/publish` | 发布；已存在同名攻略时 409（第一版不支持覆盖） |
| DELETE | `/api/guide-drafts/{id}` | 丢弃草稿 |
| POST | `/api/vocab/aliases` | `[{key, alias}]`，全部成功或全部失败 |

所有写接口沿用现有的防跨站请求中间件。

## 模块划分（给执行 Agent）

- `src/agent_runner/`（新）：
  - `cli.py`：拼 `claude` 命令行（`-p`、`--output-format stream-json`、`--include-partial-messages`、`--allowedTools`、`--permission-mode`、`--max-budget-usd`、`--resume`、新建攻略时加 `--chrome`）；**只有这里知道具体是哪个 CLI**，以后换 API / 其他 Agent 就换这个文件。
  - `jobs.py`：启动 / 取消子进程，把 stream-json 逐行解析成上面的 SSE 事件；一次只跑一个。
  - `prompts.py`：各类任务的提示词模板（指向 `xhs-reader`、`guide-author` skill，写明只能用草稿工具、最后要调用 `validate_guide_draft`）。
- `src/core/drafts.py`（新）：草稿的读写、校验、发布（确定性，可单测）。
- `src/agent_tools/`：新增 `save_guide_draft`、`validate_guide_draft`、`propose_profile_update`；② 类写工具在"界面模式"（环境变量 `PA_AGENT_ACTIVITY_LOG` 指向日志文件）下记录撤销信息。
- `src/api/app.py`：上面的新接口。
- `web/assets/agent-drawer.js` + `agent-drawer.css`（新）：抽屉，两个页面共用。
- **不改**：攻略数据结构、`community/` 里已有的攻略、`xhs-reader` / `guide-author` 的规则本身（提示词里引用它们）。

## 分步实现

1. **地基**：`agent_runner`（含假 CLI 测试）、`/api/agent/status`、jobs + SSE、抽屉外壳 + 追问（只放行读取工具）。
2. **新建攻略**：草稿区、`save_guide_draft` / `validate_guide_draft`、草稿预览、发布、别名勾选。
3. **写操作**：② 类撤销、③ 类确认卡片、快捷按钮补全、没装 CLI 时的「复制给 Agent」。

每一步做完都能单独用，单独提交、单独合并。

## 验收标准（可机械检查）

自动测试（用一个假的 `claude` 脚本代替真 CLI，按预设输出 stream-json；**测试里不调用真的 Claude**）：

1. PATH 里没有 `claude` 时，`GET /api/agent/status` 返回 `available: false`；有假脚本时返回 `true`。设置了 `ANTHROPIC_API_KEY` 时 `api_key_env` 为 `true`，且响应里任何地方都不出现这个变量的值。
2. `cli.py` 生成的命令行：包含 `-p`、`--output-format stream-json`、`--max-budget-usd`；`--allowedTools` 里**不含** `Write`、`Edit`、`Bash`；`create_guide` 任务含 `--chrome`，`ask` 任务不含。
3. 第一个任务没结束时再 `POST /api/agent/jobs` 返回 409；`cancel` 后子进程已退出，事件流以 `error`（原因"已取消"）结束。
4. 假 CLI 输出的工具调用和文字，在 SSE 里按顺序变成 `progress` / `text` / `done` 事件；`done` 带 `session_id` 和用量。
5. `save_guide_draft` 只写 `<材料根目录>/drafts/guides/`：id 不符合 `^[a-z0-9-]+$` 时拒绝；测试结束后 `community/` 目录没有任何变化。
6. 发布：草稿有 ✗ 时 422 且 `community/guides/` 不变；同名攻略已存在时 409；成功后 `community/guides/<id>.yaml` 内容与草稿一致、草稿被删除。
7. 别名：加到不存在的 key 或与其他 key 的别名撞名时 422，`material_types.yaml` 内容不变；成功后校验命令退出码为 0。
8. ② 类：通过 MCP 工具勾上一个步骤 → 活动日志多一条 → `undo` 后步骤恢复未勾选。
9. ③ 类：`propose_profile_update` 之后基本信息文件内容不变；`confirm` 之后变更生效；`reject` 之后提议被删除。
10. 来自其他网站的写请求（带跨站 `Origin`）访问所有新写接口都返回 403。
11. 原有测试全部通过；`PYTHONPATH=src uv run python -m core.guides` 退出码为 0。

人工验收（项目主）：

12. 在界面里粘贴 3–5 条真实小红书分享文字，从「开始整理」到「保存到攻略库」全程不打开终端，得到一份校验通过的攻略；期间没有要求登录小红书、没有手动关弹窗。
13. 在一件办事里问"我还缺什么"，回答和页面上的材料进度一致；让 Agent 勾一个步骤，再点「撤销」能恢复。

## 以后再说

- API key 模式、其他 Agent（Codex 等）的适配：见 BACKLOG。
- 旅游攻略（行程、景点、预算）：同一套"杂乱帖子 → 结构化"的流程，但数据结构不同，见 BACKLOG。
- 新增词表 key、在界面里做 git 提交：第一版不做。

## 进展

- **第 1 步完成（2026-09-28）**：`src/agent_runner/`（`cli.py` / `jobs.py` / `prompts.py`）、`/api/agent/status`、`/api/agent/jobs`（+ SSE 事件流、取消）、抽屉 `web/assets/agent-drawer.{js,css}`（两个页面都有，快捷按钮按页面变化，只读）。自动测试 12 条（`tests/unit/test_agent_runner.py`，用假 CLI `tests/unit/fake_claude.py`）覆盖验收 1–4、10。
  - 真机检查：在申根办事页点「我还缺什么？」，约 15 秒流式给出基于真实数据的回答（还指出了"步骤已勾完成、但申请表和预约单还没登记"的不一致），折合约 $0.39；接着追问"你刚才说的第一项…"能接上前文。
  - 发现：后台 Claude 会先调用 `ToolSearch` 加载 MCP 工具（工具是按需加载的），不在白名单里也能用，属于 CLI 自带、不涉及读写数据。

