# README 动图和总览图怎么重做

`visa-form.html` 是一张虚构的签证表，不对应任何真实网站。填写用的是项目真实的填表引擎（`src/form_engine/scan.js`、`fill.js`）。

1. 在仓库根目录运行 `uv run python -m http.server 8002`，浏览器打开 <http://127.0.0.1:8002/docs/demo/visa-form.html>。
2. 表单改了的话：在页面上读出 `window.__paScanText`，存成 `visa-form.scan.json`，再运行 `uv run python docs/demo/make_plan.py` 生成 `visa-form.plan.json`（用试用模式的虚构资料）。
3. 点右上角「填本页」连续填完；录动图时在控制台一次次运行 `paStep()`，每填一格截一张，最后 `paDone()`，再把截图合成 GIF（`docs/screenshots/fill-demo.gif`）。

流程总览图：同样开着上面的本地服务，打开 <http://127.0.0.1:8002/docs/demo/overview.html>，截 `#board` 那一块，存成 `docs/screenshots/overview.png`。
