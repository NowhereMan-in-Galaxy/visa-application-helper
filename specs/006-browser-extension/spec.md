# Spec 006：浏览器插件（填表的"工具模式"）

- 状态：第一版完成（2026-09-29）：接口、插件、自动测试都通过；等项目主在自己的 Chrome 里装上试（验收第 3 条）
- 依据：试验 #10（`specs/002-guide-to-track/trials/README.md`）：引擎在 DS-160 上一次填完一页、没有报错，
  但 Agent 要逐字转发约一万字的脚本，一页一两分钟。项目主："还是希望用户可以解放自己的双手"，同意做插件。
- 相关：spec 005（通用填表引擎、对照清单）、`docs/SPEC-mvp.md` 第 1 条第 2 项和"禁止自动化的网站由用户决定"。

## 目标

填表时不经过 Agent：点一下"填本页"（或者对某个网站打开"自动填"，翻页就自动填），一两秒填完常见格子；
填不了的格子在页面上标红，旁边的侧边栏直接列出资料，点一下复制。Agent 只处理需要判断的事。

## 分工

```
官网页面 ◀─ 扫描 / 填写（插件里的 engine/scan.js、engine/fill.js）
   ▲
插件后台（background.js）──POST /api/ext/plan──▶ 本地服务（src/form_engine/match.py，同一套规则）
   │
侧边栏（sidepanel.html）：按钮、开关、结果、嵌入 http://127.0.0.1:8000/fill-helper.html（对照清单）
```

- **判断只在 Python 里**：插件只扫描和填写，"这一格填什么"全部由本地服务的 `plan()` 决定（和 MCP 工具同一个函数）。
- **引擎脚本只写一份**：`extension/engine/*.js` 由 `scripts/build_extension.py` 从 `src/form_engine/` 复制生成，
  测试检查两边一致；插件目录要能直接"加载已解压的扩展程序"，所以生成的文件也提交进仓库。
- 脚本在页面的 MAIN world 运行（和 Agent 模式、测试里一样）。填写计划通过 `window.__paPlan` 传给 fill.js，
  填完立即删除（计划里的值本来就要写进页面格子，不额外暴露）。

## 安全

- **固定插件 ID**：`manifest.json` 里放固定公钥（`key`），插件 ID 固定为 `ojaapcocccendgphoehaamchlchjfmok`
  （`src/api/extension.py` 里的 `EXTENSION_ID`，测试检查公钥和 ID 对得上）。私钥没有保存，也不需要。
- **本地服务只放行这一个插件，只放行 `/api/ext/` 下的接口**：Origin 是 `chrome-extension://<EXTENSION_ID>`
  的写请求，路径以 `/api/ext/` 开头才放行；别的插件 ID、别的路径照旧 403。Host 检查（防 DNS 重绑定）不变。
- **插件权限最小化**：
  - 固定权限：`storage`、`sidePanel`、`activeTab`、`scripting`、`tabs`（2026-09-29 项目主实测：没有 `tabs` 时侧边栏读不到当前网页地址，一直显示"打开一个网页再用"；`activeTab` 只在点图标那一刻给地址，页面一跳转就失效。Chrome 会把 `tabs` 描述成"读取浏览记录"，插件只用它读当前标签页的地址）；`host_permissions` 只有 `http://127.0.0.1:8000/*`。
  - "填本页"用 `activeTab`（用户点击才有权限，只对当前页）。
  - "自动填这个网站"要额外申请这个网站的权限（`optional_host_permissions`，Chrome 会弹窗让用户同意）。
- **禁止自动化的网站**：共享区 `community/site_policies.yaml` 记录网站条款（例如 ImmiAccount 第 4.5 条）。
  侧边栏在这类网站上显示条款原文和后果；"填本页"和"自动填"都要先勾选"我知道风险"才能用（每个网站单独勾，存在插件本地）。
- **敏感字段**：默认不填；侧边栏"敏感信息也填"开关打开后才填（存在插件本地）。
- 签名、付款、提交、验证码：插件不点任何按钮，只填格子。

## 接口（本地服务）

