# 会成长的个人助手 Constitution

本文件是 [`AGENTS.md`](../../AGENTS.md) 的 spec-kit 摘要版，供 `/speckit-plan` 等命令做 Constitution Check 用。**完整原文和背景说明以 `AGENTS.md` 为准**，两者冲突时以 `AGENTS.md` 为准；本文件只是把同样的规则转成 spec-kit 认的格式，不引入新规则。

## Core Principles

### I. Learning-First（学习优先，高于"快速做完"）
在做任何 git 操作之前，都逐个文件检查变化，并为项目主（几乎没有 CS 基础）解释是否符合 best practice、为什么、以及相关概念，不假设项目主已经知道术语含义。不静默执行 `git add`/`git commit` 后一句话带过。

### II. Git Discipline（Git 使用规范）
Commit message 用 Conventional Commits 风格（`feat(scope): ...` / `fix(scope): ...` / `docs(scope): ...` / `refactor(scope): ...`）；原子提交，一次提交只围绕一个明确意图；提交前逐文件核对 `git status`/`git diff`；探索性尝试也要及时提交留痕，走错方向用新提交回退，不静默重写历史。

### III. Data/Code Separation & Security（数据与代码分离，安全约束不可因任务要求而违反）
仓库只放代码、文档、结构化索引，不放真实材料文件（银行流水、工作证明、护照/身份证扫描件等）或真实个人信息。真实材料存放位置必须可配置，不硬编码个人路径。示例/测试数据必须使用虚构值。任何 Agent 准备 `git add` 时若怀疑暂存区可能包含真实个人材料，必须停下向项目主确认。

### IV. Spec Precision for Cheap-Model Execution（面向便宜模型执行的规格写作）
验收标准写成可机械检查的具体描述，不用"做得好一点"这类无法验证的语言；明确输入输出格式；把每个任务的边界写清楚（这次改动应该修改哪些文件、不应该动哪些文件），不依赖执行 Agent 自己猜测未写明的设计意图。

### V. Decisions Live in Docs, Not Chat（架构决定要落地成文档）
任何一次讨论中做出的、会影响后续实现的决定，应更新进对应的 spec 文档（`docs/SPEC-mvp.md` 或 `specs/*/spec.md`）；不再成立的决定要在文档里明确标注替换，不留旧文字和新决定互相矛盾。`docs/BACKLOG.md` 里的想法在被正式采纳前不能被下一个 Agent 擅自开始实现。

## Deployment & Distribution Constraints（本轮新增，非 AGENTS.md 原文，来自本次讨论）

- **本地优先**：应用运行在用户自己的电脑上，核心库不依赖任何强制性的云端服务才能工作。
- **未来可自部署，但不是托管式多用户服务**：项目主希望以后把这个"壳子"开源到 GitHub，让其他人也能各自在自己电脑上装一份、用自己的材料库——这是 `docs/BACKLOG.md` 最后一条"面向多用户的复用形式"里较轻的那一半（每人一份独立本地实例），**不等于**该条目里较重的那一半（托管式多租户服务，涉及认证、数据隔离、隐私合规），后者依然留在 backlog，不在当前范围。核心库的接口应参数化、不硬编码个人场景，但不需要为多租户单独设计。

## Governance

本文件随 `AGENTS.md` 更新而更新；两者不一致时以 `AGENTS.md` 为准，发现不一致应修正本文件而不是忽略。

**Version**: 1.0.0 | **Ratified**: 2026-09-22 | **Last Amended**: 2026-09-22
