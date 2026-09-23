---
name: guide-author
description: 用户想把一篇或多篇杂乱的攻略（文字、截图描述、网页/小红书/知乎内容粘贴过来的文本）整理成本项目 community/guides/ 下的结构化流程攻略 YAML 时使用；触发词包括"帮我整理这篇攻略""把这个签证攻略变成流程""新增一份 xxx 攻略"。不用于回答"我这次该怎么办"（那是 errand-helper 的职责），也不用于填写官网表单。
---

# 攻略整理（杂乱资料 → community/guides/<id>.yaml）

## 目标

把用户提供的原始资料（可能是几段文字、几张截图描述、一个或多个链接的内容）整理成一份能通过校验的
`community/guides/<id>.yaml`。这份文件是共享区内容，给所有人用，绝不能包含任何个人信息。

## 执行步骤（必须按顺序做，不能跳过）

1. **先读两份文件，不要凭记忆开始写**：
   - `specs/002-guide-to-track/prompt.md`：抽取规则的唯一权威来源（怎么分 source id、evidence 怎么摘、
     `freshness_days`/`duration_days` 怎么填、`facts`/`applies_if`/`ask_if` 怎么用、步骤粒度等）。
   - `community/material_types.yaml`：材料类型词表全文（含 `normalize` 规则），确定每条材料的
     `raw_name` 能不能对上已有的 `key`。
   - 数据结构定义以 `specs/002-guide-to-track/spec.md` "数据结构"一节为准，`prompt.md` 只规定怎么抽。

2. **按 `prompt.md` 的全部规则**把用户给的资料抽取成 YAML，字段范围严格限定在
   `spec.md` "数据结构 §1" 列出的字段（`id`、`title`、`category`、`summary`、`maintainers`、`updated`、
   `timeline`、`sources`、`phases`、`facts`、`requirements`、`steps`、`checks`、`conflicts`、`uncertain`）。
   `id` 只能是小写字母、数字和连字符，且必须和文件名（不含扩展名）一致。

3. **材料叫法先查词表**：`raw_name` 填原始资料里的原叫法。词表的匹配规则是：先按
   `material_types.yaml` 顶部的 `normalize` 删掉"原件""复印件""近 N 个月"等修饰，再忽略大小写和
   空白后与某个 `alias` 或标准名完全相等。能对上的可以填 `material_type`（也可以留空让程序自动推断）；
   对不上就留空（null）。第 5 步的校验命令会列出"N 条材料叫法词表认不出"，以它为准。

4. **词表认不出的叫法，不要自己改词表**：先把这些"建议归入哪个已有 key，或者建议新增什么 key
   （包括建议的 `name`/`aliases`/`category`）"整理成一段清单，在回复正文里（不是写进 YAML 文件）
   列给用户看，等用户明确同意之后，才去改 `community/material_types.yaml`。改完词表要重新跑一遍
   第 5 步的校验命令。

5. **写完（或改完词表）之后，必须在仓库根目录运行**：

   ```bash
   PYTHONPATH=src uv run python -m core.guides
   ```

   输出里只要有一个 `✗`，就照着提示信息修改对应文件，再重新运行，直到这份新攻略、以及词表本身
   全部显示 `✓`、命令退出码为 0 才算完成。不要在还有 `✗` 的情况下告诉用户"整理好了"。

6. **硬性红线：不写任何个人信息**。以下内容永远不能出现在 `community/guides/*.yaml` 或词表里：
   - 任何人的真实姓名、证件号、电话、地址、具体存款金额；
   - 贡献者自己办这件事的进度、用了哪份材料、走到哪一步（这些属于个人区的 Track，界面会自动
     写到材料根目录下，跟这份攻略文件无关）；
   - 原始资料的大段原文——`evidence.quote` 不超过 60 字，只摘录能支撑该条目的原话，并写清
     `source` 对应哪个 `sources[].id`。
   - 攻略没提到的材料或步骤，不要凭常识/经验补；你认为明显遗漏的，写进 `uncertain` 并在
     对应条目的 `note` 里说明"攻略未提及，建议核实"。
   - 多篇资料说法冲突时写进 `conflicts`，不要自己挑一个说法定论。

7. **完成后提醒用户自己检视一遍**：告诉用户启动本地服务后打开浏览器访问 `/guides.html`，
   点进刚整理的攻略看预览，模拟回答几个问题，确认步骤和材料符合常识，再决定要不要提交。

## 别漏掉的两件事

- **导出命名**：原始资料有官方清单编号时，按 `prompt.md` 第 18 条给每条材料写 `export_name`。
- **官网链接和填表指南**：按 `prompt.md` 第 19 条，把原始资料里的网址挂到步骤的 `links` 上；写了填表/预约流程的，另写一份 `community/forms/<id>.yaml` 并链接过去。

## 输出要求

- 产出 `community/guides/<id>.yaml`；原始资料写了填表流程时再加 `community/forms/<id>.yaml`；经用户同意后才改动 `community/material_types.yaml`。
- 不要创建、修改仓库里的任何 Track 文件（那些只存在于材料根目录，不属于这个 skill 的工作范围）。
- 不要执行 `git add` / `git commit`——整理完把结果和校验通过的证据（第 5 步命令的输出）告诉用户，
  由用户自己决定是否提交；如果用户明确要求提交，提交信息按仓库 `community/README.md` 的建议格式
  写清来源，例如 `feat(guides): add japan tourist visa (Shanghai consulate)`。
