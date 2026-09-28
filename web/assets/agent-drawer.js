/* 界面里的 Agent 抽屉（spec 004 第 1 步：追问，只读）。guides.html 和 my.html 共用。
 *
 * 右下角「问 Agent」按钮 → 右侧抽屉：顶部是和当前页面相关的快捷按钮，下面是对话和输入框。
 * 抽屉根据地址栏判断你在看哪份攻略 / 哪件办事，把 id 一起发给 Agent。
 * 同一个抽屉里的追问接着同一次对话（session_id）；关掉抽屉或换页面后重新开始。
 */
(function () {
  "use strict";

  var QUICK = {
    guides: ["我正在办的事进展怎么样？"],
    guide: ["这份攻略说了什么？"],
    track: ["我还缺什么？", "下一步做什么？"],
    profile: ["查查我的基本信息还缺什么"],
    materials: [],
    travel: [],
  };

  var state = {
    open: false, status: null, ackApiKey: false,
    sessionId: null, contextKey: null, jobId: null, source: null,
  };

  function h(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "onclick") node.addEventListener("click", attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return node;
  }

  function currentContext() {
    var hash = location.hash || "";
    if (/my\.html$/.test(location.pathname)) {
      return { page: hash === "#profile" ? "profile" : hash === "#travel" ? "travel" : "materials" };
    }
    var m = hash.match(/^#\/(guide|track)\/([^/?#]+)/);
    if (m && m[1] === "guide") return { page: "guide", guide_id: decodeURIComponent(m[2]) };
    if (m && m[1] === "track") return { page: "track", track_id: decodeURIComponent(m[2]) };
    return { page: "guides" };
  }

  // 只做最基本的格式：先整体转义，再处理 **加粗** 和 `代码`，不会插入任何外来 HTML
  function renderText(text) {
    var esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return esc.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`\n]+)`/g, "<code>$1</code>");
  }

  // ---- DOM ----
  var fab = h("button", { class: "agent-fab", type: "button", "aria-expanded": "false", text: "问 Agent" });
  var closeBtn = h("button", { class: "agent-close", type: "button", "aria-label": "关闭", text: "✕" });
  var notice = h("div", { class: "agent-notice", hidden: "" });
  var quick = h("div", { class: "agent-quick" });
  var log = h("div", { class: "agent-log", "aria-live": "polite" });
  var input = h("textarea", { class: "agent-input", rows: "2", placeholder: "输入问题，回车发送（Shift+回车换行）" });
  var sendBtn = h("button", { class: "primary agent-send", type: "button", text: "发送" });
  var cancelBtn = h("button", { class: "agent-cancel", type: "button", text: "取消", hidden: "" });
  var drawer = h("aside", { class: "agent-drawer", role: "dialog", "aria-label": "Agent", hidden: "" }, [
    h("div", { class: "agent-head" }, [h("strong", { text: "Agent" }), h("small", { class: "muted", text: "只读 · 在你电脑上运行" }), closeBtn]),
    notice, quick, log,
    h("div", { class: "agent-foot" }, [input, h("div", { class: "agent-actions" }, [cancelBtn, sendBtn])]),
  ]);

  function busy() { return !!state.jobId; }

  function blocked() {
    var s = state.status;
    if (!s || !s.available || s.auth_method === "none") return true;
    return needsApiKeyAck() && !state.ackApiKey;
  }

  function needsApiKeyAck() {
    var s = state.status;
    return !!s && (s.api_key_env || (s.auth_method && s.auth_method !== "claude.ai" && s.auth_method !== "none"));
  }

  function syncControls() {
    var off = busy() || blocked();
    sendBtn.disabled = off;
    input.disabled = blocked();
    cancelBtn.hidden = !busy();
    Array.prototype.forEach.call(quick.querySelectorAll("button"), function (b) { b.disabled = off; });
  }

  function renderNotice() {
    var s = state.status;
    notice.innerHTML = "";
    notice.className = "agent-notice";
    if (!s) { notice.hidden = true; return; }
    if (!s.available) {
      notice.className += " warn";
      notice.append("没有检测到 Claude Code。装好后在终端运行一次 ", h("code", { text: "claude" }), " 登录，然后刷新本页。");
    } else if (s.auth_method === "none") {
      notice.className += " warn";
      notice.append("Claude Code 还没登录。在终端运行 ", h("code", { text: "claude" }), " 按提示登录，然后刷新本页。");
    } else if (needsApiKeyAck() && !state.ackApiKey) {
      notice.className += " warn";
      notice.append("当前按 API 用量计费，会产生实际费用（检测到 API key 登录或 ANTHROPIC_API_KEY 环境变量）。 ",
        h("button", { type: "button", text: "我知道了", onclick: function () { state.ackApiKey = true; renderNotice(); syncControls(); } }));
    } else { notice.hidden = true; return; }
    notice.hidden = false;
  }

  function renderQuick() {
    quick.innerHTML = "";
    (QUICK[currentContext().page] || []).forEach(function (q) {
      quick.appendChild(h("button", { type: "button", text: q, onclick: function () { ask(q); } }));
    });
    syncControls();
  }

  function resetConversation() {
    state.sessionId = null;
    log.innerHTML = "";
    log.appendChild(h("p", { class: "muted agent-hint", text: "可以问和当前页面有关的问题。它会先查你的真实数据再回答；现在只能看，不能帮你改。" }));
  }

  function addLine(cls, text) {
    var p = h("div", { class: "agent-msg " + cls, text: text || "" });
    log.appendChild(p);
    log.scrollTop = log.scrollHeight;
    return p;
  }

  function ask(question) {
    question = (question || "").trim();
    if (!question || busy() || blocked()) return;
    var ctx = currentContext();
    var key = JSON.stringify(ctx);
    if (key !== state.contextKey) { state.contextKey = key; state.sessionId = null; }
    var hint = log.querySelector(".agent-hint");
    if (hint) hint.remove();
    addLine("user", question);
    var progress = addLine("progress", "正在启动…");
    var answer = null, answerText = "";
    input.value = "";
    state.jobId = "pending";
    syncControls();

    fetch("/api/agent/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "ask", input: question, context: ctx, session_id: state.sessionId }),
    }).then(function (r) {
      return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || ("出错了（" + r.status + "）")); return b; });
    }).then(function (b) {
      state.jobId = b.job_id;
      var src = new EventSource("/api/agent/jobs/" + encodeURIComponent(b.job_id) + "/events");
      state.source = src;
      function finish() { src.close(); state.source = null; state.jobId = null; progress.remove(); syncControls(); }
      src.addEventListener("progress", function (e) { progress.textContent = JSON.parse(e.data).text + "…"; });
      src.addEventListener("text", function (e) {
        if (!answer) answer = addLine("agent", "");
        answerText += JSON.parse(e.data).text;
        answer.innerHTML = renderText(answerText);
        log.scrollTop = log.scrollHeight;
      });
      src.addEventListener("done", function (e) {
        var d = JSON.parse(e.data);
        state.sessionId = d.session_id || state.sessionId;
        finish();
        if (!answer) addLine("agent", "（没有回答）");
        if (typeof d.cost_usd === "number") {
          addLine("cost", needsApiKeyAck()
            ? "本次用量约 $" + d.cost_usd.toFixed(2) + "（按 API 计费）"
            : "本次折合约 $" + d.cost_usd.toFixed(2) + "（订阅用户计入额度，不另收费）");
        }
      });
      src.addEventListener("error", function (e) {
        if (e.data) {
          var d = JSON.parse(e.data);
          state.sessionId = d.session_id || state.sessionId;
          finish();
          addLine("error", d.text);
        } else if (state.source === src) {
          finish();
          addLine("error", "和本地服务的连接断了，请重试。");
        }
      });
    }).catch(function (err) {
      state.jobId = null;
      progress.remove();
      addLine("error", err.message);
      syncControls();
    });
  }

  function refreshStatus() {
    return fetch("/api/agent/status").then(function (r) { return r.json(); })
      .then(function (s) { state.status = s; })
      .catch(function () { state.status = { available: false }; })
      .then(function () { renderNotice(); syncControls(); });
  }

  function setOpen(open) {
    state.open = open;
    drawer.hidden = !open;
    fab.hidden = open;
    fab.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("agent-open", open);
    if (open) {
      if (!busy()) resetConversation();
      state.contextKey = JSON.stringify(currentContext());
      renderQuick();
      refreshStatus();
      input.focus();
    }
  }

  fab.addEventListener("click", function () { setOpen(true); });
  closeBtn.addEventListener("click", function () { setOpen(false); });
  sendBtn.addEventListener("click", function () { ask(input.value); });
  cancelBtn.addEventListener("click", function () {
    if (state.jobId && state.jobId !== "pending") fetch("/api/agent/jobs/" + encodeURIComponent(state.jobId) + "/cancel", { method: "POST" });
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && state.open) setOpen(false); });
  window.addEventListener("hashchange", function () {
    if (!state.open) return;
    var key = JSON.stringify(currentContext());
    if (key !== state.contextKey && !busy()) { state.contextKey = key; resetConversation(); }
    renderQuick();
  });

  document.body.appendChild(fab);
  document.body.appendChild(drawer);
})();
