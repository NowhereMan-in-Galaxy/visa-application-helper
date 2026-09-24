# 并行任务第 1 批（2026-09-23）

四个任务由四个执行 Agent 在各自的 git worktree（独立分支）里**同时**完成，最后由协调 Agent 合并。任务之间刻意按文件划开，**只改自己任务列出的文件**；确实需要改别的文件时，只做最小改动并在最终报告里说明。

## 所有任务共同的硬规则

1. 先读 `AGENTS.md`、`specs/002-guide-to-track/spec.md`，再读本文件里自己的任务。
2. **不碰真实数据**：不修改、不新增、不删除 `materials_index/records/`、`materials_index/applications/`、`materials/` 下的任何文件；测试一律用 `tmp_path` + monkeypatch（参考 `tests/unit/test_tracks_api.py` 的 `isolated` fixture）。
3. 前端动态文本只用 `textContent` / `createElement`，**禁止 `innerHTML`**；沿用 `web/assets/guides.css` 的颜色令牌和视觉风格。
4. Python 环境只用 `uv`（`uv run`、`uv add`），不用 pip。
5. 完成标准：`uv run pytest tests -q` 全部通过；`PYTHONPATH=src uv run python -m core.guides` 退出码 0。
6. 在自己的分支上提交，Conventional Commits 风格，一个意图一个提交，**不 push、不 merge、不改写历史**。提交信息末尾加：`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。
7. 最终报告（中文）：改了哪些文件、新增了哪些接口/函数、测试数量、没做完或偏离规格的地方。

---

## 任务 A：新版界面的「02 我的资料」

**目标**：在新版界面里维护个人材料库和出行记录，不再需要跳去旧页面。

**可以改的文件**：新建 `web/my.html`、`web/assets/my.js`、`web/assets/my.css`；`web/guides.html` 只改侧边栏 `<nav>`；`src/api/app.py` 只**新增**下面列出的接口（放在"流程攻略"那一段之前）；新建 `tests/unit/test_my_api.py`。

**侧边栏**（`guides.html` 和 `my.html` 完全一致）：`01　攻略与办事` → `/guides.html`；`02　我的资料` → `/my.html`；`03　旧版材料维护` → `/index.html`；`04　旧版工作台` → `/workbench.html`。当前页高亮。

**`my.html` 页面内容**：
1. **材料库**：按 `category` 分组，组顺序和中文名：`passport_scan` 证件、`financial_snapshot` 财务、`employment_doc` 工作、`id_photo` 证件照、`other` 其他。每条记录一行/一卡，显示：`type`（+ `sublabel`）、状态徽章（`已备齐 / 待补 / 即将过期 / 已过期`，颜色沿用 guides.css 的 `state-*` 思路）、`obtained_date`、是否有文件、**"用在：<办事标题>、…"**（没有则不显示）。`id` 以 `example-` 开头的记录加"示例"标签。
2. 每条记录有"编辑"：可改 `type`、`sublabel`、`obtained_date`、`validity_days`；保存调用 PATCH 接口，成功后刷新列表。PDF 记录保留"追加新页"（调用已有 `POST /api/materials/{id}/append-page`）。
3. **新增材料**：表单字段 `category`（下拉，5 类）、`type`（文本框 + `<datalist>`，候选来自 `GET /api/material-types`）、`obtained_date`（必填）、`sublabel`（可选）、`file`（可选）；调用已有 `POST /api/materials`。
4. **出行记录**：表格（国家、入境、离境、目的），可新增、可编辑，调用已有 `GET /api/personal-profile`（**只读 `travel_history`**）、`POST /api/personal-profile/travel-history`、`PUT /api/personal-profile/travel-history/{index}`。**不展示姓名、证件号等其他个人资料字段**（SPEC-mvp §0 的约束）。
5. 顶部一行汇总：共 N 份材料，其中过期 x 份、即将过期 y 份。

**新增接口**：
- `GET /api/material-types` → `[{key, name, category}]`，来自共享词表。
- `GET /api/materials/usage` → `{"<record_id>": [{"track_id", "track_title", "requirement_name"}]}`。只统计各 Track `matches` 里**已确认**的记录；攻略无效的 Track 跳过。
- `PATCH /api/materials/{id}`，JSON body 可含 `type`、`sublabel`、`obtained_date`、`validity_days`（未提供的字段不变；`sublabel`/`validity_days` 传 `null` 表示清空）；`type` 不能为空字符串（422）；记录不存在 404；用 `core.storage.overwrite_material_record` 写回；返回 `MaterialView`。

**验收**：`test_my_api.py` 覆盖三个新接口的正常路径和 404 / 422；浏览器打开 `/my.html` 能看到分组材料和出行记录，编辑一条材料后刷新仍然生效（用临时数据验证即可，不得改动真实记录）。

---

## 任务 B：本地服务防跨站请求（CSRF）与 DNS 重绑定

**背景**：本地服务没有鉴权，用户浏览器里打开的任何网站都能向 `127.0.0.1:8000` 发写请求。这是 spec 002 "Agent 接入方案" 里 B3 的安全前提。

**可以改的文件**：`src/api/app.py`（只新增一个中间件，放在已有的 `no_stale_frontend` 中间件旁边）；新建 `tests/unit/test_security.py`；`specs/002-guide-to-track/spec.md` 只改"B3 的安全前提"那几条；`README.md` 的"本地跑起来"一节可加一句"不要用 `--host 0.0.0.0`"。

**规则**（全部在一个中间件里实现，被拒绝时返回 403 JSON `{"detail": "<中文原因>"}`）：
1. **所有请求**：`Host` 头去掉端口后必须是 `127.0.0.1`、`localhost`、`[::1]`（或 `::1`）、`testserver`（TestClient 用）之一，否则 403。防 DNS 重绑定。
2. **写请求**（方法为 POST / PUT / PATCH / DELETE）：
   - 有 `Origin` 头时，其 `scheme://host:port` 必须与本次请求的 `Host` 对应的源一致，否则 403。
   - 有 `Sec-Fetch-Site` 头且值为 `cross-site` 或 `same-site` 时 403（注意 `localhost:3000` 对 `localhost:8000` 算 same-site，也要拦）。
   - 两个头都没有（curl、TestClient、本地 Agent 进程）→ 放行。
