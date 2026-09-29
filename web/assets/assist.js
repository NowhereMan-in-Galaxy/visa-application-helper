// 填表插件"让 Agent 补填"的对话页（specs/006-browser-extension 第二版）。
// 只和本项目插件通信：收 {type: "pa-assist", host, sensitive, fields}，回 {type: "pa-fills", fills}。
(function () {
  "use strict";

  var EXTENSION = "chrome-extension://ojaapcocccendgphoehaamchlchjfmok";
  var ctx = { host: null, sensitive: false, fields: [], track_id: null };

  var chat = window.AgentChat.create({
    kind: "fill_assist",
    rows: 2,
    placeholder: "回答 Agent 的问题，回车发送",
    context: function () { return { page: "fill_assist", host: ctx.host, sensitive: ctx.sensitive, fields: ctx.fields, track_id: ctx.track_id }; },
    onEvent: function (type, data) {
      if (type === "fills" && window.parent !== window) {
        window.parent.postMessage({ type: "pa-fills", fills: data.fills, learn: data.learn || [] }, EXTENSION);
      }
    },
  });
  document.getElementById("chat").appendChild(chat.root);

  window.addEventListener("message", function (ev) {
    if (ev.origin !== EXTENSION || !ev.data || ev.data.type !== "pa-assist") return;
    ctx = { host: ev.data.host || null, sensitive: !!ev.data.sensitive, fields: ev.data.fields || [], track_id: ev.data.track_id || null };
    // 先确认 Agent 可用（状态还没查回来时 send 会被当成"不可用"忽略掉）
    window.AgentChat.loadStatus().then(function () {
      chat.reset();
      chat.send("帮我补填这一页剩下的 " + ctx.fields.length + " 格");
    });
  });

  // 告诉插件：页面准备好了，可以发格子过来
  if (window.parent !== window) window.parent.postMessage({ type: "pa-assist-ready" }, EXTENSION);
})();
