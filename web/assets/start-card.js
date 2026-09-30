// 办事页最上面的"开始清单"（specs/007-trip-info 第 3 步）：回答问题 → 放进这次行程的材料 → 整理这次行程。
// 有「这次行程」、没办完、没做完也没跳过时代替「下一步」卡片。guides.js 调用：
//   window.StartCard.render(v, {el, upload(path, formData), redraw(view), jump(id), openTrip()})
// 返回 null 表示这次不显示（调用方照常画「下一步」）。
(function () {
  "use strict";

  function skipKey(v) { return "pa-start-skip-" + v.id; }

  function skipped(v) {
    try { return localStorage.getItem(skipKey(v)) === "1"; } catch (e) { return false; }
  }

  function steps(v) {
    var unanswered = v.facts.filter(function (f) { return f.asked && f.value === null; }).length;
    var reqById = {};
    v.requirements.forEach(function (r) { reqById[r.id] = r; });
    var sources = v.trip_sources.map(function (id) { return reqById[id]; }).filter(Boolean);
    var have = function (r) { return r.state === "ready" || r.state === "unconfirmed"; };
    var matsDone = sources.length ? sources.every(have) : v.trip_materials.length > 0;
    return {
      unanswered: unanswered,
      sources: sources,
      have: have,
      done: [unanswered === 0, matsDone, !!(v.trip.purpose && v.trip.arrival_date)],
    };
  }

  // 点了直接选文件，选完就传
  function filePicker(el, label, onFile) {
    var input = el("input", { type: "file", hidden: true, accept: ".pdf,.txt,.md,.docx,.png,.jpg,.jpeg,.webp" });
    var btn = el("button", { type: "button", class: "linkish", text: label, onclick: function () { input.click(); } });
    input.addEventListener("change", function () {
      if (!input.files.length) return;
      btn.disabled = true;
      btn.textContent = "上传中…";
      onFile(input.files[0]).catch(function () { btn.disabled = false; btn.textContent = label; });
    });
    return el("span", null, btn, input);
  }

  function render(v, deps) {
    var el = deps.el;
    if (!v.trip_groups || !v.trip_groups.length || v.completed || skipped(v)) return null;
    var st = steps(v);
    var doneCount = st.done.filter(Boolean).length;
    if (doneCount === 3) return null;

    function row(i, title, body, onTitle) {
      var head = onTitle
        ? el("button", { type: "button", class: "linkish start-title", text: title, onclick: onTitle })
        : el("span", { class: "start-title", text: title });
      return el("li", { class: "start-row" + (st.done[i] ? " done" : "") },
        el("span", { class: "start-mark", text: st.done[i] ? "✓" : String(i + 1) }),
        el("div", { class: "start-main" }, head, body));
    }

    function upload(path, fd) {
      return deps.upload(path, fd).then(deps.redraw);
    }

    var mats = el("div", { class: "start-mats" },
      st.sources.map(function (r) {
        if (st.have(r)) return el("span", { class: "start-mat have", text: r.name + " ✓" });
        return el("span", { class: "start-mat" }, el("span", { text: r.name }), filePicker(el, "上传", function (file) {
          var fd = new FormData();
          fd.set("file", file);
          fd.set("keep", "false");
          return upload("/api/tracks/" + encodeURIComponent(v.id) + "/requirements/" + encodeURIComponent(r.id) + "/upload", fd);
        }));
      }),
      otherUpload(el, v, upload)
    );

    var skip = el("button", { type: "button", class: "linkish muted start-skip", text: "跳过", onclick: function () {
      try { localStorage.setItem(skipKey(v), "1"); } catch (e) { /* 存不了就只是这次不显示 */ }
      deps.redraw(v);
    } });

    return el("section", { class: "next-card start-card" },
      el("div", { class: "start-head" },
        el("div", { class: "label", text: "开始办之前" }),
        el("small", { class: "muted", text: doneCount + " / 3" })),
      el("ol", { class: "start-list" },
        row(0, st.unanswered ? "回答几个问题（还有 " + st.unanswered + " 个）" : "回答几个问题", null,
          st.done[0] ? null : function () { deps.jump("facts"); }),
        row(1, "放进这次行程的材料", mats),
        row(2, "整理这次行程", st.done[2] ? null : el("button", { type: "button", class: "primary start-go", text: "让 Agent 整理", onclick: deps.openTrip }))
      ),
      skip
    );
  }

  // "＋ 其他"：攻略没列的行程材料（邀请函、会议通知……），填个名字再选文件
  function otherUpload(el, v, upload) {
    var name = el("input", { type: "text", maxlength: "30", placeholder: "邀请函、会议通知……", "aria-label": "材料名" });
    var box = el("span", { class: "start-other", hidden: true }, name, filePicker(el, "选文件", function (file) {
      var fd = new FormData();
      fd.set("file", file);
      fd.set("name", name.value.trim() || file.name.replace(/\.[^.]+$/, ""));
      return upload("/api/tracks/" + encodeURIComponent(v.id) + "/trip-files", fd);
    }));
    var toggle = el("button", { type: "button", class: "linkish", text: "＋ 其他", onclick: function () {
      box.hidden = false; toggle.hidden = true; name.focus();
    } });
    return el("span", { class: "start-mat" }, toggle, box);
  }

  window.StartCard = { render: render };
})();
