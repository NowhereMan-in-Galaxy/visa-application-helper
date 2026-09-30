// 在线演示站（docs/demo/site.md）专用，由 scripts/build_demo_site.py 放到每个页面最前面。
// 页面照常请求 /api/...；这里把 GET 换成读构建时导出的 data/*.json（试用模式的虚构资料），
// 其余请求（保存、上传、删除、Agent）一律回"只能看"。不改页面本身的任何代码。
(function () {
  "use strict";
  window.PA_DEMO = true;
  var realFetch = window.fetch.bind(window);
  var READ_ONLY = "这是在线演示，只能看不能改。装到自己电脑上就能用全部功能。";

  // 和 build_demo_site.py 的 data_file() 一致：api/ 后面的路径和查询串里，字母数字 . - 以外的字符都换成 _xx（十六进制）
  function dataFile(url) {
    var u = new URL(url, location.href);
    var at = u.pathname.indexOf("/api/");
    if (at < 0) return null;
    var key = u.pathname.slice(at + 5) + u.search;
    var safe = "";
    for (var i = 0; i < key.length; i++) {
      var c = key.charAt(i);
      safe += /[A-Za-z0-9.-]/.test(c) ? c : "_" + key.charCodeAt(i).toString(16);
    }
    return "data/" + safe + ".json";
  }

  function json(status, body) {
    return new Response(JSON.stringify(body), { status: status, headers: { "Content-Type": "application/json" } });
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : input.url;
    var file = dataFile(url);
    if (!file) return realFetch(input, init);
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    if (method !== "GET") return Promise.resolve(json(403, { detail: READ_ONLY }));
    return realFetch(file).then(function (r) { return r.ok ? r : json(404, { detail: "演示版里没有这项数据。" }); });
  };

  // 顶部一行说明 + 隐藏演示里用不了的入口（问 Agent、新建攻略）
  var style = document.createElement("style");
  style.textContent = ".agent-fab, .new-guide-btn { display: none !important; }" +
    "#pa-demo-bar { background: #2b2f26; color: #f4f1e8; font: 13px/1.5 -apple-system, 'PingFang SC', sans-serif; padding: 7px 16px; text-align: center; }" +
    "#pa-demo-bar a { color: #d9e4c8; }";
  document.head.appendChild(style);
  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.createElement("div");
    bar.id = "pa-demo-bar";
    bar.innerHTML = "在线演示：资料都是虚构的，只能看不能改。" +
      "<a href=\"https://github.com/NowhereMan-in-Galaxy/visa-application-helper\">装到自己电脑上 →</a>";
    document.body.insertBefore(bar, document.body.firstChild);
  });
})();
