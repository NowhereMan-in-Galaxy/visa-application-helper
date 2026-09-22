# Implementation Plan: 材料资料库扩展 + 办签证智能清单

**Branch**: `001-visa-material-hub` | **Date**: 2026-09-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-visa-material-hub/spec.md`

## Summary

在本地单机上跑一个小型 Web 服务：浏览器打开 `http://localhost` 就能看材料库状态、办签证时生成 AI checklist。核心确定性逻辑（存储、状态判断、建空文件夹）用 Python 写成独立的"核心库"，不依赖模型调用、可单独测试；材料需求提取和清单匹配这两步需要模型判断，放在单独的"Agent 层"，通过可配置的 LLM API 调用。材料记录以人可读的 YAML 文件存储，方便项目主（CS 初学者）直接打开看懂、也方便用 git 追踪索引的变化历史。项目从设计上就避免硬编码个人路径/场景，为将来开源到 GitHub、让其他人各自本地自部署留好空间（见 `.specify/memory/constitution.md` 的 Deployment & Distribution Constraints）。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI + Uvicorn（本地 Web 服务）、Pydantic（数据结构定义与校验）、PyYAML（读写材料记录文件）、pytest（测试）。前端先用纯 HTML/CSS/JS 静态页面，不引入重框架，避免额外的构建工具链对初学阶段造成负担。

**Storage**: 分两个目录，概念上不能混：
- **材料根目录**（真实文件本体：护照扫描件、银行流水等）——路径可配置，默认指向项目内 `materials/`（已被 `.gitignore` 排除），也可以指向项目外任意路径（例如 iCloud）。
- **`materials_index/`**（本仓库内，会被 git 追踪）——只存材料记录的结构化元数据，每条 `MaterialRecord` 一个 YAML 文件，`file_ref` 字段是相对于材料根目录的相对路径，不含真实文件内容。这是 `docs/SPEC-mvp.md` 第 3 条"数据与代码分离"原则的具体落地方式。

**Testing**: pytest 覆盖核心库（状态计算、更新频率提醒、file_ref 路径解析、空文件夹生成的命名规则与冲突检测）；Agent 层用固定输入输出的 fixture 做契约测试，不在自动化测试里真实调用模型 API（省 token、也让测试结果确定）。

**Target Platform**: 本地桌面（项目主当前用 macOS；代码只用跨平台的 Python 标准库 + 上述依赖，不用任何 macOS 专有 API，理论上 Linux/Windows 也能跑——这也是"以后开源给别人自部署"的前提）。

**Project Type**: 本地 web-service（一个本地后端 + 浏览器前端），不是原生桌面应用，也不是移动端。

**Performance Goals**: 个人使用规模，不追求高并发；材料记录在数百条量级内，状态计算和列表加载应在 200ms 内完成，属于宽松但可验证的目标。

**Constraints**: 除了"材料需求提取""材料匹配"这两个 Agent 层功能需要联网调用模型 API，其余功能（浏览材料库、查状态、建空文件夹）应能离线运行；不依赖任何付费云服务才能把应用本身跑起来。

**Scale/Scope**: 单用户，材料记录数十到数百条，签证申请数个位数到十位数量级——MVP 阶段不需要为规模做任何特殊设计。

## Constitution Check

*对照 `.specify/memory/constitution.md`：*

- **I. Learning-First**：Python + 人类可读的 YAML 文件，项目主可以直接打开 `materials_index/` 里的文件看懂发生了什么，不需要先学"数据库"这个概念。✅
- **II. Git Discipline**：不受技术选型影响，后续每个 `/speckit-tasks` 任务落地时仍按原子提交 + Conventional Commits 执行。✅
- **III. Data/Code Separation & Security**：`materials_index/` 只存元数据和相对路径，材料根目录路径通过配置文件声明、不硬编码；`materials/` 默认目录已在 `.gitignore` 里。✅
- **IV. Spec Precision for Cheap-Model Execution**：本 plan 给出的目录结构和分层，是为了让下一步 `/speckit-tasks` 能拆出边界清晰、可以交给更便宜模型执行的具体任务。✅
- **V. Decisions Live in Docs**：本文件本身就是这一层决定的落地位置，无需再回填 `docs/SPEC-mvp.md`。✅
- **Deployment & Distribution**：纯本地运行、无强制云依赖；不硬编码个人路径或"只有我能用"的假设，符合"以后开源给别人自部署"的约束。✅

无违反，Complexity Tracking 一节不适用。

## Project Structure

### Documentation (this feature)

```text
specs/001-visa-material-hub/
├── spec.md              # 已完成（/speckit-specify）
├── plan.md              # 本文件（/speckit-plan）
├── checklists/
│   └── requirements.md   # 已完成，spec 质量自检
├── diagrams/
│   └── data-model.*       # 已完成，实体关系图
└── tasks.md              # 下一步（/speckit-tasks），本文件不创建
```

### Source Code (repository root)

```text
src/
├── core/                  # 核心库：确定性逻辑，不调用模型，可独立单测
│   ├── models.py           # MaterialRecord / VisaApplication / MaterialChecklist / ChecklistItem（Pydantic）
│   ├── status.py            # 已备齐/待补/即将过期/已过期 的状态计算（FR-003）
│   ├── update_cadence.py     # 建议更新频率提醒，独立于 validity_rule（FR-003a）
│   ├── storage.py             # 读写 materials_index/ 下的 YAML 记录；材料根目录路径解析（SPEC-mvp §3）
│   └── scaffold.py             # 为缺失材料建空文件夹，命名规范 + 冲突检测（FR-008/FR-009）
│
├── agent/                  # Agent 层：需要模型判断，探索结果应可沉淀复用
│   ├── extractor.py          # 文字/图片材料要求 → 结构化 checklist（FR-005/FR-006）
│   └── matcher.py              # checklist 项 ↔ materials_index 已有记录匹配（FR-007）
│
├── api/                    # 本地 Web 服务
│   ├── app.py                # FastAPI 入口
│   └── routes/                 # 材料 / 签证申请 / checklist 相关 HTTP 路由
│
└── config.py                # 读取材料根目录路径等可配置项

web/                        # 前端静态页面（纯 HTML/CSS/JS）
├── index.html                # 材料库浏览主页
└── assets/

materials_index/             # 材料记录 YAML（仓库内，git 追踪，只存元数据）
└── .gitkeep

materials/                   # 材料根目录默认位置（已在 .gitignore，可在配置里改指向别处）
└── .gitkeep

tests/
├── unit/                     # 核心库单元测试（pytest）
└── fixtures/                   # 虚构示例数据，绝不放真实材料

config.example.yaml            # 配置文件示例（材料根目录路径等），真正的 config.yaml 会被 .gitignore 排除
```

**Structure Decision**：采用单一 Python 项目内的分层结构（`core` / `agent` / `api` 三层 + 静态前端），不拆成前后端两个独立包。前端目前只是浏览材料库的静态页面，还没复杂到需要独立构建流程；如果以后前端功能明显变重，可以再拆成独立项目。
