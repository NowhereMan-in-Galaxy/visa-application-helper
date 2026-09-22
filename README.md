# 会成长的个人助手（材料与表单管理）

## 这是什么


## Intent（我们真正想解决的问题）

起点是一次真实经历：办理澳大利亚签证时，材料分散在各处，其中银行流水、工作证明等有时效性，容易搞不清哪些已备齐、哪些要更新；网站表单填写这一步用 Agent 做过一次，可行但慢——因为每次都在从零探索网页结构。

值得解决的核心问题：
1. 材料状态（有没有、是否过期）应该能随时查到，而不是每次要用的时候现翻。
2. 网站表单填写的"探索"只应该发生一次；探索结果应变成之后能反复使用的资产。

## 现在所处的阶段

项目负责人（下称"项目主"）几乎没有计算机基础，正在通过这个项目学习版本管理和软件工程实践；本仓库的文档和代码由 Claude（Sonnet 5）在多轮讨论中协助整理和实现。**"材料资料库 + 办签证智能清单"这个 feature（`specs/001-visa-material-hub/`）已经进入实现阶段，不再只是规格记录**——本地能跑起来，能看真实数据。

在读这份 README 的 Agent（不论强弱），按顺序读：
1. [`AGENTS.md`](./AGENTS.md)——协作规则，尤其是版本管理和安全相关的约定，**必读，优先级最高**。
2. [`docs/SPEC-mvp.md`](./docs/SPEC-mvp.md)——项目级别锁定的范围、架构边界、安全约束。
3. [`specs/001-visa-material-hub/spec.md`](./specs/001-visa-material-hub/spec.md) + [`plan.md`](./specs/001-visa-material-hub/plan.md)——这个 feature 的详细需求和技术方案。
4. [`specs/001-visa-material-hub/STATUS.md`](./specs/001-visa-material-hub/STATUS.md)——**当前实现进度**：哪些 User Story 做完了、哪些没做、已知的粗糙点/技术债，接手的 Agent 从这份文档开始定位"接下来该做什么"，不用去翻聊天记录。
5. [`docs/BACKLOG.md`](./docs/BACKLOG.md)——明确推迟、暂不实现的想法，看到这些想法时不要主动开始实现，除非项目主明确要求把某一项从 backlog 移进范围。

## 项目主的背景（供协作的 Agent 参考）

- 几乎没有计算机科学基础，正在通过这个项目学习版本管理（Git）、软件工程实践和基础计算机概念，希望解释伴随实现过程发生，而不是只交付代码。
- Token 预算有限，之后大概率会用更便宜的模型执行具体任务。这要求任务描述和规格写得足够具体、无歧义，能让能力较弱的模型也能可靠执行。

## 目录结构（当前）

```
personal-assistant/
  README.md              # 本文件
  AGENTS.md               # 协作与学习规则
  docs/
    SPEC-mvp.md            # 已锁定的 MVP 范围、架构边界、数据结构草案、验收标准、待决问题
    BACKLOG.md              # 明确推迟的扩展想法
  specs/001-visa-material-hub/
    spec.md                  # 这一轮功能的详细规格（用 spec-kit 写的）
    plan.md                   # 技术方案：语言/存储/目录结构怎么选的
    diagrams/                  # 数据模型图
  src/                       # 实现代码（见下面"本地跑起来"）
  web/                        # 前端静态页面
  materials_index/             # 材料记录的结构化索引（只存元数据，不存真实文件）
  tests/                      # pytest 单元测试
  .gitignore
```

## 本地跑起来

依赖用 [uv](https://docs.astral.sh/uv/) 管理，第一次跑之前先装好 uv，然后在仓库根目录：

```bash
uv sync                # 装依赖（第一次跑，或者 pyproject.toml 变了之后）
uv run pytest tests/    # 跑单元测试
uv run uvicorn api.app:app --app-dir src --reload   # 启动本地服务
```

启动之后浏览器打开 <http://127.0.0.1:8000>，会看到一份**虚构的示例数据**（`materials_index/` 里 `example-` 开头的文件），确认能跑通之后把这些示例删掉、换成自己的真实申请信息（记住只填元数据，真实文件本体放在 `materials_root` 配置指向的目录——复制 `config.example.yaml` 为 `config.yaml` 后按需修改）。
