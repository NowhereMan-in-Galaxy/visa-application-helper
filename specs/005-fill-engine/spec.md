# Spec 005：通用填表引擎（第一步：Agent 模式 + 通用识别）

- 状态：第一步实现中（2026-09-28）
- 依据：项目主 2026-09-28 的决定——"网站专用对照表放到下一步，这一步先做 Agent 用的通用引擎"。
- 相关：`docs/SPEC-mvp.md` 第 1 条第 2 项（基本信息驱动的 Agent 填表）、specs/003（基本信息）、
  `.claude/skills/form-filler/`、`specs/002-guide-to-track/trials/README.md` 试验 #6（DS-160 被封 IP）。

## 为什么要做

试验 #6 里 Agent 一格一格地填 DS-160：慢，而且在多行列表上反复重试，最后被封 IP。
常见的格子（姓名、生日、护照号、地址、电话、邮箱……）其实不需要模型判断——Chrome 自带的自动填充
就是靠"看格子旁边的字 + 同义词"认出来的。

所以把填表拆成两部分：

- **引擎（确定性代码）**：认出页面上的常见格子，从「基本信息」取值，一次填完这一页。
- **Agent**：只处理引擎认不出、或需要判断的格子（本次行程信息、法律声明题、多行列表），以及问用户。

## 分层（这一步只做第 1 层）

| 层 | 内容 | 这一步 |
|---|---|---|
| 1. 通用识别 | 按同义词表认格子，不需要了解具体网站 | ✅ 做 |
| 2. 网站专用对照表 | `community/forms/<id>.yaml` 里加字段级对照（DS-160、France-Visas、ImmiAccount…） | 下一步 |
| 3. 贡献流程 | 填完一页"记下结构"（不记值）生成对照表草稿 | 下一步 |
| 插件外壳 | 侧边栏 + "填本页"按钮，不经过 Agent | 再下一步 |

## 组成

```
页面 ──scan.js──▶ 格子描述（不含值）──plan_form_fill──▶ 填写计划 + fill.js（含值）──▶ 页面
                                        ▲
                    community/form_fields.yaml（同义词表） + 「基本信息」
```

1. `src/form_engine/scan.js`：在页面里运行，列出可以填的格子，**不读格子里的值**，只报"是否已有内容"。
2. `src/form_engine/match.py`：同义词表 + 基本信息 → 每个格子填什么（**判断全在 Python 里，能用 pytest 测**）。
3. `src/form_engine/fill.js`：在页面里运行，按计划填值、标黄框，只返回计数，不回显值。
4. `community/form_fields.yaml`：同义词表，共享区数据，任何人可以补充；**不含个人信息**。
5. MCP 工具 `get_form_scan_script`、`plan_form_fill`（见下）。

把判断放在 Python、不放在页面脚本里：以后插件通过本地服务调用同一套判断，规则只写一份。

## 数据格式

### scan.js 的返回值

```json
{"host": "example.gov", "title": "页面标题", "count": 2, "fields": [
  {"i": 0, "kind": "text", "label": "Surname", "name": "ctl00 tbx app surname", "placeholder": "",
   "autocomplete": "family-name", "section": "Personal Information", "filled": false},
  {"i": 1, "kind": "radio", "label": "Sex", "name": "rbl sex", "options": ["Male", "Female"],
   "section": "", "filled": false}
]}
```

- `kind`：`text`（含 email / tel / 没写 type 的 input）、`date`（`type=date`）、`textarea`、`select`、`radio`（一组一条）。
- **不扫**：`hidden`、`password`、`file`、`checkbox`、`submit/button`、不可见、`disabled`、`readonly`、
  名字或标签含 `captcha` / `验证码` 的格子、iframe 里的格子。
- `name`：`name` 和 `id` 原样拼起来，最多 120 字；拆词（`tbxAPP_SURNAME` → `tbx app surname`）在 Python 里做。
- `label`、`section` 各最多 100 字；`options` 只给单选组，每项最多 40 字、最多 12 项。
- `filled`：文本框有内容 / 下拉框选的不是第一项 / 单选组已有选中项。
- 只返回域名，不返回完整网址（网址里可能带申请号或令牌）。
- 每个格子加 `data-pa-i` 属性，fill.js 用它找回格子；页面刷新后属性消失，要重新扫。

### plan_form_fill 的返回值

```json
{
  "fill": [{"i": 0, "path": "identity.surname", "label": "基本身份 › 姓（拼音，同护照）"}],
  "sensitive": [{"i": 3, "path": "passport.passport_number", "label": "..."}],
  "missing": [{"i": 5, "path": "contact.secondary_phone", "label": "..."}],
  "needs_format": [{"i": 7, "path": "identity.date_of_birth", "label": "..."}],
  "already_filled": [2],
  "unmatched": [{"i": 9, "text": "Purpose of trip"}],
  "script": "(() => { ... })()"
}
```

- `fill`：会填的格子。**报告里不含值**；值只在 `script` 里。
- `sensitive`：认出来了、基本信息里有值，但字段是敏感的（证件号、出生日期、收入……），**默认不填**。
  用户在对话里同意后，Agent 把这些 `path` 放进 `allow_sensitive` 重新调用。
- `missing`：认出来了，但基本信息里没有值 → Agent 问用户（长期信息确认后写回基本信息）。
- `needs_format`：日期格子，但看不出要哪种格式 → 交给 Agent 看页面填。
- `already_filled`：页面上已有内容的格子，不覆盖。
- `unmatched`：认不出的格子 → 交给 Agent。

