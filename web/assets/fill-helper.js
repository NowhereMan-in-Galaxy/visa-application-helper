// 填表对照清单（specs/005-fill-engine）：GET /api/fill-helper → 分组列出，点一下复制到剪贴板。
// 这个页面只读本机的基本信息，不读、不改任何官网页面；粘贴到官网上的是用户自己。
(function () {
  "use strict";

  var DONE_KEY = "pa-fill-helper-done"; // 本次填表已复制过的项（sessionStorage，关掉窗口就清空）
  var data = null;
  var done = loadDone();

  function $(id) { return document.getElementById(id); }

  function el(tag, props) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v === undefined || v === null || v === false) return;
      if (k === "text") node.textContent = String(v);
      else if (k === "class") node.className = v;
      else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    });
    (function add(child) {
      if (child === null || child === undefined || child === false) return;
      if (Array.isArray(child)) { child.forEach(add); return; }
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    })(Array.prototype.slice.call(arguments, 2));
    return node;
  }

  function loadDone() {
    try { return new Set(JSON.parse(sessionStorage.getItem(DONE_KEY) || "[]")); } catch (e) { return new Set(); }
  }
  function saveDone() {
    try { sessionStorage.setItem(DONE_KEY, JSON.stringify(Array.from(done))); } catch (e) { /* 存不了就只在内存里记 */ }
  }

  function toast(text) {
    var t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.hidden = true; }, 1400);
  }

  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    // 退路：老办法复制（不是 localhost / https 时剪贴板接口不可用）
    return new Promise(function (resolve, reject) {
      var ta = el("textarea", { style: "position:fixed;opacity:0" });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      var ok = document.execCommand("copy");
      ta.remove();
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }

  function matches(item, group, words) {
    if (!words.length) return true;
    var hay = [item.label, group.label, item.path].concat(item.terms || []).join(" ").toLowerCase();
    return words.every(function (w) { return hay.indexOf(w) >= 0; });
  }

  function valueButton(item, v) {
    var masked = item.sensitive && !$("reveal").checked;
    return el(
      "button",
      {
        type: "button",
        class: "fh-val" + (masked ? " masked" : ""),
        title: "点一下复制" + (v.hint ? "（" + v.hint + "）" : ""),
        onclick: function () {
          copy(v.text).then(function () {
            done.add(item.path);
            saveDone();
            toast("已复制：" + item.label.split(" › ").pop());
            render();
          }, function () { toast("复制失败，请手动选中"); });
        },
      },
      masked ? "••••••" : v.text,
      v.hint ? el("small", { class: "muted", text: v.hint }) : null
    );
  }

  function render() {
    var list = $("list");
    list.replaceChildren();
    if (!data) return;
    var words = $("q").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var total = 0, shown = 0;
    data.groups.forEach(function (g) {
      var rows = g.items.filter(function (it) { total++; return matches(it, g, words); });
      shown += rows.length;
      if (!rows.length) return;
      list.append(el(
        "section",
        { class: "fh-group" },
        el("h2", { text: g.label }),
        rows.map(function (it) {
          return el(
            "div",
            { class: "fh-row" + (done.has(it.path) ? " done" : "") },
            el("div", { class: "fh-label", text: it.label + (it.sensitive ? "（敏感）" : "") }),
            el("div", { class: "fh-vals" }, it.values.map(function (v) { return valueButton(it, v); }))
          );
        })
      ));
    });
    if (!total) {
      list.append(el("p", { class: "fh-empty" }, "基本信息还是空的。先到 ", el("a", { href: "/my.html#profile", target: "_blank", text: "我的资料 › 基本信息" }), " 填一下。"));
    } else if (!shown) {
      list.append(el("p", { class: "fh-empty", text: "没找到。换个说法试试，比如英文 passport、中文 护照。" }));
    }
    $("progress").textContent = "已复制 " + done.size + " / " + total;
  }

  $("q").addEventListener("input", render);
  $("reveal").addEventListener("change", render);
  $("reset").addEventListener("click", function () { done.clear(); saveDone(); render(); });

  fetch("/api/fill-helper")
    .then(function (r) {
      if (!r.ok) return r.json().then(function (b) { throw new Error(b.detail || r.status); }, function () { throw new Error(r.status); });
      return r.json();
    })
    .then(function (body) { data = body; render(); $("q").focus(); })
    .catch(function (e) {
      var b = $("error");
      b.textContent = "读不到基本信息：" + e.message;
      b.hidden = false;
    });
})();
