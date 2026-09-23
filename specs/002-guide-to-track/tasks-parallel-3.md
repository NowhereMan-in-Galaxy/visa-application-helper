# 并行任务第 3 批（2026-09-23）

共同硬规则同 [`tasks-parallel-1.md`](./tasks-parallel-1.md) 第 1–7 条。协调 Agent 同时在主分支上写后端测试、MCP 工具和文档，**执行 Agent 只改下面列出的文件**。

## 任务 F：办事页的「个人调整」界面

**背景**：后端已经支持隐藏步骤/材料、给步骤/材料加备注、自己加步骤、自己加材料，数据结构和接口见 `spec.md`"### 2. 我的办事"里的"个人调整"一条（已实现、已可调用）。`TrackView` 里相关字段：`steps[].custom / hidden / user_note`、`requirements[].custom / hidden / user_note`、`hidden_items`。

**可以改的文件**：`web/assets/guides.js`、`web/assets/guides.css`（只在文件末尾追加）。不改 API、不改其他文件。

**要做的交互**（只在办事页，攻略预览页 `readonly` 时一律不显示这些操作）：
1. **每个步骤**标题行右侧一个小的"⋯"按钮，点开一行小菜单：`加备注` / `隐藏这一步`；自己加的步骤还有 `改名` / `删除`。菜单同一时间只开一个，点别处或再点一次关闭。
2. **每条材料**卡片右上角同样的"⋯"：`加备注` / `隐藏这项材料`；自己加的材料还有 `改名` / `删除`。
3. **备注**：在步骤/材料下方显示为一块浅色便签（前缀"我的备注："），点它可编辑；编辑用行内输入框 + `保存` / `取消`，保存空内容 = 删除备注（调用 `PUT .../notes/...`）。
4. **自己加的步骤/材料**标一个小标签"我加的"。
5. **加步骤**：每个阶段分组标题（`phase-heading`）右侧一个 `＋ 加一步` 链接按钮，点开行内表单（步骤名必填、地点可选），提交时 `phase` 为该阶段，`after` 为该阶段最后一个可见步骤的 id；没有阶段的攻略在步骤列表末尾放一个同样的按钮。
6. **加材料**：每个步骤的材料列表末尾一个 `＋ 加材料` 链接按钮，点开行内表单（材料名必填、"加分项"复选框），`step` 为该步骤 id。
7. **已隐藏**：步骤面板底部，当 `hidden_items` 非空时显示一个默认折叠的 `<details>`："已隐藏 N 项"，展开后每项一行 + `恢复` 按钮（调用对应的 `hidden` 接口传 `false`）。
8. 删除自己加的步骤前用页面内的确认（例如按钮变成"确认删除？"再点一次），**不要用 `window.confirm` / `alert`**。
9. 所有请求走现有的 `update(v, path, body)` 或同风格的 `request()`，成功后用返回的 `TrackView` 重画（`drawTrack`）；DELETE 用 `request("DELETE", ...)`。错误用 `showError`。

**验收**（机械可查）：
- `node --check web/assets/guides.js` 通过；`uv run pytest tests -q` 全绿。
- 攻略预览页（`#/guide/<id>`）上不出现"⋯"、"＋ 加一步"、"＋ 加材料"。
- 办事页：隐藏一步后它从时间线消失、出现在"已隐藏"里，点恢复后回来；加一步后它出现在对应阶段末尾并带"我加的"；给材料加备注后刷新页面仍显示。
  - 验证方法：在你的 worktree 里启动服务（`uv run uvicorn api.app:app --app-dir src --port 8016`）。worktree 里没有 `config.yaml`，材料根目录默认是 worktree 自己的 `materials/`（被 .gitignore 忽略、和主目录隔离），所以可以放心**新建办事**来测试；但**不要上传文件、不要编辑材料**（那会改动 `materials_index/records/`）。测完关掉服务，删除 worktree 里的 `materials/tracks/`。
- 页面上不出现 "null"、"undefined"、"[object"。
