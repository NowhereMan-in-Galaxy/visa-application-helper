# 有条有理：大家共同维护的签证/办事流程攻略

## 这是什么

签证、社保、银行补贴……这类行政流程繁琐、信息分散，最容易让人焦虑。这个项目想把它变成"照着做就行"：

1. **共同维护的流程攻略库**（`community/guides/`）：每份攻略是一件事的结构化流程——先问你几个会影响清单的问题（身份、婚否……），再列出要做哪几步、每步要什么材料、材料之间哪里必须对得上，每一条都附原始资料里的原话。任何人都可以提交或改进一份攻略。
2. **本地 Agent 辅助整理**：网上的攻略是杂乱的图文。贡献者用自己本机的 Agent（Claude Code / Codex 等）按 [`specs/002-guide-to-track/prompt.md`](./specs/002-guide-to-track/prompt.md) 把它整理成结构化攻略，再用校验命令检查。应用本身不调用任何模型、不需要 API key。
3. **可以交互检视的界面**（`/guides.html`）：挑一份攻略"开始办"，回答几个问题后，和你无关的材料自动隐藏；它会用你本机的材料库自动对出"你已经有哪些材料、哪些过期了、还缺什么"，告诉你下一步做什么，最后带你逐条核对。

**攻略是大家的，进度是你自己的**：攻略放在公开的 `community/`，不含任何个人信息；你的回答、进度、材料匹配只存在你本机的材料根目录里，永远不进仓库。


## Intent（我们真正想解决的问题）

起点是一次真实经历：办澳大利亚签证时，材料分散在各处，银行流水、工作证明等有时效性，搞不清哪些已备齐、哪些要更新；网上收藏了攻略，自己对照着准备依然很慢。

值得解决的核心问题：
1. **弄清"到底要办什么"**是最难的一步——把杂乱的攻略变成结构化的流程，而且只需要有一个人整理一次，大家都能用。
2. **材料复用**：不同事情要的基础材料大量重复，同一份护照、同一份流水应该能服务多件事，状态（有没有、过没过期）随时可查。
3. **网站表单填写**的"探索"只应该发生一次，探索结果变成可以反复使用的资产（MVP 第 2 项，尚未开始）。

## 现在所处的阶段

项目负责人（下称"项目主"）几乎没有计算机基础，正在通过这个项目学习版本管理和软件工程实践；文档和代码由 AI Agent 在多轮讨论中协助整理和实现。

- **材料资料库**（`specs/001-visa-material-hub/`）：已实现，能看真实数据、上传材料、维护出行记录。
- **流程攻略 + 我的办事**（`specs/002-guide-to-track/`）：Phase A 已实现——攻略校验、材料匹配、状态计算、交互界面。已有第一份攻略（申根短期旅游签）。下一步是 Phase B：把整理指令打包成本地 Agent skill，方便贡献者使用。

在读这份 README 的 Agent（不论强弱），按顺序读：
1. [`AGENTS.md`](./AGENTS.md)——协作规则，尤其是版本管理和安全相关的约定，**必读，优先级最高**。
2. [`docs/SPEC-mvp.md`](./docs/SPEC-mvp.md)——项目级别的范围、架构边界、安全约束。
3. [`specs/002-guide-to-track/spec.md`](./specs/002-guide-to-track/spec.md)——当前主线：攻略/我的办事的数据结构、状态计算、分阶段计划、待决问题。
4. [`specs/001-visa-material-hub/spec.md`](./specs/001-visa-material-hub/spec.md) + [`STATUS.md`](./specs/001-visa-material-hub/STATUS.md)——材料资料库的需求和实现进度。
5. [`docs/ROADMAP.md`](./docs/ROADMAP.md)——**接下来做什么**：按优先级排好的几条主线、每条需要项目主提供什么、待商量的决定。
6. [`docs/BACKLOG.md`](./docs/BACKLOG.md)——明确推迟、暂不实现的想法，看到时不要主动开始实现，除非项目主明确要求。

## 项目主的背景（供协作的 Agent 参考）

- 几乎没有计算机科学基础，正在通过这个项目学习版本管理（Git）、软件工程实践和基础计算机概念，希望解释伴随实现过程发生，而不是只交付代码。
- Token 预算有限，之后大概率会用更便宜的模型执行具体任务。这要求任务描述和规格写得足够具体、无歧义，能让能力较弱的模型也能可靠执行。

## 目录结构（当前）

