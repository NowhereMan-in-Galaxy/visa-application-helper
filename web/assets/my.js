/* 「02 我的资料」：维护个人材料库、出行记录和基本信息（基本信息见 specs/003-personal-profile；specs/002-guide-to-track/tasks-parallel-1.md 任务 A，
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
    tab: "materials", // "materials" | "travel" | "profile"
    categoryFilter: "all",
    search: "",
    newFormOpen: false,
    materialsExpanded: null, // { id, mode: "edit" | "append" } | null，同一时间最多一个
    travelExpanded: null, // { mode: "add" } | { mode: "edit", index } | null
    // 基本信息：每个分组一份编辑中的草稿（保存成功前只在内存里），切换标签页不丢
    profileDrafts: {}, // { group: object }
    profileStatus: {}, // { group: { ok: bool, text } } 保存按钮旁的提示
    profileOpen: null, // { group: bool } 哪些分组面板展开着；null = 还没初始化（默认展开第一个）
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
      request("GET", "/api/personal-profile/fields"),
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
        data.profileFields = results[5];
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

  // ---------- 标签页路由：#materials / #travel / #profile，刷新后保持 ----------

  function syncTabFromHash() {
    state.tab = location.hash === "#travel" ? "travel" : location.hash === "#profile" ? "profile" : "materials";
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
      el("div", null, el("h1", { text: "我的资料" })),
      el("button", {
        class: "primary",
        type: "button",
        text: "＋ 新增材料",
        onclick: function () { state.newFormOpen = !state.newFormOpen; render(); },
      })
    );
  }

  // ---------- 概览：一行字 ----------
  // （2026-09-28 简化：原来是四个数字格子，全是 0 的时候只是噪音；有要处理的材料时，下面的「需要处理」会列出来）

  function overviewLine() {
    var total = data.materials.length;
    var issues = data.materials.filter(function (m) { return m.status === "已过期" || m.status === "即将过期" || m.status === "待补"; }).length;
    return el("p", { class: "overview-line" + (issues ? " has-issues" : "") },
      issues ? total + " 份材料，其中 " + issues + " 份需要处理（见下方）。" : total + " 份材料，都在有效期内。");
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
      }),
      el("a", {
        href: "#profile",
        class: "tab" + (state.tab === "profile" ? " active" : ""),
        "aria-current": state.tab === "profile" ? "page" : "false",
        text: "基本信息",
      })
    );
  }

  // ---------- 材料库标签页 ----------

  function materialsHeaderRow() {
    return el(
      "div",
      { class: "mrow mrow-head", "aria-hidden": "true" },
      el("div", { class: "mrow-line1" }, el("span", { text: "材料" })),
      el("div", { class: "mrow-line2" }, el("span", { class: "col-date", text: "取得日期" }))
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
      m.status === "已备齐" ? null : statusChip(m.status),  // 备齐了是常态，不用每行都写
      el("span", { class: "mat-name", text: m.type }),
      m.sublabel ? el("span", { class: "mat-sub", text: m.sublabel }) : null,
      isExample ? el("span", { class: "badge", text: "示例" }) : null
    );
    var line2 = el(
      "div",
      { class: "mrow-line2" },
      el("span", { class: "col-date", text: m.obtained_date || "—" }),
      // 只写例外情况：没有文件、被哪件办事用到；平常的"有文件""没用到"不写
      m.file_ref ? null : el("span", { class: "col-file warn", text: "还没有文件" }),
      usageTitles.length ? el("span", { class: "col-usage", text: "用在：" + usageTitles.join("、") }) : null,
      el("span", { class: "col-actions" + (isEditing || isAppending ? " active" : "") }, actions)
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

  // ---------- 基本信息标签页（specs/003-personal-profile） ----------
  //
  // 表单完全按 GET /api/personal-profile/fields 的字段说明生成（标签、类型、下拉选项都来自后端），
  // 这里不写死任何字段名。每个分组一份草稿（state.profileDrafts），输入时直接改草稿；
  // 增删列表条目只重画这一个分组面板（别的面板里没保存的输入不受影响）；
  // 点「保存」把整个分组 PUT 回去。

  function deepCopy(v) {
    return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
  }

  function emptyValue(f) {
    if (f.type === "list" || f.type === "list_text") return [];
    if (f.type === "object") return emptyObject(f.fields);
    return null;
  }

  function emptyObject(fields) {
    var o = {};
    fields.forEach(function (f) { o[f.key] = emptyValue(f); });
    return o;
  }

  // 提交前整理：去掉首尾空格、空字符串变 null、去掉完全没填的列表条目
  function cleanValue(f, v) {
    if (f.type === "list_text") {
      return (v || []).map(function (x) { return (x || "").trim(); }).filter(function (x) { return x; });
    }
    if (f.type === "list") {
      return (v || [])
        .map(function (item) { return cleanObject(f.item_fields, item); })
        .filter(function (item) { return !isBlank(item); });
    }
    if (f.type === "object") return cleanObject(f.fields, v);
    if (typeof v === "string") { v = v.trim(); return v === "" ? null : v; }
    return v === undefined ? null : v;
  }

  function cleanObject(fields, obj) {
    var out = {};
    fields.forEach(function (f) { out[f.key] = cleanValue(f, obj ? obj[f.key] : undefined); });
    return out;
  }

  function isBlank(v) {
    if (v === null || v === undefined || v === "") return true;
    if (Array.isArray(v)) return v.length === 0;
    if (typeof v === "object") return Object.keys(v).every(function (k) { return isBlank(v[k]); });
    return false;
  }

  function profileDraft(group) {
    if (!state.profileDrafts[group.key]) {
      var saved = data.profile[group.key];
      state.profileDrafts[group.key] = saved ? deepCopy(saved) : emptyObject(group.fields);
    }
    return state.profileDrafts[group.key];
  }

  function fieldLabel(f) {
    return el(
      "span",
      { class: "pf-label" },
      f.label,
      f.sensitive ? el("span", { class: "badge sens", text: "敏感", title: "敏感信息：只保存在这台电脑上" }) : null
    );
  }

  // 鼠标悬停时提示对应 DS-160 的哪一问（给想核对的人看）
  function ds160Title(f) {
    return f.ds160 ? "DS-160：" + f.ds160 : null;
  }

  // obj[f.key] 的输入控件；rerender() 重画所在的分组面板（只在增删条目时用）
  function fieldControl(f, obj, rerender) {
    if (f.type === "object") {
      if (!obj[f.key] || typeof obj[f.key] !== "object") obj[f.key] = emptyObject(f.fields);
      return el(
        "fieldset",
        { class: "pf-object", title: ds160Title(f) },
        el("legend", null, fieldLabel(f)),
        el("div", { class: "pf-grid" }, f.fields.map(function (sub) { return fieldControl(sub, obj[f.key], rerender); }))
      );
    }
    if (f.type === "list") return listControl(f, obj, rerender);
    if (f.type === "list_text") return listTextControl(f, obj, rerender);

    var value = obj[f.key];
    var input;
    if (f.type === "select" || f.type === "bool") {
      var options = f.type === "bool"
        ? [{ value: "true", label: "是" }, { value: "false", label: "否" }]
        : f.options;
      var current = value === null || value === undefined ? "" : String(value);
      input = el(
        "select",
        { name: f.key },
        el("option", { value: "", text: "未填" }),
        options.map(function (o) { return el("option", { value: o.value, text: o.label, selected: current === o.value }); })
      );
      input.addEventListener("change", function () {
        var v = input.value;
        obj[f.key] = v === "" ? null : f.type === "bool" ? v === "true" : v;
      });
    } else if (f.type === "textarea") {
      input = el("textarea", { name: f.key, rows: "3" });
      input.value = value || "";
      input.addEventListener("input", function () { obj[f.key] = input.value; });
    } else {
      input = el("input", { type: f.type === "date" ? "date" : "text", name: f.key, value: value || "" });
      input.addEventListener("input", function () { obj[f.key] = input.value; });
    }
    return el(
      "label",
      { class: "pf-field" + (f.type === "textarea" ? " wide" : ""), title: ds160Title(f) },
      fieldLabel(f),
      input
    );
  }

  function listTextControl(f, obj, rerender) {
    if (!Array.isArray(obj[f.key])) obj[f.key] = [];
    var arr = obj[f.key];
    return el(
      "div",
      { class: "pf-list wide", title: ds160Title(f) },
      el("div", { class: "pf-list-head" }, fieldLabel(f), el("small", { text: arr.length ? arr.length + " 项" : "未填" })),
      arr.map(function (item, i) {
        var input = el("input", { type: "text", value: item || "", "aria-label": f.label + " 第 " + (i + 1) + " 项" });
        input.addEventListener("input", function () { arr[i] = input.value; });
        return el(
          "div",
          { class: "pf-text-item" },
          input,
          el("button", { type: "button", class: "linkish", text: "删除", onclick: function () { arr.splice(i, 1); rerender(); } })
        );
      }),
      el("button", { type: "button", class: "pf-add", text: "＋ 添加", onclick: function () { arr.push(""); rerender(); } })
    );
  }

  function listControl(f, obj, rerender) {
    if (!Array.isArray(obj[f.key])) obj[f.key] = [];
    var arr = obj[f.key];
    return el(
      "div",
      { class: "pf-list wide", title: ds160Title(f) },
      el("div", { class: "pf-list-head" }, fieldLabel(f), el("small", { text: arr.length ? arr.length + " 条" : "未填" })),
      arr.map(function (item, i) {
        return el(
          "div",
          { class: "pf-item" },
          el(
            "div",
            { class: "pf-item-head" },
            el("b", { text: "第 " + (i + 1) + " 条" }),
            el("button", { type: "button", class: "linkish", text: "删除这条", onclick: function () { arr.splice(i, 1); rerender(); } })
          ),
          el("div", { class: "pf-grid" }, f.item_fields.map(function (sub) { return fieldControl(sub, item, rerender); }))
        );
      }),
      el("button", {
        type: "button",
        class: "pf-add",
        text: "＋ 添加一条",
        onclick: function () { arr.push(emptyObject(f.item_fields)); rerender(); },
      })
    );
  }

  function nowHm() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  // 「确认没有」（profile.confirmed_none，见 specs/003）：空着 ≠ 没有。
  // 已确认的字段下面显示「✓ 已确认没有」并可撤销；列表类字段（曾用名、拒签记录……）空着时可以直接点「我没有这项」。
  // 文字字段只显示已确认的状态，标记交给填表 Agent 问过之后写，避免姓名这类字段旁边也出现"没有"按钮。
  // 是非题直接选「否」，不用这个标记。填上值再保存时，后端会自动把它移出清单。
  function withNoneMark(group, f, control, draft, rerender) {
    if (f.type === "bool" || f.type === "object") return control;
    var path = group.key + "." + f.key;
    var confirmed = (data.profile.confirmed_none || []).indexOf(path) >= 0;
    var isList = f.type === "list" || f.type === "list_text";
    if (!confirmed && !(isList && isBlank(draft[f.key]) && isBlank(data.profile[group.key] && data.profile[group.key][f.key]))) {
      return control;
    }
    function toggle(none) {
      showError("");
      request("PUT", "/api/personal-profile/confirmed-none", { path: path, none: none })
        .then(function (profile) { data.profile = profile; rerender(); })
        .catch(function (e) { showError(e.message); });
    }
    control.append(
      confirmed
        ? el(
            "div",
            { class: "pf-none" },
            el("span", { text: "✓ 已确认没有（填表时直接答「没有」）" }),
            el("button", { type: "button", class: "linkish", text: "撤销", onclick: function (ev) { ev.preventDefault(); toggle(false); } })
          )
        : el("button", { type: "button", class: "linkish pf-none-btn", text: "我没有这项", title: "确认没有，填表时就不用再问你", onclick: function (ev) { ev.preventDefault(); toggle(true); } })
    );
    return control;
  }

  function profileGroupPanel(group) {
    var draft = profileDraft(group);
    var panel;
    function rerender() {
      panel.replaceWith(profileGroupPanel(group));
    }
    var status = state.profileStatus[group.key];
    var saveBtn = el("button", { class: "primary", type: "submit", text: "保存「" + group.label + "」" });
    var statusEl = el("span", {
      class: "pf-status" + (status && !status.ok ? " error" : ""),
      role: "status",
      text: status ? status.text : "",
    });
    var form = el(
      "form",
      { class: "pf-form", novalidate: true },
      group.key === "travel"
        ? el("p", { class: "muted pf-note", text: "逐次的出入境记录在「出行记录」标签页里维护；这里记以往签证、拒签、去美国的记录等。" })
        : null,
      el("div", { class: "pf-grid" }, group.fields.map(function (f) { return withNoneMark(group, f, fieldControl(f, draft, rerender), draft, rerender); })),
      el("div", { class: "form-actions pf-actions" }, saveBtn, statusEl)
    );
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      saveBtn.disabled = true;
      statusEl.className = "pf-status";
      statusEl.textContent = "保存中…";
      showError("");
      request("PUT", "/api/personal-profile/" + encodeURIComponent(group.key), cleanObject(group.fields, draft))
        .then(function (profile) {
          data.profile = profile;
          state.profileDrafts[group.key] = deepCopy(profile[group.key]);
          state.profileStatus[group.key] = { ok: true, text: "已保存 " + nowHm() };
          rerender();
        })
        .catch(function (e) {
          saveBtn.disabled = false;
          state.profileStatus[group.key] = { ok: false, text: "保存失败：" + e.message };
          statusEl.className = "pf-status error";
          statusEl.textContent = state.profileStatus[group.key].text;
        });
    });

    panel = el(
      "details",
      { class: "panel pgroup", open: !!state.profileOpen[group.key], id: "pgroup-" + group.key },
      el(
        "summary",
        { class: "panel-head" },
        el("h2", { text: group.label }),
        status && status.ok ? el("small", { text: status.text }) : null
      ),
      form
    );
    panel.addEventListener("toggle", function () { state.profileOpen[group.key] = panel.open; });
    return panel;
  }

  function profileTabSection() {
    var groups = data.profileFields || [];
    if (!state.profileOpen) {
      state.profileOpen = {};
      if (groups.length) state.profileOpen[groups[0].key] = true;
    }
    return el(
      "div",
      { class: "profile-tab" },
      el(
        "p",
        { class: "muted profile-intro" },
        "可以反复用到的个人资料：姓名拼音、护照、住址、学历、工作、家庭、签证历史……以后填 DS-160 等表格时可以直接取用。没把握的先留空。"
      ),
      el(
        "p",
        { class: "profile-helper" },
        el("button", {
          type: "button",
          text: "打开填表对照",
          // 窄窗口，方便放在官网旁边；不支持弹窗时退回新标签页
          onclick: function () {
            var w = window.open("/fill-helper.html", "pa-fill-helper", "width=440,height=900");
            if (!w) location.href = "/fill-helper.html";
          },
        }),
        el("small", { class: "muted", text: "　在官网旁边打开，点一下复制、自己粘贴。适合禁止自动填表的网站（例如澳洲 ImmiAccount）。" })
      ),
      groups.map(profileGroupPanel)
    );
  }

  // ---------- 整页 ----------

  function render() {
    if (!data.materials) return;
    setView(
      headingSection(),
      state.tab === "materials" ? overviewLine() : null,
      attentionPanel(),
      newMaterialPanel(),
      tabsNav(),
      state.tab === "travel" ? travelTabSection() : state.tab === "profile" ? profileTabSection() : materialsTabSection()
    );
  }

  window.addEventListener("hashchange", function () {
    syncTabFromHash();
    render();
  });

  // 在抽屉里确认了 Agent 提议的基本信息修改：丢掉那个分组的本地草稿，重新读一遍（spec 004 第 3 步）
  window.addEventListener("agent-data-changed", function (e) {
    if (e.detail.profile_group && state.profileDrafts) delete state.profileDrafts[e.detail.profile_group];
    load();
  });

  document.getElementById("today").textContent = "今天 " + todayIso();
  syncTabFromHash();
  load();
})();