3. GET / HEAD / OPTIONS 只做规则 1。

**验收**：`test_security.py` 至少覆盖：跨站 Origin 的 POST 被拒；同源 Origin 放行；`Sec-Fetch-Site: cross-site` 被拒；`same-site` 被拒；`same-origin` 放行；无 Origin 放行；`Host: evil.example` 的 GET 被拒。已有全部测试仍通过。spec 里 B3 前提改写为"已实现（Origin / Sec-Fetch-Site / Host 校验）"，并注明威胁模型：防的是浏览器里的恶意网页，不防本机其他进程。

---

## 任务 C：本地 Agent 接入（spec 002 Phase B 的 B1 + B2）

**可以改的文件**：`.gitignore`；新建 `.claude/skills/guide-author/SKILL.md`、`.claude/skills/errand-helper/SKILL.md`；新建 `src/agent_tools/__init__.py`、`src/agent_tools/mcp_server.py`、`src/agent_tools/tools.py`；新建仓库根目录 `.mcp.json`；`pyproject.toml` / `uv.lock`（通过 `uv add mcp`）；新建 `tests/unit/test_agent_tools.py`；`README.md` 新增一节"用本地 Agent"；`specs/002-guide-to-track/spec.md` 只改 "Phase B" 列表，标注 B1/B2 已实现。

**B1 skills**：
- `.gitignore` 里的 `.claude/` 改成只忽略非 skills 部分（`.claude/*` 加 `!.claude/skills/`），并用 `git check-ignore` 自查 `.claude/settings.local.json` 仍被忽略、`.claude/skills/guide-author/SKILL.md` 不被忽略。
- `guide-author`：把用户给的攻略（文字/截图/链接内容）整理成 `community/guides/<id>.yaml`。正文必须要求：先读 `specs/002-guide-to-track/prompt.md` 和 `community/material_types.yaml`；按 prompt 的全部规则；写完运行 `PYTHONPATH=src uv run python -m core.guides`，有 ✗ 就改到全部 ✓；词表认不出的叫法列出建议、等用户确认后才改词表；**不写任何个人信息**；最后提醒用户打开 `/guides.html` 检视。frontmatter 的 `description` 写清触发场景（中文）。
- `errand-helper`：回答"我这件事下一步做什么 / 我要不要交 X / 还缺什么"。优先通过 MCP 工具读取；**任何写操作（改回答、勾步骤、确认材料）先向用户复述并得到同意**；不读取材料文件内容。