| 接口 | 输入 | 输出 |
|---|---|---|
| `GET /api/ext/status` | 无 | `{"ok": true, "extension_id": "..."}` |
| `GET /api/ext/site-policy?host=<域名>` | 域名 | `{"automation": "forbidden" / "unknown", "name", "clause", "consequence", "url", "checked"}`；没有记录时 `automation` 为 `unknown`，其余为 null |
| `POST /api/ext/plan` | `{"scan": 扫描结果（字符串或已展开的列表）, "sensitive": true/false}` | `plan()` 的报告（`fill`、`sensitive`、`missing`、`needs_format`、`manual`、`already_filled`、`unmatched`）+ `ops`（填写计划），**不含** `script` |

- 扫描结果格式有问题 → 422，信息说明原因。
- `plan()` 的返回值新增 `ops`（和 `script` 里嵌的计划相同）；MCP 工具 `plan_form_fill` 去掉 `ops` 只留 `script`，输出不变。

## `community/site_policies.yaml`

```yaml
sites:
  - host: online.immi.gov.au        # 网址的域名；子域名也算（例如 xx.online.immi.gov.au）
    name: 澳洲 ImmiAccount
    automation: forbidden            # forbidden / allowed
    clause: "4.5 You must not use software automation techniques or solutions when using ImmiAccount."
    consequence: 违反条款可被暂停或终止账户（第 8.3 条）
    url: https://online.immi.gov.au/lusc/termsAndConditions
    checked: 2026-09-29
    date_format: dd mmm yyyy         # 可选：日期框的写法，格子旁边没写格式时用（2026-09-29 加）
```

校验（`python -m core.guides` 里输出一行）：`host`、`name`、`automation`、`checked` 必填；`automation` 只能是
`forbidden` / `allowed`；`forbidden` 时 `clause` 必填；`host` 不重复；`date_format` 只能是 `dd/mm/yyyy`、`dd mmm yyyy`
这类写法（日 / 月 / 年三段，分隔符一致）。

**日期格式的优先顺序**：格子自己的占位符 / 标签里写了格式就用它；没写时用这个网站的 `date_format`；都没有才交给 Agent。
扫描结果里带着网站域名（`host`），`/api/ext/plan` 和 MCP 的 `plan_form_fill` 都按它查。

## 插件界面（侧边栏）

- 顶部：当前网站域名。连不上本地服务时只显示一行"连不上本地服务"和启动命令。
- 禁止自动化的网站：显示网站名、条款原文、后果，和一个"我知道风险，允许在这个网站自动填"勾选框。
- 按钮"填本页"；开关"自动填这个网站"、"敏感信息也填"。
- 填完的结果：填了几格；**请手动选**（`manual`）、**资料里没有**（`missing`）、**没认出**（`unmatched` + `needs_format`）、
  **敏感信息没填**（`sensitive`）分别列出。页面上这些格子标红色虚线框，填上的标黄色虚线框。
- 下面嵌入对照清单（`/fill-helper.html`），点一下复制。
- 不写说明性的提示文字（项目主偏好），只放需要操作的内容。

## 自动填

- 用户对某个网站打开"自动填"：申请该网站权限 → 记进插件本地的自动填列表。
- 这个网站的页面加载完成（`tabs.onUpdated` 的 `complete`）→ 自动执行和"填本页"一样的流程；插件图标上显示填了几格。
- 同一个标签页、同一个网址，60 秒内只自动填一次（ASP.NET 页面保存后网址不变，避免反复填）。
- 只填主页面，不填 iframe 里的格子。

## 验收（可以机械检查）

1. `uv run pytest` 全部通过，新增测试覆盖：
   - 插件公钥算出的 ID 等于 `EXTENSION_ID`；`manifest.json` 是合法 JSON，权限只有上面列的几项；
   - `extension/engine/*.js` 和 `scripts/build_extension.py` 生成的内容一致；
   - 插件 Origin 调 `/api/ext/plan` 成功；别的插件 ID、网页 Origin 调它 403；插件 Origin 调其他写接口 403；
   - `/api/ext/plan` 返回 `ops`、不返回 `script`；`sensitive: true` 时敏感字段进 `fill`；
   - `/api/ext/site-policy` 对 `online.immi.gov.au` 和它的子域名返回 `forbidden`，对 `example.com` 返回 `unknown`；
   - `site_policies.yaml` 校验能发现缺字段、重复 host。
2. 在无界面 Chrome 里，用插件目录下的 engine 脚本 + 模拟的插件接口，对测试表单跑一遍"填本页"流程：填上的格子和 spec 005 一致，没填的格子标红。
3. 项目主在自己的 Chrome 里"加载已解压的扩展程序"后：打开测试表单点"填本页"能填；打开 ImmiAccount 显示条款警告。（手动，结果记进试验记录）

