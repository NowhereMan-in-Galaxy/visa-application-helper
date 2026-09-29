/* 界面里的 Agent（spec 004）。guides.html 和 my.html 共用，要在页面自己的脚本之前加载。
 *
 * 两部分：
 * 1. window.AgentChat.create(options)：一个可复用的对话窗口（状态提示、对话记录、进度、输入框、取消）。
 *    右侧抽屉（追问）和「新建攻略」窗口都用它。
 * 2. 右下角「问 Agent」按钮 + 右侧抽屉：只读追问，快捷按钮按当前页面变化。
 *    抽屉根据地址栏判断你在看哪份攻略 / 哪件办事，把 id 一起发给 Agent；在「新建攻略」页面不显示（那里有自己的对话窗口）。
 */
(function () {
  "use strict";

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

  // 只做最基本的格式：先整体转义，再处理 **加粗** 和 `代码`，不会插入任何外来 HTML
  function renderText(text) {
    var esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return esc.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`\n]+)`/g, "<code>$1</code>");
  }

  // ---------- Agent 是否可用（整页共用一份） ----------

  var status = null, statusPromise = null, ackApiKey = false;
  var statusListeners = [];

  function loadStatus(force) {
    if (!statusPromise || force) {
      statusPromise = fetch("/api/agent/status").then(function (r) { return r.json(); })
        .catch(function () { return { available: false }; })
        .then(function (s) { status = s; statusListeners.forEach(function (f) { f(); }); return s; });
    }
    return statusPromise;
  }

  function paidByApi() {
    return !!status && (status.api_key_env || (status.auth_method && status.auth_method !== "claude.ai" && status.auth_method !== "none"));
  }

  function blocked() {
    if (!status || !status.available || status.auth_method === "none") return true;
    return paidByApi() && !ackApiKey;
  }

  // ---------- Agent 改了数据：撤销、确认卡片（spec 004 第 3 步） ----------

  // 通知页面重新读数据（guides.js / my.js 监听这个事件）
  function dataChanged(detail) {
    window.dispatchEvent(new CustomEvent("agent-data-changed", { detail: detail || {} }));
  }

  function post(url) {
    return fetch(url, { method: "POST" }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) { if (!r.ok) throw new Error(b.detail || ("出错了（" + r.status + "）")); return b; });
    });
  }

  // "已勾上：递交材料 [撤销]"
  function activityLine(a) {
    var btn = h("button", { type: "button", class: "agent-undo", text: "撤销" });
    var line = h("div", { class: "agent-msg activity" }, [h("span", { text: "✓ " + a.text }), btn]);
    btn.addEventListener("click", function () {
      btn.disabled = true;
      post("/api/agent/undo/" + encodeURIComponent(a.activity_id))
        .then(function () { line.classList.add("undone"); btn.replaceWith(h("span", { class: "muted", text: "已撤销" })); dataChanged({ track_id: a.track_id }); })
        .catch(function (err) { btn.disabled = false; line.appendChild(h("div", { class: "agent-inline-error", text: err.message })); });
    });
    dataChanged({ track_id: a.track_id });
    return line;
  }

  function showValue(v) {
    if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) return "（空）";
    if (v === true) return "是";
    if (v === false) return "否";
    return typeof v === "object" ? JSON.stringify(v) : String(v);
  }

  // 改基本信息的确认卡片：旧值 → 新值，点确认才写入
  function proposalCard(p) {
    var status = h("div", { class: "agent-card-status" });
    var ok = h("button", { type: "button", class: "primary", text: "确认修改" });
    var no = h("button", { type: "button", text: "不改" });
    var card = h("div", { class: "agent-card" }, [
      h("strong", { text: "Agent 想修改你的基本信息" }),
      h("ul", null, p.changed.map(function (c) {
        // 名字只留最后两段（"目前的单位或学校 › 工作电话"），分组名在卡片里是多余的
        var name = c.label.split(" › ").slice(-2).join(" › ");
        var before = c.before === null || c.before === undefined || c.before === "" ? null : showValue(c.before);
        return h("li", null, [
          h("span", { class: "change-label", text: name }),
          before ? h("del", { text: before }) : h("span", { class: "muted", text: "（空）" }),
          " → ",
          h("ins", { text: showValue(c.after) }),
        ]);
      })),
      h("div", { class: "agent-card-actions" }, [no, ok]),
      status,
    ]);
    function done(text) { ok.remove(); no.remove(); status.textContent = text; }
    ok.addEventListener("click", function () {
      ok.disabled = no.disabled = true;
      post("/api/agent/profile-proposals/" + encodeURIComponent(p.proposal_id) + "/confirm")
        .then(function () { done("✓ 已写入基本信息"); dataChanged({ profile_group: p.group }); })
        .catch(function (err) { ok.disabled = no.disabled = false; status.textContent = err.message; });
    });
    no.addEventListener("click", function () {
      ok.disabled = no.disabled = true;
      post("/api/agent/profile-proposals/" + encodeURIComponent(p.proposal_id) + "/reject")
        .then(function () { done("没有修改"); })
        .catch(function (err) { ok.disabled = no.disabled = false; status.textContent = err.message; });
    });
    return card;
  }

  // ---------- 1. 可复用的对话窗口 ----------

  /* options:
   *   kind          "ask" | "create_guide"
   *   context()     返回发给后端的上下文（页面、攻略 / 办事 id、攻略类型、草稿 id…）
   *   hint          空对话时的说明文字
   *   placeholder   输入框提示
   *   rows          输入框行数
   *   sendLabel()   发送按钮上的字（可随状态变化）
   *   validate(text) 返回错误文字则不发送
   *   onEvent(type, data)  收到事件时回调（例如 "draft"、"done"）
   */
  function create(options) {
    var sessionId = null, jobId = null, source = null;

    var notice = h("div", { class: "agent-notice", hidden: "" });
    var log = h("div", { class: "agent-log", "aria-live": "polite" });
    var input = h("textarea", { class: "agent-input", rows: String(options.rows || 2), placeholder: options.placeholder || "" });
    var sendBtn = h("button", { class: "primary agent-send", type: "button" });
    var cancelBtn = h("button", { class: "agent-cancel", type: "button", text: "取消", hidden: "" });
    var inputError = h("small", { class: "agent-input-error", hidden: "" });
    var quick = h("div", { class: "agent-quick" });
    var root = h("div", { class: "agent-chat" }, [
      notice, quick, log,
      h("div", { class: "agent-foot" }, [input, inputError, h("div", { class: "agent-actions" }, [cancelBtn, sendBtn])]),
    ]);

    function busy() { return !!jobId; }

    function sync() {
      var err = options.validate ? options.validate(input.value) : null;
      inputError.hidden = !err;
      inputError.textContent = err || "";
      sendBtn.textContent = options.sendLabel ? options.sendLabel(!!sessionId) : "发送";
      sendBtn.disabled = busy() || blocked() || !!err;
      input.disabled = blocked();
      cancelBtn.hidden = !busy();
      Array.prototype.forEach.call(quick.querySelectorAll("button"), function (b) { b.disabled = busy() || blocked(); });
    }

    function renderNotice() {
      notice.innerHTML = "";
      notice.className = "agent-notice";
      if (!status) { notice.hidden = true; return; }
      if (!status.available) {
        notice.className += " warn";
        notice.append("没有检测到 Claude Code。装好后在终端运行一次 ", h("code", { text: "claude" }), " 登录，然后刷新本页。也可以先 ",
          h("button", { type: "button", text: "复制给 Agent", onclick: copyForAgent }), "，粘贴到你自己用的 AI 里。");
      } else if (status.auth_method === "none") {
        notice.className += " warn";
        notice.append("Claude Code 还没登录。在终端运行 ", h("code", { text: "claude" }), " 按提示登录，然后刷新本页。");
      } else if (paidByApi() && !ackApiKey) {
        notice.className += " warn";
        notice.append("当前按 API 用量计费，会产生实际费用（检测到 API key 登录或 ANTHROPIC_API_KEY 环境变量）。 ",
          h("button", { type: "button", text: "我知道了", onclick: function () { ackApiKey = true; statusListeners.forEach(function (f) { f(); }); } }));
      } else { notice.hidden = true; return; }
      notice.hidden = false;
    }

    function onStatus() { renderNotice(); sync(); }

    // 没装 Claude Code 时的退路：把当前页面和输入框里的问题拼成一段话，复制到剪贴板
    function copyForAgent(ev) {
      var ctx = options.context();
      var text = [
        "我在用 personal-assistant 这个本地办事助手（仓库里有 AGENTS.md、.claude/skills/ 和 .mcp.json）。",
        "当前页面：" + (ctx.page || "") + (ctx.guide_id ? "，攻略 id：" + ctx.guide_id : "") + (ctx.track_id ? "，办事 id：" + ctx.track_id : "") +
          (ctx.guide_type ? "，要新建的攻略类型：" + ctx.guide_type : ""),
        options.kind === "create_guide" ? "请按 .claude/skills/guide-author（读小红书用 xhs-reader）把下面的内容整理成攻略：" : "我的问题：",
        input.value.trim() || "（在这里写你的问题）",
      ].join("\n");
      var btn = ev.target;
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
        .then(function () { btn.textContent = "已复制"; })
        .catch(function () { window.prompt("复制下面这段话：", text); });
    }
    statusListeners.push(onStatus);

    function addLine(cls, text) {
      var p = h("div", { class: "agent-msg " + cls, text: text || "" });
      log.appendChild(p);
      log.scrollTop = log.scrollHeight;
      return p;
    }

    function reset() {
      if (busy()) return;
      sessionId = null;
      log.innerHTML = "";
      if (options.hint) log.appendChild(h("p", { class: "muted agent-hint", text: options.hint }));
      sync();
    }

    function send(text) {
      text = (text || "").trim();
      if (!text || busy() || blocked()) return;
      if (options.validate && options.validate(text)) return;
      var hint = log.querySelector(".agent-hint");
      if (hint) hint.remove();
      addLine("user", text);
      var progress = addLine("progress", "正在启动…");
      var steps = h("details", { class: "agent-steps" }, [h("summary", { text: "过程" })]);
      var answer = null, answerText = "", stepCount = 0;
      input.value = "";
      jobId = "pending";
      sync();

      fetch("/api/agent/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: options.kind, input: text, context: options.context(), session_id: sessionId }),
      }).then(function (r) {
        return r.json().then(function (b) { if (!r.ok) throw new Error(b.detail || ("出错了（" + r.status + "）")); return b; });
      }).then(function (b) {
        jobId = b.job_id;
        var src = new EventSource("/api/agent/jobs/" + encodeURIComponent(b.job_id) + "/events");
        source = src;
        function finish() {
          src.close(); source = null; jobId = null; progress.remove();
          if (stepCount) { steps.querySelector("summary").textContent = "过程（" + stepCount + " 步）"; log.insertBefore(steps, answer); }
          sync();
        }
        src.addEventListener("progress", function (e) {
          var t = JSON.parse(e.data).text;
          // 调用工具之前说的话（"先看一下…""读第二篇"）属于过程，挪进「过程」，最后一段才算回答
          if (answer) {
            steps.appendChild(h("div", { class: "agent-step-note", text: "💬 " + answerText.trim() }));
            answer.remove();
            answer = null;
            answerText = "";
          }
          progress.textContent = t + "…";
          stepCount += 1;
          steps.appendChild(h("div", { text: t }));
        });
        src.addEventListener("text", function (e) {
          if (!answer) answer = addLine("agent", "");
          answerText += JSON.parse(e.data).text;
          answer.innerHTML = renderText(answerText);
          log.appendChild(progress);  // 进度行保持在最下面
          log.scrollTop = log.scrollHeight;
        });
        src.addEventListener("draft", function (e) { if (options.onEvent) options.onEvent("draft", JSON.parse(e.data)); });
        src.addEventListener("activity", function (e) { log.appendChild(activityLine(JSON.parse(e.data))); log.appendChild(progress); });
        src.addEventListener("proposal", function (e) { log.appendChild(proposalCard(JSON.parse(e.data))); log.appendChild(progress); });
        // 填表插件"让 Agent 补填"：Agent 交出了"哪一格填什么"（spec 006 第二版）
        src.addEventListener("fills", function (e) {
          var d = JSON.parse(e.data);
          log.appendChild(h("div", { class: "agent-msg activity", text: "✓ 已交给插件填 " + d.fills.length + " 格" }));
          log.appendChild(progress);
          if (options.onEvent) options.onEvent("fills", d);
        });
        src.addEventListener("done", function (e) {
          var d = JSON.parse(e.data);
          sessionId = d.session_id || sessionId;
          finish();
          if (!answer) addLine("agent", "（没有回答）");
          if (options.onEvent) options.onEvent("done", d);
        });
        src.addEventListener("error", function (e) {
          if (e.data) {
            var d = JSON.parse(e.data);
            sessionId = d.session_id || sessionId;
            finish();
            addLine("error", d.text);
            if (options.onEvent) options.onEvent("error", d);
          } else if (source === src) {
            finish();
            addLine("error", "和本地服务的连接断了，请重试。");
          }
        });
      }).catch(function (err) {
        jobId = null;
        progress.remove();
        addLine("error", err.message);
        sync();
      });
    }

    sendBtn.addEventListener("click", function () { send(input.value); });
    cancelBtn.addEventListener("click", function () {
      if (jobId && jobId !== "pending") fetch("/api/agent/jobs/" + encodeURIComponent(jobId) + "/cancel", { method: "POST" });
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !options.enterNewline) { e.preventDefault(); send(input.value); }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(input.value); }
    });
    input.addEventListener("input", sync);

    reset();
    loadStatus().then(onStatus);

    return {
      root: root, input: input, send: send, reset: reset, busy: busy,
      setQuick: function (labels) {
        quick.innerHTML = "";
        labels.forEach(function (q) { quick.appendChild(h("button", { type: "button", text: q, onclick: function () { send(q); } })); });
        sync();
      },
      destroy: function () {
        var i = statusListeners.indexOf(onStatus);
        if (i !== -1) statusListeners.splice(i, 1);
      },
    };
  }

  window.AgentChat = { create: create, loadStatus: loadStatus };

  // 只要对话窗口、不要右下角按钮的页面（例如填表插件里的补填页）在 <body> 上加 data-no-drawer
  if (document.body && document.body.hasAttribute("data-no-drawer")) return;

  // ---------- 2. 右下角按钮 + 抽屉（只读追问） ----------

  var QUICK = {
    guides: ["带我上手", "我正在办的事进展怎么样？"],
    guide: ["这份攻略说了什么？"],
    track: ["我还缺什么？", "下一步做什么？"],
    draft: ["这份草稿还有哪些不确定的地方？"],
    profile: ["带我上手", "查查我的基本信息还缺什么"],
    materials: ["我有哪些材料快过期了？"],
    travel: [],
  };

  function currentContext() {
    var hash = location.hash || "";
    if (/my\.html$/.test(location.pathname)) {
      return { page: hash === "#profile" ? "profile" : hash === "#travel" ? "travel" : "materials" };
    }
    if (/^#\/new(\/|$)/.test(hash)) return { page: "new" };
    var m = hash.match(/^#\/(guide|track)\/([^/?#]+)/);
    if (m && m[1] === "guide") return { page: "guide", guide_id: decodeURIComponent(m[2]) };
    if (m && m[1] === "track") return { page: "track", track_id: decodeURIComponent(m[2]) };
    if (/^#\/draft\//.test(hash)) return { page: "draft" };
    return { page: "guides" };
  }

  var chat = create({
    kind: "ask",
    context: currentContext,
    hint: "可以问和当前页面有关的问题，也可以让它帮你改进度，比如「签证中心预约好了，帮我勾上」。它改了什么会写在这里，随时能撤销；改基本信息前会先让你确认。新建攻略请到攻略库点「+ 新建攻略」。",
    placeholder: "输入问题，回车发送（Shift+回车换行）",
  });
  var fab = h("button", { class: "agent-fab", type: "button", "aria-expanded": "false", text: "问 Agent" });
  var closeBtn = h("button", { class: "agent-close", type: "button", "aria-label": "关闭", text: "✕" });
  var drawer = h("aside", { class: "agent-drawer", role: "dialog", "aria-label": "Agent", hidden: "" }, [
    h("div", { class: "agent-head" }, [h("strong", { text: "Agent" }), h("small", { class: "muted", text: "在你电脑上运行" }), closeBtn]),
    chat.root,
  ]);
  var open = false, contextKey = null;

  function syncFab() {
    var onNew = currentContext().page === "new";
    fab.hidden = open || onNew;
    if (onNew && open) setOpen(false);
  }

  function setOpen(value) {
    open = value;
    drawer.hidden = !open;
    fab.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("agent-open", open);
    syncFab();
    if (open) {
      contextKey = JSON.stringify(currentContext());
      chat.reset();
      chat.setQuick(QUICK[currentContext().page] || []);
      loadStatus(true);
      chat.input.focus();
    }
  }

  fab.addEventListener("click", function () { setOpen(true); });
  closeBtn.addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && open) setOpen(false); });
  window.addEventListener("hashchange", function () {
    syncFab();
    if (!open) return;
    var key = JSON.stringify(currentContext());
    if (key !== contextKey && !chat.busy()) { contextKey = key; chat.reset(); }
    chat.setQuick(QUICK[currentContext().page] || []);
  });

  document.body.appendChild(fab);
  document.body.appendChild(drawer);
  syncFab();
})();