**B2 MCP 服务**（官方 `mcp` Python SDK，stdio 传输）：
- `tools.py` 放纯函数（便于测试），`mcp_server.py` 只负责注册。所有函数直接调用 `src/core` 和 `config`，不经过 HTTP。
- 工具：`list_guides()`、`get_guide(guide_id)`（返回攻略 + 预览视图）、`list_tracks()`、`get_track(track_id)`（返回 `TrackView` 的 JSON）、`set_fact(track_id, fact, value)`（`value` 为 null 清除；非法选项报错）、`set_step_done(track_id, step_id, done)`、`confirm_match(track_id, requirement_id, confirmed)`、`validate_community()`（返回与命令行校验相同的结果结构）。写操作之后要调用 `core.tracks.sync_completion`，与 API 行为一致。**不提供删除、不提供读取材料文件内容的工具。**
- 启动：`PYTHONPATH=src uv run python -m agent_tools.mcp_server`；`.mcp.json` 按 Claude Code 项目级 MCP 配置格式写好这条命令（`env` 里设置 `PYTHONPATH=src`）。

**验收**：`test_agent_tools.py` 用 tmp 目录覆盖每个工具至少一个正常用例，`set_fact` 非法值、不存在的 track 各一个错误用例；`uv run python -c "import agent_tools.mcp_server"`（带 `PYTHONPATH=src`）不报错。

---

## 任务 D：倒排时间（spec 002 Phase C 第一条）

**目标**：Track 设了 `deadline` 时，算出每个步骤"最晚什么时候开始"，并把已经赶不上的标红。

**可以改的文件**：`src/core/tracks.py`；`src/api/app.py` 只新增一个接口（放在其他 `/api/tracks/{id}/...` 接口旁边）；`web/assets/guides.js`（只改步骤信息、阶段卡片、"下一步"卡片、办事页标题区，以及新增截止日期编辑）；`web/assets/guides.css`（只在文件末尾追加）；`tests/unit/test_tracks.py`、`tests/unit/test_tracks_api.py`（只追加）；`specs/002-guide-to-track/spec.md` 的"状态计算"一节追加算法，"Phase C"标注已实现。

**算法**（纯函数，`today` 传入）：
- 只考虑 `applies == "yes"` 且未完成的步骤，记为集合 S；没有 `deadline` 时全部结果为 null。
- 步骤时长 `dur(s)` = `duration_days.max`，没有则为 0。
- 对 S 中的步骤 s：`latest_finish(s)` = S 中所有直接依赖 s 的步骤 d 的 `latest_start(d)` 的最小值；没有这样的 d 时为 `deadline`。`latest_start(s)` = `latest_finish(s) − dur(s)`（按天减）。
- `late(s)` = `today > latest_start(s)`。
- 阶段的 `latest_finish` = 该阶段内 S 中步骤 `latest_finish` 的最大值；阶段内没有 S 中步骤时为 null。
- 例：申根攻略 `deadline = 2026-12-01`，"等出签" `max = 45` → 它的 `latest_start = 2026-10-17`；"递签"的 `latest_finish = latest_start = 2026-10-17`。

**数据**：`StepView` 新增 `latest_start: date | None`、`late: bool`；`PhaseView` 新增 `latest_finish: date | None`。

**接口**：`PUT /api/tracks/{id}/deadline`，body `{"deadline": "YYYY-MM-DD" | null}`，返回 `TrackView`。

**界面**：步骤信息里显示"最晚 M月D日 开始"，`late` 时红色并写"已经晚了 N 天"；阶段卡片显示"最晚 M月D日 完成"；"下一步"卡片在 `late` 时显示醒目提醒；办事页标题区可以设置/修改/清除截止日期（日期输入框 + 保存）。

**验收**：测试覆盖：无 deadline 全为 null；上面的申根例子（用 `community/guides/schengen-tourist.yaml` 真实攻略 + 空材料库计算）；依赖链上的传递；已完成步骤不参与；`late` 判断；阶段 `latest_finish`；API 设置和清除 deadline。