## 识别规则（match.py）

1. 每个格子的"文本" = `label` + `section` + `name` + `placeholder`，做规范化：拆驼峰、转小写、
   非字母数字（中文保留）换成空格。
2. 同义词表每条是 `路径: {match: [[词组…], [词组…]], exclude: [...], autocomplete: [...]}`：
   - `match` 里的**每一组都要命中至少一个词**（例如"父亲的姓"= `[[father, 父亲], [surname, 姓]]`）；
   - 英文词按整词匹配，中文词按子串匹配；
   - `exclude` 里任一词出现就不算（例如申请人本人的"姓"排除 father / mother / spouse…）；
   - 得分 = 每组命中的最长词的长度之和；词出现在格子自己的标签 / 名字 / 占位符里算两倍，只出现在小节标题里算一倍
     （"Home Address" 小节里的 "Primary phone" 应该认成电话，不是地址）；网页自带的 `autocomplete` 命中直接得 100 分。
3. 一个格子取得分最高的一条；**并列第一且路径不同时算认不出**（宁可交给 Agent，不乱填）。
4. 同一个字段可以填进多个格子（例如"邮箱"和"确认邮箱"）。
5. 日期字段：
   - `type=date` → `YYYY-MM-DD`；
   - 文本框里看得出格式（`DD/MM/YYYY`、`MM/DD/YYYY`、`YYYY-MM-DD`、`DD-MM-YYYY`、`DD.MM.YYYY`、`YYYY/MM/DD`、`DD-MMM-YYYY`）→ 按格式；
   - 格子文本里有 day / month / year（或 日 / 月 / 年）→ 只填那一部分（DS-160 的日期就是拆成三格的）；
   - 都不是 → `needs_format`。
6. 下拉框和单选组：Python 给出"候选写法"（例如男 → `male, m, 男`；中国 → `china, 中国, chn…`；
   五月 → `05, 5, may, 五月`），fill.js 在选项文字或选项值里找**规范化后完全相同**的一项；
   没有再找"以候选开头"的；**只有唯一一项时才选**，否则不动并计入 `skipped`。
7. 只支持单个值的字段（包括嵌套对象，例如 `contact.home_address.city`、`family.father.surname`）；
   列表字段（曾用名、以前的工作、去过美国……）这一步不填，交给 Agent。

## fill.js 的行为

- 填写顺序：文本框 → 下拉框 → 单选组（下拉框和单选可能触发页面刷新，放最后）。
- 文本框用浏览器原生的赋值方法 + `input` / `change` / `blur` 事件（React、Vue 做的页面也能认到）。
- 下拉框设 `value` + `change` 事件；单选用 `click()`。
- 已有内容的格子不覆盖（扫描之后用户又填了的，也再查一次）。
- 填上的格子加黄色虚线框，鼠标悬停显示"个人助手自动填写，请核对"。
- 返回 `{"filled": n, "skipped": n, "gone": n}`（`gone` = 格子找不到了，多半是页面刷新了），**不返回任何值**。

## MCP 工具

| 工具 | 输入 | 输出 |
|---|---|---|
| `get_form_scan_script()` | 无 | `{"script": "..."}`，用浏览器工具在页面里运行 |
| `plan_form_fill(fields, allow_sensitive=[])` | scan.js 返回的 `fields` | 上面的计划；`allow_sensitive` 里不在 `sensitive` 候选中的路径忽略 |

两者都只读，不写任何文件。界面里的 Agent（spec 004）暂不开放这两个工具。

## Agent 使用方式（写进 form-filler skill）

每一页：扫描 → 计划 → 把 `sensitive` 列给用户确认 → 运行 `script` → 自己处理 `unmatched` / `needs_format`
/ `missing` → 用户核对黄框后**自己点**下一页。一页最多扫描 + 填写 **2 轮**（第 2 轮用于页面刷新后
新出现的格子），不再多试。

## 验收标准（可以机械检查）

1. `uv run pytest -q` 全部通过，其中新增测试覆盖：
   - 用 `tests/fixtures/forms/generic-form.scan.json`（在真实浏览器里对 `tests/fixtures/forms/generic-form.html`
     扫描得到）+ 虚构的基本信息，计划结果与测试里写明的"格子 → 路径"表完全一致；
   - 申请人本人的"姓"和"父亲的姓"不会互相认错；"家庭住址 城市"和"出生城市"不会互相认错；
   - 敏感字段默认进 `sensitive` 不进 `fill`，放进 `allow_sensitive` 后进 `fill`；
   - 报告部分（去掉 `script`）序列化后不包含虚构基本信息里的任何值；
   - 拆开的生日（日 / 月 / 年三格）三格都认出，分别得到正确的部分；
   - 同义词表里每个路径都存在于基本信息、且是单值字段；`exclude` / `match` 不为空。
2. `PYTHONPATH=src uv run python -m core.guides` 输出一行 `✓ community/form_fields.yaml：N 个字段`，退出码 0。
3. 在真实 Chrome 里打开 `generic-form.html`，按 skill 流程扫描、计划、填写：`fill` 里的格子都被填上、
   标黄框；`already_filled` 的格子内容不变；密码框和验证码框没被扫到。结果记进试验记录（只记结构，不记值）。

## 不做

- 不点"下一步 / 保存 / 提交"；不处理验证码、登录、付款、签名（和 form-filler 硬性红线一致）。
- 不保存页面结构，不写对照表（第 2、3 层是下一步）。
- 不填列表字段，不填复选框。
