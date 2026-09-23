/* 「02 我的资料」：维护个人材料库和出行记录（specs/002-guide-to-track/tasks-parallel-1.md 任务 A，
 * 重新排版见 specs/002-guide-to-track/tasks-parallel-2.md 任务 E）。
 *
 * 单页面：一次性加载材料库 + 材料用途 + 词表候选 + 出行记录，全部渲染在 #view 里，
 * 用 state 记住当前标签页 / 筛选条件 / 展开的编辑区，任何操作后整页重画（除了
 * 搜索框输入——那个只局部刷新列表，避免每敲一个字就丢失输入焦点）。
 *
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
  var STATUS_RANK = { "已过期": 0, "即将过期": 1, "待补": 2, "已备齐": 3 };
  var EXAMPLE_PREFIX = "example-";

  var view = document.getElementById("view");
  var errorBox = document.getElementById("error");

  // 页面状态：标签页记在 URL # 里，其余（筛选、搜索词、展开的编辑区）只存在这一次加载里
  var state = {
    tab: "materials", // "materials" | "travel"
    statusFilter: null, // 点概览格子时设置，null 表示不筛选
    categoryFilter: "all",
    search: "",
    newFormOpen: false,
    materialsExpanded: null, // { id, mode: "edit" | "append" } | null，同一时间最多一个
    travelExpanded: null, // { mode: "add" } | { mode: "edit", index } | null
  };

  // 加载到的数据（reload() 整体重新拉取；筛选/展开只是本地重画，不重新请求）
  var data = { materials: null, usage: null, types: null, profile: null };

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
    // 子节点可以是字符串、元素、空值或（任意层嵌套的）数组：数组逐层展开，空值跳过。
    // 原生 append 会把数组 / null 变成 "[object ...]" / "null" 文字，所以一律经过这里。
    (function add(child) {
      if (child === null || child === undefined || child === false) return;
      if (Array.isArray(child)) { child.forEach(add); return; }
      node.append(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
    })(Array.prototype.slice.call(arguments, 2));
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

  // ---------- 数据加载 ----------

  function load() {
    showError("");
    return Promise.all([
      request("GET", "/api/materials"),
      request("GET", "/api/materials/usage"),
      request("GET", "/api/material-types"),
      request("GET", "/api/personal-profile"),
      request("GET", "/api/tracks"),
    ])
      .then(function (results) {
        // 长期资料 vs 本次专用：页面上的统计、筛选、"需要处理"只看长期资料；
        // 只属于某件办事的一次性材料放进下面单独的折叠分组
        data.materials = results[0].filter(function (m) { return !m.for_track; });
        data.oneOff = results[0].filter(function (m) { return !!m.for_track; });
        data.trackTitles = {};
        results[4].forEach(function (t) { data.trackTitles[t.id] = t.title; });
        data.usage = results[1];
        data.types = results[2];
        data.profile = results[3];
        render();
      })
      .catch(function (e) {
        setView();
        showError(e.message);
      });
  }

  // 目前数据量不大，任何写操作之后就整体重新拉取一遍，逻辑简单、不用维护本地增量更新
  function reload() {
    return load();
  }

  // ---------- 标签页路由：#materials / #travel，刷新后保持 ----------

  function syncTabFromHash() {
    state.tab = location.hash === "#travel" ? "travel" : "materials";
  }

  function switchTab(tab) {
    if (state.tab === tab) { render(); return; }
    location.hash = "#" + tab; // 触发 hashchange -> syncTabFromHash() + render()
  }

  // ---------- 材料库：筛选 / 排序 ----------

  function usageTitlesFor(m) {
    var usages = data.usage[m.id] || [];
    var seenTrack = {};
    return usages
      .filter(function (u) {
        if (seenTrack[u.track_id]) return false;
        seenTrack[u.track_id] = true;
        return true;
      })
      .map(function (u) { return u.track_title; });
  }

  function sortMaterials(list) {
    return list.slice().sort(function (a, b) {
      var ra = STATUS_RANK[a.status], rb = STATUS_RANK[b.status];
      if (ra !== rb) return ra - rb;
      var da = a.obtained_date || "";
      var db = b.obtained_date || "";
      if (da === db) return 0;
      return da < db ? 1 : -1; // 取得日期倒序
    });
  }

  function filteredMaterials() {
    var list = data.materials;
    if (state.categoryFilter !== "all") list = list.filter(function (m) { return m.category === state.categoryFilter; });
    if (state.statusFilter) list = list.filter(function (m) { return m.status === state.statusFilter; });
    var q = state.search.trim().toLowerCase();
    if (q) {
      list = list.filter(function (m) {
        return (m.type || "").toLowerCase().indexOf(q) !== -1 || (m.sublabel || "").toLowerCase().indexOf(q) !== -1;
      });
    }
    return sortMaterials(list);
  }

  function statusChip(status) {
    return el("span", { class: "state mstate-" + (STATUS_CLASS[status] || "ok"), text: status });
  }

  // ---------- 标题区 ----------

  function headingSection() {
    return el(
      "div",
      { class: "heading" },
      el("div", null, el("h1", { text: "我的资料" }), el("p", { class: "muted", text: "材料库和出行记录，只保存在这台电脑上。" })),
      el("button", {
        class: "primary",
        type: "button",
        text: "＋ 新增材料",
        onclick: function () { state.newFormOpen = !state.newFormOpen; render(); },
      })
    );
  }

  // ---------- 概览数字 ----------

  function overviewPanel() {
    var counts = { total: data.materials.length, "已过期": 0, "即将过期": 0, "待补": 0 };
    data.materials.forEach(function (m) { if (counts[m.status] !== undefined) counts[m.status]++; });

    function cell(key, label, count, dangerWhenNonZero) {
      var zero = count === 0;
      var pressed = key !== null && state.statusFilter === key;
      return el(
        "button",
        {
          type: "button",
          class: "stat" + (zero ? " zero" : "") + (dangerWhenNonZero && !zero ? " danger" : ""),
          "aria-pressed": pressed ? "true" : "false",
          onclick: function () {
            state.statusFilter = key === null ? null : (state.statusFilter === key ? null : key);
            switchTab("materials");
          },
        },
        el("b", { text: String(count) }),
        el("span", { text: label })
      );
    }

    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "概览" })),
      el(
        "div",
        { class: "stats" },
        cell(null, "材料总数", counts.total, false),
        cell("已过期", "已过期", counts["已过期"], true),
        cell("即将过期", "即将过期", counts["即将过期"], false),
        cell("待补", "待补", counts["待补"], false)
      )
    );
  }

  // ---------- 需要处理 ----------

  function attentionReason(m) {
    if (m.status === "待补") return "还没填取得日期";
    if (m.status === "已过期") return "已过期 " + (-m.days_until_expiry) + " 天";
    if (m.status === "即将过期") return m.days_until_expiry + " 天后过期";
    return "";
  }

  function attentionPanel() {
    var items = sortMaterials(
      // 示例记录只是演示格式，不提醒用户去处理
      data.materials.filter(function (m) {
        return m.id.indexOf("example-") !== 0 && (m.status === "已过期" || m.status === "即将过期" || m.status === "待补");
      })
    );
    if (!items.length) return null;
    return el(
      "section",
      { class: "panel attention" },
      el("div", { class: "panel-head" }, el("h2", null, "需要处理", el("span", { class: "count", text: items.length }))),
      el(
        "div",
        { class: "attention-list" },
        items.map(function (m) {
          return el(
            "div",
            { class: "attention-row" },
            statusChip(m.status),
            el("span", { class: "attention-name", text: m.type + (m.sublabel ? "（" + m.sublabel + "）" : "") }),
            el("span", { class: "attention-reason", text: attentionReason(m) }),
            el("button", {
              type: "button",
              text: "更新",
              onclick: function () {
                state.categoryFilter = "all";
                state.search = "";
                state.statusFilter = null;
                state.materialsExpanded = { id: m.id, mode: "edit" };
                switchTab("materials");
              },
            })
          );
        })
      )
    );
  }

  // ---------- 新增材料（默认收起，点标题区按钮展开） ----------

  function newMaterialPanel() {
    var categorySelect = el(
      "select",
      { name: "category", required: true },
      CATEGORY_ORDER.map(function (c) { return el("option", { value: c, text: CATEGORY_LABEL[c] }); })
    );
    var typeInput = el("input", {
      type: "text", name: "type", list: "material-type-options", required: true,
      placeholder: "例如：护照个人信息页",
    });
    var typeList = el("datalist", { id: "material-type-options" }, data.types.map(function (t) { return el("option", { value: t.name }); }));
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
        .then(function () { state.newFormOpen = false; return reload(); })
        .catch(function (e) { showError(e.message); })
        .then(function () { btn.disabled = false; });
    });

    return el(
      "section",
      { class: "panel", hidden: !state.newFormOpen },
      el("div", { class: "panel-head" }, el("h2", { text: "新增材料" })),
      form
    );
  }

  // ---------- 标签页导航 ----------

  function tabsNav() {
    return el(
      "nav",
      { class: "tabs", "aria-label": "内容切换" },
      el("a", {
        href: "#materials",
        class: "tab" + (state.tab === "materials" ? " active" : ""),
        "aria-current": state.tab === "materials" ? "page" : "false",
        text: "材料库（" + data.materials.length + "）",
      }),
      el("a", {
        href: "#travel",
        class: "tab" + (state.tab === "travel" ? " active" : ""),
        "aria-current": state.tab === "travel" ? "page" : "false",
        text: "出行记录（" + (data.profile.travel_history || []).length + "）",
      })
    );
  }

  // ---------- 材料库标签页 ----------

  function materialsHeaderRow() {
    return el(
      "div",
      { class: "mrow mrow-head", "aria-hidden": "true" },
      el("div", { class: "mrow-line1" }, el("span", { text: "状态 / 材料" })),
      el(
        "div",
        { class: "mrow-line2" },
        el("span", { class: "col-date", text: "取得日期" }),
        el("span", { class: "col-file", text: "文件" }),
        el("span", { class: "col-usage", text: "用在" }),
        el("span", { class: "col-actions", text: "操作" })
      )
    );
  }

  function materialRow(m) {
    var isExample = m.id.indexOf(EXAMPLE_PREFIX) === 0;
    var usageTitles = usageTitlesFor(m);
    var isEditing = state.materialsExpanded && state.materialsExpanded.id === m.id && state.materialsExpanded.mode === "edit";
    var isAppending = state.materialsExpanded && state.materialsExpanded.id === m.id && state.materialsExpanded.mode === "append";
    var isPdf = m.file_ref && m.file_ref.toLowerCase().endsWith(".pdf");

    var actions = [
      el("button", {
        type: "button",
        text: "编辑",
        "aria-pressed": isEditing ? "true" : "false",
        onclick: function () {
          state.materialsExpanded = isEditing ? null : { id: m.id, mode: "edit" };
          render();
        },
      }),
    ];
    if (isPdf) {
      actions.push(el("button", {
        type: "button",
        text: "追加新页",
        "aria-pressed": isAppending ? "true" : "false",
        onclick: function () {
          state.materialsExpanded = isAppending ? null : { id: m.id, mode: "append" };
          render();
        },
      }));
    }

    var line1 = el(
      "div",
      { class: "mrow-line1" },
      statusChip(m.status),
      el("span", { class: "mat-name", text: m.type }),
      m.sublabel ? el("span", { class: "mat-sub", text: m.sublabel }) : null,
      isExample ? el("span", { class: "badge", text: "示例" }) : null
    );
    var line2 = el(
      "div",
      { class: "mrow-line2" },
      el("span", { class: "col-date", text: m.obtained_date || "—" }),
      el("span", { class: "sep", text: "·" }),
      el("span", { class: "col-file", text: m.file_ref ? "✓" : "—" }),
      el("span", { class: "sep", text: "·" }),
      el("span", { class: "col-usage", text: usageTitles.length ? usageTitles.join("、") : "—" }),
      el("span", { class: "col-actions" }, actions)
    );

    return el("div", { class: "mrow", id: "mat-row-" + m.id }, line1, line2);
  }

  function materialEditRow(m) {
    var typeInput = el("input", { type: "text", name: "type", value: m.type, required: true });
    var sublabelInput = el("input", { type: "text", name: "sublabel", value: m.sublabel || "" });
    var dateInput = el("input", { type: "date", name: "obtained_date", value: m.obtained_date || "" });
    var validityInput = el("input", {
      type: "number", name: "validity_days", min: "0",
      value: m.validity_days === null || m.validity_days === undefined ? "" : m.validity_days,
    });
    var saveBtn = el("button", { class: "primary", type: "submit", text: "保存" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { state.materialsExpanded = null; render(); } });
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
        .then(function () { state.materialsExpanded = null; return reload(); })
        .catch(function (e) { saveBtn.disabled = false; showError(e.message); });
    });
    return el("div", { class: "edit-row" }, form);
  }

  function materialAppendRow(m) {
    var fileInput = el("input", { type: "file", name: "file", required: true, accept: ".pdf,.jpg,.jpeg,.png" });
    var btn = el("button", { class: "primary", type: "submit", text: "追加" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { state.materialsExpanded = null; render(); } });
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
        .then(function () { state.materialsExpanded = null; return reload(); })
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return el("div", { class: "edit-row" }, form);
  }

  function materialsTable(list) {
    var byId = {};
    list.forEach(function (m) { byId[m.id] = m; });
    var rows = [materialsHeaderRow()];
    list.forEach(function (m) {
      rows.push(materialRow(m));
      if (state.materialsExpanded && state.materialsExpanded.id === m.id) {
        rows.push(state.materialsExpanded.mode === "append" ? materialAppendRow(m) : materialEditRow(m));
      }
    });
    return el("div", { class: "mtable" }, rows);
  }

  function materialsTabSection() {
    var counts = { all: data.materials.length };
    CATEGORY_ORDER.forEach(function (c) { counts[c] = 0; });
    data.materials.forEach(function (m) { counts[m.category] = (counts[m.category] || 0) + 1; });

    var chips = el(
      "nav",
      { class: "chips", "aria-label": "按分类筛选" },
      el(
        "button",
        { type: "button", class: "chip", "aria-current": state.categoryFilter === "all" ? "true" : "false", onclick: function () { state.categoryFilter = "all"; render(); } },
        "全部",
        el("span", { class: "n", text: counts.all })
      ),
      CATEGORY_ORDER.map(function (c) {
        return el(
          "button",
          { type: "button", class: "chip", "aria-current": state.categoryFilter === c ? "true" : "false", onclick: function () { state.categoryFilter = c; render(); } },
          CATEGORY_LABEL[c],
          el("span", { class: "n", text: counts[c] })
        );
      })
    );

    var searchInput = el("input", {
      type: "search",
      placeholder: "按类型 / 细分标签搜索…",
      value: state.search,
    });
    var listContainer = el("div", { class: "table-wrap" });
    var countLabel = el("small");

    function refreshList() {
      var list = filteredMaterials();
      countLabel.textContent = list.length + " / " + data.materials.length;
      listContainer.replaceChildren(list.length ? materialsTable(list) : el("p", { class: "empty", text: "没有符合条件的材料。" }));
    }
    searchInput.addEventListener("input", function (ev) {
      state.search = ev.target.value;
      refreshList();
    });
    refreshList();

    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "材料库" }), countLabel),
      el("div", { class: "toolbar" }, chips, el("label", { class: "search" }, "搜索", searchInput)),
      listContainer,
      oneOffSection()
    );
  }

  // 本次专用的材料：按所属办事分组，默认折叠；需要的话可以一键转为长期资料
  function oneOffSection() {
    if (!data.oneOff || !data.oneOff.length) return null;
    var groups = {};
    data.oneOff.forEach(function (m) { (groups[m.for_track] = groups[m.for_track] || []).push(m); });
    return el(
      "details",
      { class: "one-off" },
      el("summary", { text: "办事专用的材料（" + data.oneOff.length + "）——只属于某一件办事，不会被别的办事用到" }),
      Object.keys(groups).map(function (tid) {
        return el(
          "div",
          { class: "one-off-group" },
          el("div", { class: "one-off-title", text: data.trackTitles[tid] || tid + "（这件办事已不存在）" }),
          groups[tid].map(function (m) {
            return el(
              "div",
              { class: "one-off-row" },
              el("span", { text: m.type + (m.sublabel ? "（" + m.sublabel + "）" : "") }),
              el("small", { class: "muted", text: (m.obtained_date || "未填日期") + " · " + (m.file_ref ? "有文件" : "没有文件") }),
              el("button", {
                type: "button",
                text: "转为长期资料",
                title: "以后别的办事也能用到这份材料",
                onclick: function () {
                  showError("");
                  request("PATCH", "/api/materials/" + encodeURIComponent(m.id), { for_track: null })
                    .then(reload)
                    .catch(function (e) { showError(e.message); });
                },
              })
            );
          })
        );
      })
    );
  }

  // ---------- 出行记录标签页 ----------

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

  function travelAddForm() {
    var f = travelFields(null);
    var btn = el("button", { class: "primary", type: "submit", text: "新增出行记录" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { state.travelExpanded = null; render(); } });
    var form = el(
      "form",
      { class: "travel-form" },
      el("label", null, "国家（可选）", f.country),
      el("label", null, "入境日期", f.entryDate),
      el("label", null, "离境日期（可选，还没回来就留空）", f.exitDate),
      el("label", null, "目的（可选）", f.purpose),
      el("div", { class: "form-actions" }, btn, cancelBtn)
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      btn.disabled = true;
      showError("");
      request("POST", "/api/personal-profile/travel-history", travelPayload(f))
        .then(function () { state.travelExpanded = null; return reload(); })
        .catch(function (e) { showError(e.message); })
        .then(function () { btn.disabled = false; });
    });
    return form;
  }

  function travelEditForm(entry, index) {
    var f = travelFields(entry);
    var btn = el("button", { class: "primary", type: "submit", text: "保存" });
    var cancelBtn = el("button", { type: "button", text: "取消", onclick: function () { state.travelExpanded = null; render(); } });
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
        .then(function () { state.travelExpanded = null; return reload(); })
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return form;
  }

  function travelHeaderRow() {
    return el(
      "div",
      { class: "mrow mrow-head", "aria-hidden": "true" },
      el("div", { class: "mrow-line1" }, el("span", { text: "国家" })),
      el(
        "div",
        { class: "mrow-line2" },
        el("span", { class: "col-date", text: "入境" }),
        el("span", { class: "col-file", text: "离境" }),
        el("span", { class: "col-usage", text: "目的" }),
        el("span", { class: "col-actions", text: "操作" })
      )
    );
  }

  function travelRow(entry, index) {
    var isEditing = state.travelExpanded && state.travelExpanded.mode === "edit" && state.travelExpanded.index === index;
    var warn = !entry.country;
    var editBtn = el("button", {
      type: "button",
      text: "编辑",
      "aria-pressed": isEditing ? "true" : "false",
      onclick: function () {
        state.travelExpanded = isEditing ? null : { mode: "edit", index: index };
        render();
      },
    });
    var line1 = el(
      "div",
      { class: "mrow-line1" },
      el("span", { class: "mat-name" + (warn ? " warn" : ""), text: entry.country || "国家待补" })
    );
    var line2 = el(
      "div",
      { class: "mrow-line2" },
      el("span", { class: "col-date", text: entry.entry_date }),
      el("span", { class: "sep", text: "·" }),
      el("span", { class: "col-file", text: entry.exit_date || "至今" }),
      el("span", { class: "sep", text: "·" }),
      el("span", { class: "col-usage", text: entry.purpose || "—" }),
      el("span", { class: "col-actions" }, editBtn)
    );
    return el("div", { class: "mrow" + (warn ? " travel-warn" : "") }, line1, line2);
  }

  function travelTabSection() {
    var entries = (data.profile.travel_history || []).map(function (entry, index) { return { entry: entry, index: index }; });
    var sorted = entries.slice().sort(function (a, b) { return b.entry.entry_date.localeCompare(a.entry.entry_date); });

    var isAdding = state.travelExpanded && state.travelExpanded.mode === "add";
    var addBtn = el("button", {
      type: "button",
      class: "primary",
      text: "＋ 新增出行记录",
      onclick: function () {
        state.travelExpanded = isAdding ? null : { mode: "add" };
        render();
      },
    });

    var rows = [travelHeaderRow()];
    if (isAdding) rows.push(el("div", { class: "edit-row" }, travelAddForm()));
    sorted.forEach(function (item) {
      rows.push(travelRow(item.entry, item.index));
      if (state.travelExpanded && state.travelExpanded.mode === "edit" && state.travelExpanded.index === item.index) {
        rows.push(el("div", { class: "edit-row" }, travelEditForm(item.entry, item.index)));
      }
    });

    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", null, "出行记录", el("span", { class: "count", text: entries.length })), addBtn),
      entries.length || isAdding ? el("div", { class: "mtable" }, rows) : el("p", { class: "empty", text: "还没有出行记录。" })
    );
  }

  // ---------- 整页 ----------

  function render() {
    if (!data.materials) return;
    setView(
      headingSection(),
      overviewPanel(),
      attentionPanel(),
      newMaterialPanel(),
      tabsNav(),
      state.tab === "travel" ? travelTabSection() : materialsTabSection()
    );
  }

  window.addEventListener("hashchange", function () {
    syncTabFromHash();
    render();
  });

  document.getElementById("today").textContent = "今天 " + todayIso();
  syncTabFromHash();
  load();
})();