## 第二版：清空重填 + 让 Agent 补填（2026-09-29 项目主同意）

项目主实测 DS-160"目前的工作"页后提出：①填错了要能一键清掉重填（引擎不覆盖已有内容）；②右边清单全是滚动不好找（已改：分类按钮、点"没认出"的格子自动定位）；③能不能联动 Agent。

### 清空本页自动填的

侧边栏按钮"清空本页自动填的"：把这一页上插件填过的格子（黄框，`title` 是"个人助手自动填写，请核对"）清空并去掉黄框；
文本框清成空、下拉框选回第一项，单选不动（清不掉"已选"又不触发页面刷新）。只在当前页运行，不碰别的格子。

### 让 Agent 补填

```
侧边栏「让 Agent 补填（N 格）」
  → 嵌入 http://127.0.0.1:8000/assist.html，把剩下的格子描述发给它（postMessage，只收发本项目插件的消息）
  → assist.html 启动一个 Agent 任务（POST /api/agent/jobs，kind = fill_assist）并显示对话
  → Agent 查基本信息、有需要就在对话里问用户，然后调 MCP 工具 submit_form_fills 交出"哪一格填什么"
  → 后台任务发现新交的结果，推给 assist.html（事件 fills）→ 转给侧边栏 → 插件后台用自带的 fill.js 填
```

- **Agent 碰不到官网**：`fill_assist` 任务没有浏览器权限，只能读基本信息（`get_personal_profile`、`get_profile_gaps`）、提议改基本信息（`propose_profile_update`）、交结果（`submit_form_fills`）。真正填写的是插件。
- **发给 Agent 的只有格子的描述**，不含页面上已填的值：
  `{"host", "sensitive": bool, "fields": [{"i", "kind", "label", "section", "name", "why", "options": [选项文字]}]}`；
  `why` 是插件没填的原因（没认出 / 资料里没有 / 格式看不出 / 请手动选 / 敏感信息）；`options` 只给下拉框和单选组，最多 80 项、每项最多 60 字；最多 60 个格子。
- **Agent 的规则**（写进 prompt）：只用基本信息里有的值或用户在对话里亲口说的；本次行程信息问用户，不写回基本信息；
  Security / Background 类法律声明题不填、不建议；`sensitive` 为 false 时不填敏感字段；下拉框 / 单选的值必须是 `options` 里的原文。
- **`submit_form_fills(fills, learn=[])`**：`fills` = `[{"i": 整数, "value": 文字}]`（每个值最多 2000 字）；
  `learn` = `[{"phrase": 格子上的说法, "path": 基本信息字段路径}]`，是"以后引擎也能认"的建议，这一版只记录、在对话里告诉用户，采纳进同义词表放 BACKLOG。
  记录写在材料根目录 `agent/form-fills.jsonl`（最多 50 条）。只有网页调起的任务（`PA_AGENT_UI=1`）能用。
- 插件拿到 `fills` 后：文本框直接填；下拉框 / 单选按选项原文找（和 spec 005 同一个 `pick`）；填上的标黄框；已有内容的照旧不覆盖。
- 用量上限 `fill_assist` = 2 美元折合（只处理剩下的几格）。

### 验收（第二版）

1. `uv run pytest` 通过，新增：`submit_form_fills` 写记录并能被 `side_events` 报成 `fills` 事件（只报新的）；
   不合法的 `i` / 过长的值 / 不存在的 `learn.path` 报错；`fill_assist` 的命令行没有浏览器工具、没有 `--chrome`、有 `submit_form_fills`；
   `/api/agent/jobs` 对 `fill_assist` 要求 `context.fields` 是 1–60 个带整数 `i` 的格子，否则 422；prompt 里有每一格的编号、标签和选项。
2. 项目主实测：DS-160 某一页"填本页"后点"让 Agent 补填"，Agent 填上剩下的格子（结果记进试验记录）。

## 不做（这一版）

- 不做 DS-160 的多行列表（Add Another）：等 DS-160 专用对照表（spec 005 第 2 层）。
- `learn` 建议自动写进同义词表：先只记录，见 BACKLOG。
- 不上架 Chrome 应用商店；只支持"加载已解压的扩展程序"。
- 不支持 Chrome 以外的浏览器。
