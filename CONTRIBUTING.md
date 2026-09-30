# 参与有条有理

谢谢你愿意帮忙！下面按"想做的事"分开写，挑你需要的看就行。

## 最重要的一条：不提交任何个人信息

这个仓库是公开的，只放代码、文档和攻略。**姓名、证件号、电话、住址、金额、自己的办事进度、材料扫描件**，一律不能出现在提交里。

示例数据请用明显虚构的值，比如 `ZHANG SAN`、`1 EXAMPLE ROAD`、`zhang.san@example.com`。你自己的资料放在材料根目录（默认是 `materials/`），它已经被 git 忽略了。

## 攻略过时了 / 写错了

最简单的方法是[提一个 issue](../../issues/new/choose)，选"攻略过时了"，写清楚哪一步、官网现在怎么说、官网链接。

会改文件的话，也可以直接修改 `community/guides/` 里对应的 YAML，提交 Pull Request。

## 分享一份新攻略

1. 在有条有理里点「+ 新建攻略」，贴几篇帖子的链接或正文，让 Agent 整理成草稿；也可以在终端里让你自己的 Agent 按 [`specs/002-guide-to-track/prompt.md`](./specs/002-guide-to-track/prompt.md) 整理。
2. 草稿确认没问题后，会保存成 `community/guides/<id>.yaml`。
3. 在项目文件夹里运行校验，全部是 ✓ 才算通过：

   ```bash
   uv run python -m core.guides
   ```

4. 提交 Pull Request，写上资料来源（哪几篇帖子、哪个官网）和资料截至日期。

攻略的写法规则（摘录原话不超过 60 字、说法冲突怎么标……）见 [`community/README.md`](./community/README.md)。

## 报告 bug

[提一个 issue](../../issues/new/choose)，选"出问题了"。写清楚你做了什么、看到了什么、本来期望什么。截图前请遮住个人信息，或者用 `uv run youtiao --demo` 的虚构资料复现。

## 一起写代码

### 跑起来

```bash
uv sync
uv run youtiao --reload      # 改了代码自动重启
uv run pytest                # 测试
uv run python -m core.guides # 校验攻略和词表
```

改了 `src/form_engine/` 里的填表脚本后，运行 `uv run python scripts/build_extension.py`，把它同步到插件里（CI 会检查两边是否一致）。

### 代码在哪

```
community/        大家一起维护的攻略、材料词表、填表同义词表
src/core/         核心逻辑：攻略校验、材料匹配、办事进度、这次行程
src/api/          本地网页服务
src/form_engine/  填表引擎和填表对照
src/agent_tools/  给 Agent 用的工具（MCP）
src/agent_runner/ 从网页调起 Agent 的任务
extension/        Chrome 插件
web/              页面
specs/  docs/     设计文档、路线图、试验记录
```

### 动手之前

- 先读 [`AGENTS.md`](./AGENTS.md)：协作规则，包括提交信息的格式和安全约定。
- 再看 [`docs/ROADMAP.md`](./docs/ROADMAP.md)，了解接下来要做什么；新想法先写进 [`docs/BACKLOG.md`](./docs/BACKLOG.md)。
- 功能的设计都在 `specs/` 里，每个编号一个主题。改行为之前先改对应的 spec。
- 提交信息用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/) 的格式，比如 `feat(web): ...`、`fix(form-engine): ...`。

提交 Pull Request 时，模板里有一张检查清单，照着勾一遍就好。
