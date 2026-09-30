# 在线演示站

网址：<https://nowhereman-in-galaxy.github.io/visa-application-helper/>

不装软件也能点着看的只读版本：攻略库（排在最前面）、攻略详情、一件示例办事、我的资料、填表对照。资料全部来自试用模式（`src/api/demo.py`），是虚构的。

## 怎么做的

- 网页本身不改。构建时（`scripts/build_demo_site.py`）用试用模式的资料，请求页面会用到的每个 GET 接口，把结果存成 `data/*.json`。
- 每个页面最前面加 `demo-shim.js`：把 `/api/...` 的读取换成读这些文件；保存、上传、删除、Agent 一律回"只能看"；隐藏「问 Agent」「新建攻略」；顶部一行说明。
- 首页检查 `window.PA_DEMO`，演示站里把攻略库排在「办理中」前面（`web/assets/guides.js`）。
- `.github/workflows/pages.yml`：每次推送到 main 自动重新生成并发布到 GitHub Pages。
- 构建时发现数据里有本机路径（例如 `export-locations` 这类接口）就报错不发布；这类接口在 `FIXED` 里给固定回答。

## 页面新加了 GET 接口怎么办

在 `build_demo_site.py` 的 `collect()` 里加上，否则演示站上那一块会显示"演示版里没有这项数据"。本地试：

```bash
uv run python scripts/build_demo_site.py _site
cd _site && uv run python -m http.server 8004   # 打开 http://127.0.0.1:8004/
```