```
personal-assistant/
  README.md                # 本文件
  AGENTS.md                # 协作与学习规则
  community/               # 共享区：大家共同维护，绝不含个人信息
    README.md              #   贡献说明
    material_types.yaml    #   材料类型词表
    guides/                #   流程攻略，一件事一个 YAML
  docs/
    SPEC-mvp.md            # 项目级范围、架构边界、安全约束
    BACKLOG.md             # 明确推迟的扩展想法
  specs/
    001-visa-material-hub/ # 材料资料库
    002-guide-to-track/    # 流程攻略 + 我的办事（spec、整理指令、试验记录）
  src/
    core/                  # 核心库：纯代码、可单独测试（guides.py、tracks.py、material_types.py …）
    api/                   # 本地 Web 服务
  web/                     # 前端静态页面（guides.html 是新主入口）
  materials_index/         # 个人材料记录的结构化索引（只存元数据；见 spec 002 待决问题）
  tests/                   # pytest 测试
```

个人区（不在仓库里）：`config.yaml` 里 `materials_root` 指向的目录，默认是项目内被 `.gitignore` 排除的 `materials/`。里面放真实材料文件、`personal-profile.yaml` 和 `tracks/`（你的办事进度）。

## 本地跑起来

依赖用 [uv](https://docs.astral.sh/uv/) 管理，第一次跑之前先装好 uv，然后在仓库根目录：

```bash
uv sync                                              # 装依赖（第一次跑，或者 pyproject.toml 变了之后）
uv run pytest tests/                                  # 跑测试
PYTHONPATH=src uv run python -m core.guides          # 校验 community/ 下的攻略和词表
uv run uvicorn api.app:app --app-dir src --reload    # 启动本地服务
```

启动之后浏览器打开 <http://127.0.0.1:8000>（会自动跳到攻略库 `/guides.html`）：攻略库和"我正在办的事"；「我的资料」在 `/my.html`。

服务没有登录鉴权，只靠 Origin / Host 校验挡浏览器里的跨站请求（见 `specs/002-guide-to-track/spec.md` B3 安全前提），**不要用 `--host 0.0.0.0` 之类的参数把它暴露到局域网/公网**，否则同一网络里的其他设备也能直接读写你的材料数据。

`materials_index/` 里 `example-` 开头的是**虚构示例数据**，只用来演示格式，不会被匹配给真实的办事；确认能跑通之后可以删掉，换成自己的材料记录（只填元数据，真实文件本体放在材料根目录——复制 `config.example.yaml` 为 `config.yaml` 后按需修改）。

## 用本地 Agent

这个项目不内嵌任何模型 API、不需要 API key——Agent 能力来自**你自己本机已经装好的** Claude Code /
Codex 等工具，用谁的账号、花谁的额度，由你自己决定（详见 [`specs/002-guide-to-track/spec.md`](./specs/002-guide-to-track/spec.md) "Agent 接入方案"一节）。目前实现了两级：

1. **项目自带指令（skills）**：在仓库根目录打开你自己的 Claude Code / Codex，直接用自然语言描述需求，
   Agent 会按 `.claude/skills/` 下的指令工作：
   - `guide-author`：把一篇杂乱的攻略（文字/截图/网页内容）整理成 `community/guides/<id>.yaml`，
     整理完自动跑校验命令，认不出的材料叫法会先跟你确认再改词表。
   - `errand-helper`：回答"我这件事下一步做什么""要不要交某份材料"之类的问题；任何会改动你办事
     进度的操作（改回答、勾步骤、确认材料）都会先复述一遍、等你同意才会真的写。

2. **本地 MCP 服务**：仓库根目录的 [`.mcp.json`](./.mcp.json) 已经配置好，Claude Code 打开这个项目
   会自动连接。它把"列出攻略 / 读我的办事 / 改回答 / 勾步骤 / 确认材料 / 校验共享区"包装成 Agent 能
   直接调用的工具（定义在 `src/agent_tools/tools.py`），不经过 HTTP、不需要额外起服务；只暴露必要的
   读和受控写操作，不提供删除，也不提供读取材料文件内容本身的工具。手动启动看是否正常（正常情况下
   会挂起等待 stdio 输入，`Ctrl+C` 退出即可）：

   ```bash
   PYTHONPATH=src uv run python -m agent_tools.mcp_server
   ```

第三级（界面里点一下"问 Agent"，结果直接显示在页面上）还没实现，需要先做好防跨站请求伪造（CSRF）
的安全加固，见 spec 里的说明。
