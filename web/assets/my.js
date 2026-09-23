/* 「02 我的资料」：维护个人材料库和出行记录（specs/002-guide-to-track/tasks-parallel-1.md 任务 A）。
 *
 * 单页面、不分路由：一次性加载材料库 + 材料用途 + 词表候选 + 出行记录，全部渲染在 #view 里。
 * 动态文本一律用 textContent / createElement 写入，不用 innerHTML（见 el() 的写法，抄自 guides.js）。
 */
(function () {
  "use strict";

  var CATEGORY_ORDER = ["passport_scan", "financial_snapshot", "employment_doc", "id_photo", "other"];
  var CATEGORY_LABEL = {
    passport_scan: "证件",
    financial_snapshot: "财务",
    employment_doc: "工作",
    id_photo: "证件照",
    other: "其他",
  };
  // MaterialStatus 的四个取值（src/core/models.py），映射到这个页面自己的着色类（web/assets/my.css）
  var STATUS_CLASS = { "已备齐": "ok", "待补": "missing", "即将过期": "soon", "已过期": "expired" };
  var EXAMPLE_PREFIX = "example-";

  var view = document.getElementById("view");
  var errorBox = document.getElementById("error");

  // ---------- 小工具（跟 guides.js 是同一套写法，两个页面各自独立加载，不共享脚本） ----------

  function el(tag, props) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v === undefined || v === null || v === false) return;
        if (k === "text") node.textContent = String(v);
        else if (k === "class") node.className = v;
        else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? "" : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) child.forEach(function (c) { if (c) node.append(c); });
      else node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  // 原生 replaceChildren / append 会把 null 当成文字 "null" 显示出来，统一经过这里过滤掉空值
  function setView() {
    // 和 el() 的子节点规则一致：数组展开一层，空值跳过（原生方法会把数组/null 变成字符串显示出来）
    var nodes = [];
    Array.prototype.slice.call(arguments).forEach(function (n) {
      (Array.isArray(n) ? n : [n]).forEach(function (c) {
        if (c !== null && c !== undefined && c !== false) nodes.push(c);
      });
    });
    view.replaceChildren.apply(view, nodes);
  }

  function showError(msg) {
    errorBox.hidden = !msg;
    errorBox.textContent = msg || "";
  }

  function request(method, path, body) {
    var opts = { method: method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          throw new Error(typeof detail === "string" ? detail : "请求失败（HTTP " + res.status + "）");
        }
        return data;
      });
    });
  }

  function formRequest(method, path, formData) {
    return fetch(path, { method: method, body: formData, headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          throw new Error(typeof detail === "string" ? detail : "请求失败（HTTP " + res.status + "）");
        }
        return data;
      });
    });
  }

  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  // ---------- 材料库 ----------

  function statusChip(status) {
    return el("span", { class: "state mstate-" + (STATUS_CLASS[status] || "ok"), text: status });
  }

  function materialCard(m, usageByRecord, reload) {
    var isExample = m.id.indexOf(EXAMPLE_PREFIX) === 0;

    var usages = usageByRecord[m.id] || [];
    var seenTrack = {};
    var usageTitles = usages
      .filter(function (u) {
        if (seenTrack[u.track_id]) return false;
        seenTrack[u.track_id] = true;
        return true;
      })
      .map(function (u) { return u.track_title; });

    var metaBits = [
      el("span", { text: m.obtained_date ? "取得于 " + m.obtained_date : "还没填取得日期" }),
      el("span", { text: m.file_ref ? "已有文件" : "没有文件" }),
    ];
    if (m.days_until_expiry !== null && m.days_until_expiry !== undefined) {
      metaBits.push(el("span", {
        text: m.days_until_expiry >= 0 ? "还有 " + m.days_until_expiry + " 天过期" : "已过期 " + (-m.days_until_expiry) + " 天",
      }));
    }

    var card = el(
      "div",
      { class: "mat" },
      el(
        "div",
        { class: "mat-top" },
        statusChip(m.status),
        el("span", { class: "mat-name", text: m.type + (m.sublabel ? "（" + m.sublabel + "）" : "") }),
        isExample ? el("span", { class: "badge", text: "示例" }) : null
      ),
      el("div", { class: "step-meta" }, metaBits),
      usageTitles.length ? el("div", { class: "mat-note", text: "用在：" + usageTitles.join("、") }) : null,
      el("div", { class: "mat-actions" })
    );

    var actions = card.querySelector(".mat-actions");

    var editBtn = el("button", {
      type: "button",
      text: "编辑",
      onclick: function () {
        var existing = card.querySelector("form");
        if (existing) { existing.remove(); return; }
        card.append(editForm(m, reload));
      },
    });
    actions.append(editBtn);

    if (m.file_ref && m.file_ref.toLowerCase().endsWith(".pdf")) {
      actions.append(el("button", {
        type: "button",
        text: "追加新页",
        onclick: function () {
          var existing = card.querySelector("form");
          if (existing) { existing.remove(); return; }
          card.append(appendPageForm(m, reload));
        },
      }));
    }

    return card;
  }

  function editForm(m, reload) {
    var typeInput = el("input", { type: "text", name: "type", value: m.type, required: true });
    var sublabelInput = el("input", { type: "text", name: "sublabel", value: m.sublabel || "" });
    var dateInput = el("input", { type: "date", name: "obtained_date", value: m.obtained_date || "" });
    var validityInput = el("input", {
      type: "number", name: "validity_days", min: "0",
      value: m.validity_days === null || m.validity_days === undefined ? "" : m.validity_days,
    });
    var saveBtn = el("button", { type: "submit", text: "保存" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { form.remove(); } });
    var form = el(
      "form",
      { class: "edit-form" },
      el("label", null, "类型名", typeInput),
      el("label", null, "细分标签", sublabelInput),
      el("label", null, "取得日期", dateInput),
      el("label", null, "有效期天数", validityInput),
      el("div", { class: "form-actions" }, saveBtn, cancelBtn)
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var newType = typeInput.value.trim();
      if (!newType) { showError("类型名不能为空"); return; }
      saveBtn.disabled = true;
      showError("");
      request("PATCH", "/api/materials/" + encodeURIComponent(m.id), {
        type: newType,
        sublabel: sublabelInput.value.trim() ? sublabelInput.value.trim() : null,
        obtained_date: dateInput.value || null,
        validity_days: validityInput.value === "" ? null : Number(validityInput.value),
      })
        .then(reload)
        .catch(function (e) { saveBtn.disabled = false; showError(e.message); });
    });
    return form;
  }

  function appendPageForm(m, reload) {
    var fileInput = el("input", { type: "file", name: "file", required: true, accept: ".pdf,.jpg,.jpeg,.png" });
    var btn = el("button", { type: "submit", text: "追加" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { form.remove(); } });
    var form = el(
      "form",
      { class: "append-form" },
      el("label", null, "新的一页（图片或 PDF）", fileInput),
      el("div", { class: "form-actions" }, btn, cancelBtn)
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (!fileInput.files.length) return;
      var fd = new FormData();
      fd.set("file", fileInput.files[0]);
      btn.disabled = true;
      showError("");
      formRequest("POST", "/api/materials/" + encodeURIComponent(m.id) + "/append-page", fd)
        .then(reload)
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return form;
  }

  function groupMaterials(materials) {
    var byCategory = {};
    CATEGORY_ORDER.forEach(function (c) { byCategory[c] = []; });
    materials.forEach(function (m) {
      if (!byCategory[m.category]) byCategory[m.category] = [];
      byCategory[m.category].push(m);
    });
    return byCategory;
  }

  function materialsSections(materials, usage, reload) {
    var byCategory = groupMaterials(materials);
    return CATEGORY_ORDER.map(function (cat) {
      var list = byCategory[cat] || [];
      return el(
        "section",
        { class: "panel" },
        el("div", { class: "panel-head" }, el("h2", null, CATEGORY_LABEL[cat], el("span", { class: "count", text: list.length }))),
        list.length
          ? el("div", { class: "mat-list" }, list.map(function (m) { return materialCard(m, usage, reload); }))
          : el("p", { class: "empty", text: "还没有这一类材料。" })
      );
    });
  }

  function newMaterialForm(types, reload) {
    var categorySelect = el(
      "select",
      { name: "category", required: true },
      CATEGORY_ORDER.map(function (c) { return el("option", { value: c, text: CATEGORY_LABEL[c] }); })
    );
    var typeInput = el("input", {
      type: "text", name: "type", list: "material-type-options", required: true,
      placeholder: "例如：护照个人信息页",
    });
    var typeList = el("datalist", { id: "material-type-options" }, types.map(function (t) { return el("option", { value: t.name }); }));
    var dateInput = el("input", { type: "date", name: "obtained_date", required: true });
    var sublabelInput = el("input", { type: "text", name: "sublabel" });
    var fileInput = el("input", { type: "file", name: "file" });
    var btn = el("button", { class: "primary", type: "submit", text: "新增材料" });

    var form = el(
      "form",
      { class: "start" },
      el("label", null, "类别", categorySelect),
      el("label", null, "类型名", typeInput),
      typeList,
      el("label", null, "取得日期", dateInput),
      el("label", null, "细分标签（可选）", sublabelInput),
      el("label", null, "文件（可选）", fileInput),
      btn
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      btn.disabled = true;
      showError("");
      var fd = new FormData();
      fd.set("category", categorySelect.value);
      fd.set("type", typeInput.value.trim());
      fd.set("obtained_date", dateInput.value);
      if (sublabelInput.value.trim()) fd.set("sublabel", sublabelInput.value.trim());
      if (fileInput.files.length) fd.set("file", fileInput.files[0]);
      formRequest("POST", "/api/materials", fd)
        .then(function () { form.reset(); return reload(); })
        .catch(function (e) { showError(e.message); })
        .then(function () { btn.disabled = false; });
    });
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "新增材料" })),
      form
    );
  }

  function summaryLine(materials) {
    var expired = materials.filter(function (m) { return m.status === "已过期"; }).length;
    var soon = materials.filter(function (m) { return m.status === "即将过期"; }).length;
    return el(
      "p",
      { class: "notice" + (expired ? " warn" : "") },
      "共 " + materials.length + " 份材料，其中过期 " + expired + " 份、即将过期 " + soon + " 份。"
    );
  }

  // ---------- 出行记录 ----------

  function travelFields(entry) {
    return {
      country: el("input", { type: "text", name: "country", value: (entry && entry.country) || "" }),
      entryDate: el("input", { type: "date", name: "entry_date", required: true, value: (entry && entry.entry_date) || "" }),
      exitDate: el("input", { type: "date", name: "exit_date", value: (entry && entry.exit_date) || "" }),
      purpose: el("input", { type: "text", name: "purpose", value: (entry && entry.purpose) || "" }),
    };
  }

  function travelPayload(f) {
    return {
      country: f.country.value.trim() ? f.country.value.trim() : null,
      entry_date: f.entryDate.value,
      exit_date: f.exitDate.value || null,
      purpose: f.purpose.value.trim() ? f.purpose.value.trim() : null,
    };
  }

  function travelAddForm(reload) {
    var f = travelFields(null);
    var btn = el("button", { class: "primary", type: "submit", text: "新增出行记录" });
    var form = el(
      "form",
      { class: "travel-form" },
      el("label", null, "国家（可选）", f.country),
      el("label", null, "入境日期", f.entryDate),
      el("label", null, "离境日期（可选，还没回来就留空）", f.exitDate),
      el("label", null, "目的（可选）", f.purpose),
      btn
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      btn.disabled = true;
      showError("");
      request("POST", "/api/personal-profile/travel-history", travelPayload(f))
        .then(function () { form.reset(); return reload(); })
        .catch(function (e) { showError(e.message); })
        .then(function () { btn.disabled = false; });
    });
    return form;
  }

  function travelEditForm(entry, index, reload, onDone) {
    var f = travelFields(entry);
    var btn = el("button", { type: "submit", text: "保存" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: onDone });
    var form = el(
      "form",
      { class: "travel-form" },
      el("label", null, "国家", f.country),
      el("label", null, "入境日期", f.entryDate),
      el("label", null, "离境日期", f.exitDate),
      el("label", null, "目的", f.purpose),
      el("div", { class: "form-actions" }, btn, cancelBtn)
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      btn.disabled = true;
      showError("");
      request("PUT", "/api/personal-profile/travel-history/" + index, travelPayload(f))
        .then(reload)
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return form;
  }

  function travelSection(profile, reload) {
    var entries = (profile.travel_history || []).map(function (entry, index) { return { entry: entry, index: index }; });
    var sorted = entries.slice().sort(function (a, b) { return a.entry.entry_date.localeCompare(b.entry.entry_date); });

    var rows = [];
    sorted.forEach(function (item) {
      var e = item.entry;
      var editBtn = el("button", { type: "button", text: "编辑" });
      var row = el(
        "tr",
        null,
        el("td", { text: e.country || "（待补充）" }),
        el("td", { text: e.entry_date }),
        el("td", { text: e.exit_date || "至今" }),
        el("td", { text: e.purpose || "" }),
        el("td", null, editBtn)
      );
      rows.push(row);
      editBtn.addEventListener("click", function () {
        var next = row.nextElementSibling;
        if (next && next.classList.contains("edit-row")) { next.remove(); return; }
        var editRow = el(
          "tr",
          { class: "edit-row" },
          el("td", { colspan: "5" }, travelEditForm(e, item.index, reload, function () { editRow.remove(); }))
        );
        row.after(editRow);
      });
    });

    var table = el(
      "table",
      { class: "travel-table" },
      el("thead", null, el("tr", null, el("th", { text: "国家" }), el("th", { text: "入境" }), el("th", { text: "离境" }), el("th", { text: "目的" }), el("th"))),
      el("tbody", null, rows)
    );

    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", null, "出行记录", el("span", { class: "count", text: entries.length }))),
      entries.length ? table : el("p", { class: "empty", text: "还没有出行记录。" }),
      el("div", { class: "travel-add" }, travelAddForm(reload))
    );
  }

  // ---------- 整页 ----------

  function render(materials, usage, types, profile) {
    setView(
      el(
        "div",
        { class: "heading" },
        el("div", null, el("h1", { text: "我的资料" }), el("p", { class: "muted", text: "材料库和出行记录，只保存在这台电脑上。" }))
      ),
      summaryLine(materials),
      materialsSections(materials, usage, load),
      newMaterialForm(types, load),
      travelSection(profile, load)
    );
  }

  function load() {
    showError("");
    return Promise.all([
      request("GET", "/api/materials"),
      request("GET", "/api/materials/usage"),
      request("GET", "/api/material-types"),
      request("GET", "/api/personal-profile"),
    ])
      .then(function (results) { render(results[0], results[1], results[2], results[3]); })
      .catch(function (e) {
        setView();
        showError(e.message);
      });
  }

  document.getElementById("today").textContent = "今天 " + todayIso();
  load();
})();
