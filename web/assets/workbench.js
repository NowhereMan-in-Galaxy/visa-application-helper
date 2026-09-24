/* 办事工作台前端。
 *
 * 两条数据线，刻意分开：
 *  1) 真实数据：来自本机 FastAPI 服务的只读接口（签证申请 / 材料 / 个人资料）。
 *     只读展示，不写回，也不把接口里的个人信息存进 localStorage。
 *  2) 本浏览器草稿：新建办事、攻略、工作笔记，存在 localStorage 命名空间
 *     pa-workbench-v1 下，不写服务器、不跨设备。
 *
 * 所有动态文本一律用 textContent / createElement 写入，不用 innerHTML，避免 XSS。
 */
(function () {
  "use strict";

  var KEY = "pa-workbench-v1";
  var PAGES = ["work", "guides", "career", "files", "profile"];
  var CATEGORY_LABEL = {
    passport_scan: "护照扫描件",
    financial_snapshot: "财务快照",
    employment_doc: "工作材料",
    id_photo: "证件照",
  };
  var NOTE_KIND = { guide: "攻略", weekly: "周报", resume: "简历素材" };

  var $ = function (id) {
    return document.getElementById(id);
  };
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function clear(node) {
    node.replaceChildren();
  }

  // ---- 运行态 ----
  var storageBroken = false; // 本地存储读不出来时置位，之后拒绝一切写入，避免覆盖坏数据
  var store = emptyStore();
  var realApps = []; // [{ app, materials|null, error|null }]
  var allMaterials = [];
  var travel = [];
  var careerFilter = "all";
  var errors = [];

  function emptyStore() {
    return { version: 1, items: [], notes: [] };
  }

  // ---- 顶部错误汇总（每源独立，互不拖垮） ----
  function addError(msg) {
    errors.push(msg);
    var b = $("global-error");
    b.hidden = false;
    clear(b);
    b.append(el("strong", null, "部分数据没能加载（其余内容仍可用）："));
    var ul = el("ul");
    errors.forEach(function (m) {
      ul.append(el("li", null, m));
    });
    b.append(ul);
  }

  // ---- localStorage ----
  function loadStore() {
    var raw;
    try {
      raw = localStorage.getItem(KEY);
    } catch (e) {
      storageBroken = true;
      addError("无法访问浏览器本地存储：" + (e && e.message ? e.message : e));
      return emptyStore();
    }
    if (raw === null) return emptyStore();
    try {
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("顶层不是对象");
      }
      return {
        version: 1,
        items: Array.isArray(parsed.items) ? parsed.items : [],
        notes: Array.isArray(parsed.notes) ? parsed.notes : [],
      };
    } catch (e) {
      storageBroken = true;
      addError(
        "本地草稿读取失败（数据可能已损坏）：" +
          (e && e.message ? e.message : e) +
          "。为避免覆盖坏数据，本次不会写入任何新草稿。如确认不再需要，请手动清除浏览器 localStorage 里的 pa-workbench-v1。"
      );
      return emptyStore();
    }
  }

  // 返回 true 表示确实写成功；UI 只有在 true 时才当作已保存。
  function persist(next) {
    if (storageBroken) {
      alert("本地存储处于损坏保护状态，本次改动未保存。");
      return false;
    }
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      return true;
    } catch (e) {
      alert("保存失败，本次改动没有保存：" + (e && e.message ? e.message : e));
      return false;
    }
  }

  function commit(mutate) {
    var next = JSON.parse(JSON.stringify(store));
    mutate(next);
    if (!persist(next)) return false;
    store = next;
    return true;
  }

  function newId(prefix) {
    return prefix + "-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  // ---- 网络 ----
  function getJSON(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function loadRealData() {
    // 签证申请：列表失败只记一条错误；每份申请的材料各自独立请求、独立失败。
    getJSON("/api/visa-applications")
      .then(function (apps) {
        if (!Array.isArray(apps)) throw new Error("返回格式不是数组");
        return apps.reduce(function (chain, app) {
          return chain.then(function () {
            var entry = { app: app, materials: null, error: null };
            realApps.push(entry);
            return getJSON("/api/visa-applications/" + encodeURIComponent(app.id) + "/materials")
              .then(function (mats) {
                entry.materials = Array.isArray(mats) ? mats : [];
              })
              .catch(function (e) {
                entry.error = e && e.message ? e.message : String(e);
              });
          });
        }, Promise.resolve());
      })
      .catch(function (e) {
        addError("签证申请加载失败：" + (e && e.message ? e.message : e));
      })
      .then(function () {
        renderItems();
      });

    // 材料库：失败只影响材料库页面
    getJSON("/api/materials")
      .then(function (mats) {
        allMaterials = Array.isArray(mats) ? mats : [];
      })
      .catch(function (e) {
        addError("材料库加载失败：" + (e && e.message ? e.message : e));
      })
      .then(function () {
        renderMaterials();
      });

    // 个人资料：只取 travel_history，绝不读取或保存证件号等其他字段
    getJSON("/api/personal-profile")
      .then(function (p) {
        travel = p && Array.isArray(p.travel_history) ? p.travel_history : [];
      })
      .catch(function (e) {
        addError("出行记录加载失败：" + (e && e.message ? e.message : e));
      })
      .then(function () {
        renderTravel();
      });
  }

  // ---- 页面切换 ----
  function showPage(page) {
    if (PAGES.indexOf(page) === -1) page = "work";
    document.querySelectorAll("[data-page]").forEach(function (n) {
      n.classList.toggle("active", n.dataset.page === page);
    });
    PAGES.forEach(function (id) {
      var s = $("page-" + id);
      if (s) s.hidden = id !== page;
    });
    if (location.hash.slice(1) !== page) {
      try {
        history.replaceState(null, "", "#" + page);
      } catch (e) {
        /* file:// 等场景下忽略 */
      }
    }
  }

  // ---- 出行记录 ----
  function sortedTravel() {
    return travel.slice().sort(function (a, b) {
      var x = (a && a.entry_date) || "";
      var y = (b && b.entry_date) || "";
      return x < y ? 1 : x > y ? -1 : 0;
    });
  }

  function fillTravelBody(tbody) {
    clear(tbody);
    var rows = sortedTravel();
    if (!rows.length) {
      var tr = el("tr");
      var td = el("td", "muted", "暂无出行记录");
      td.colSpan = 4;
      tr.append(td);
      tbody.append(tr);
      return;
    }
    rows.forEach(function (r) {
      var tr = el("tr");
      tr.append(el("td", null, r.country || "未记录"));
      tr.append(el("td", null, r.entry_date || "—"));
      tr.append(el("td", null, r.exit_date || "未返回"));
      tr.append(el("td", null, r.purpose || "—"));
      tbody.append(tr);
    });
  }

  function renderTravel() {
    fillTravelBody($("travel-body-home"));
    fillTravelBody($("travel-body-profile"));
    var n = String(travel.length);
    $("travel-count").textContent = n;
    $("travel-count-profile").textContent = n;
  }

  // ---- 事项列表 ----
  function isExampleApp(app) {
    return typeof app.id === "string" && app.id.indexOf("example-") === 0;
  }

  function statusTagClass(status) {
    if (status === "已过期") return "tag overdue";
    if (status === "即将过期") return "tag expiring";
    if (status === "已备齐") return "tag done";
    return "tag";
  }

  function renderItems() {
    var box = $("items");
    clear(box);
    var total = 0;

    // 本机草稿（可勾选）
    store.items.forEach(function (item) {
      total++;
      box.append(localItemCard(item));
    });

    // 真实申请（只读）
    realApps.forEach(function (entry) {
      total++;
      box.append(realAppCard(entry));
    });

    if (!total) {
      box.append(el("p", "empty", "还没有事项。点右上角“新建办事”开始，或等本机服务加载真实申请。"));
    }
    $("item-count").textContent = String(total);
  }

  function localItemCard(item) {
    var list = item.checklist || [];
    var done = list.filter(function (c) {
      return c && c.done;
    }).length;
    var article = el("article", "case");

    var top = el("div", "case-top");
    var left = el("div");
    left.append(el("small", null, "本机草稿 · " + (item.category || "其他")));
    left.append(el("h3", null, item.name || "(未命名)"));
    var tag = el("span", "tag", list.length && done === list.length ? "已完成" : "待办 " + done + "/" + list.length);
    top.append(left, tag);
    article.append(top);

    if (item.description) article.append(el("p", "muted", item.description));

    var bar = el("div", "progress");
    var fill = el("i");
    fill.style.width = (list.length ? Math.round((done / list.length) * 100) : 0) + "%";
    bar.append(fill);
    article.append(bar);

    var bottom = el("div", "case-bottom");
    bottom.append(el("small", null, "清单 " + done + " / " + list.length + " 项"));
    var actions = el("div", "row-actions");
    var openBtn = el("button", "linkbtn", "勾选清单 →");
    openBtn.type = "button";
    openBtn.addEventListener("click", function () {
      openDetail(item.id);
    });
    var editBtn = el("button", "linkbtn", "编辑");
    editBtn.type = "button";
    editBtn.addEventListener("click", function () {
      openItemDialog(item);
    });
    var delBtn = el("button", "linkbtn", "删除");
    delBtn.type = "button";
    delBtn.addEventListener("click", function () {
      deleteItem(item.id, item.name);
    });
    actions.append(openBtn, editBtn, delBtn);
    bottom.append(actions);
    article.append(bottom);
    return article;
  }

  function realAppCard(entry) {
    var app = entry.app || {};
    var article = el("article", "case");
    var top = el("div", "case-top");
    var left = el("div");
    left.append(el("small", null, (app.country || "未知国家") + " / " + (app.visa_type || "签证")));
    left.append(el("h3", null, (app.country || "未知国家") + " · " + (app.visa_type || "签证")));
    var tags = el("div", "row-actions");
    if (isExampleApp(app)) tags.append(el("span", "tag example", "示例"));
    if (app.deadline) tags.append(el("span", "tag", "截止 " + app.deadline));
    top.append(left, tags);
    article.append(top);

    var mats = entry.materials || [];
    var doneCount = mats.filter(function (m) {
      return m && m.status === "已备齐";
    }).length;

    var bar = el("div", "progress");
    var fill = el("i");
    fill.style.width = (mats.length ? Math.round((doneCount / mats.length) * 100) : 0) + "%";
    bar.append(fill);
    article.append(bar);

    var bottom = el("div", "case-bottom");
    bottom.append(el("small", null, "材料准备 " + doneCount + " / " + mats.length));
    var viewBtn = el("button", "linkbtn", "查看材料 →");
    viewBtn.type = "button";
    viewBtn.addEventListener("click", function () {
      openDetail(null, entry);
    });
    bottom.append(viewBtn);
    article.append(bottom);

    if (entry.error) {
      article.append(el("p", "section-msg error", "这份申请的材料加载失败：" + entry.error));
    } else if (!mats.length) {
      article.append(el("p", "muted", "这次申请下还没有材料记录。"));
    }
    return article;
  }

  // ---- 详情 dialog（本机草稿可勾选 / 真实申请只读） ----
  function openDetail(itemId, entry) {
    var dialog = $("detail-dialog");
    var listBox = $("detail-list");
    clear(listBox);
    var note = $("detail-note");
    var foot = $("detail-foot");

    if (itemId) {
      var item = store.items.find(function (i) {
        return i.id === itemId;
      });
      if (!item) return;
      $("detail-title").textContent = item.name || "(未命名)";
      note.textContent = "本机草稿 · 勾选后会立即保存到这台浏览器（localStorage: pa-workbench-v1）。";
      if (!item.description) {
        /* 描述留空就不占位 */
      } else {
        listBox.append(el("p", "muted", item.description));
      }
      (item.checklist || []).forEach(function (c, idx) {
        var row = el("label", "chk");
        var input = document.createElement("input");
        input.type = "checkbox";
        input.checked = !!c.done;
        input.addEventListener("change", function () {
          toggleChecklist(itemId, idx, input.checked, input);
        });
        var span = el("span", c.done ? "done" : null, c.text);
        row.append(input, span);
        listBox.append(row);
      });
      if (!(item.checklist || []).length) {
        listBox.append(el("p", "muted", "这条事项还没有清单，编辑时每行填一项。"));
      }
      foot.textContent = checklistFoot(item);
      foot.dataset.itemId = itemId;
      dialog.showModal();
      return;
    }

    // 真实申请
    var app = (entry && entry.app) || {};
    $("detail-title").textContent = (app.country || "未知国家") + " · " + (app.visa_type || "签证");
    note.textContent = "真实数据 · 只读展示，状态由本机服务计算；本页不会修改或提交任何材料。";
    if (isExampleApp(app)) {
      note.textContent += " 这条申请 id 以 example- 开头，是示例数据。";
    }
    var mats = (entry && entry.materials) || [];
    if (entry && entry.error) {
      listBox.append(el("p", "section-msg error", "材料加载失败：" + entry.error));
    } else if (!mats.length) {
      listBox.append(el("p", "muted", "这次申请下还没有材料记录。"));
    } else {
      mats.forEach(function (m) {
        var row = el("div", "mat-row");
        var nameBox = el("div");
        nameBox.append(el("div", null, m.type || "(未命名材料)"));
        if (m.sublabel) nameBox.append(el("small", "muted", m.sublabel));
        row.append(nameBox, el("span", statusTagClass(m.status), m.status || "—"));
        listBox.append(row);
      });
    }
    foot.textContent = "";
    delete foot.dataset.itemId;
    dialog.showModal();
  }

  function checklistFoot(item) {
    var list = item.checklist || [];
    var done = list.filter(function (c) {
      return c && c.done;
    }).length;
    return "已勾选 " + done + " / " + list.length + " 项";
  }

  function toggleChecklist(itemId, idx, checked, box) {
    var ok = commit(function (next) {
      var it = next.items.find(function (i) {
        return i.id === itemId;
      });
      if (!it || !it.checklist[idx]) return;
      it.checklist[idx].done = checked;
      it.updatedAt = new Date().toISOString();
    });
    if (!ok) {
      box.checked = !checked; // 写失败就回滚勾选，不谎称已保存
      return;
    }
    var item = store.items.find(function (i) {
      return i.id === itemId;
    });
    var span = box.parentElement.querySelector("span");
    if (span) span.className = checked ? "done" : "";
    $("detail-foot").textContent = checklistFoot(item);
    renderItems();
  }

  function deleteItem(itemId, name) {
    if (!confirm('删除本机草稿「' + (name || "") + '」？此操作不可撤销。')) return;
    if (commit(function (next) {
      next.items = next.items.filter(function (i) {
        return i.id !== itemId;
      });
    })) {
      renderItems();
    }
  }

  // ---- 新建 / 编辑办事 ----
  var editingItemId = null;

  function openItemDialog(item) {
    editingItemId = item ? item.id : null;
    $("item-dialog-title").textContent = item ? "编辑办事" : "新建办事";
    $("item-name").value = item ? item.name || "" : "";
    $("item-category").value = item && item.category ? item.category : "签证";
    $("item-desc").value = item ? item.description || "" : "";
    $("item-checklist").value = item
      ? (item.checklist || [])
          .map(function (c) {
            return c.text;
          })
          .join("\n")
      : "";
    $("item-dialog").showModal();
  }

  function buildChecklist(text, oldList) {
    var old = oldList || [];
    return text
      .split("\n")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean)
      .map(function (t, i) {
        var prev = old[i];
        return { text: t, done: prev && prev.text === t ? !!prev.done : false };
      });
  }

  function submitItem(ev) {
    ev.preventDefault();
    var name = $("item-name").value.trim();
    var category = $("item-category").value;
    var description = $("item-desc").value.trim();
    var checklist = buildChecklist($("item-checklist").value);
    if (!name) {
      alert("请填写事项名称。");
      return;
    }
    var now = new Date().toISOString();
    var ok;
    if (editingItemId) {
      var id = editingItemId;
      ok = commit(function (next) {
        var it = next.items.find(function (i) {
          return i.id === id;
        });
        if (!it) return;
        it.name = name;
        it.category = category;
        it.description = description;
        it.checklist = buildChecklist($("item-checklist").value, it.checklist);
        it.updatedAt = now;
      });
    } else {
      ok = commit(function (next) {
        next.items.unshift({
          id: newId("item"),
          name: name,
          category: category,
          description: description,
          checklist: checklist,
          createdAt: now,
          updatedAt: now,
        });
      });
    }
    if (!ok) return; // 保存失败，对话框保持打开，不假装已保存
    $("item-dialog").close();
    renderItems();
    showPage("work");
  }

  // ---- 笔记（攻略 / 周报 / 简历素材） ----
  var editingNoteId = null;

  function safeUrl(u) {
    if (!u) return null;
    try {
      var url = new URL(u, location.origin);
      if (url.protocol === "http:" || url.protocol === "https:") return url.href;
    } catch (e) {
      /* 非法链接 */
    }
    return null;
  }

  function openNoteDialog(kind, note) {
    editingNoteId = note ? note.id : null;
    $("note-dialog-title").textContent = note ? "编辑笔记" : "新建笔记";
    $("note-kind").value = note ? note.kind : kind || "guide";
    $("note-title").value = note ? note.title || "" : "";
    $("note-url").value = note ? note.sourceUrl || "" : "";
    $("note-body").value = note ? note.body || "" : "";
    syncNoteUrlVisibility();
    $("note-dialog").showModal();
  }

  function syncNoteUrlVisibility() {
    $("note-url-wrap").hidden = $("note-kind").value !== "guide";
  }

  function submitNote(ev) {
    ev.preventDefault();
    var kind = $("note-kind").value;
    var title = $("note-title").value.trim();
    var body = $("note-body").value.trim();
    var sourceUrl = kind === "guide" ? $("note-url").value.trim() : "";
    if (!title) {
      alert("请填写标题。");
      return;
    }
    var now = new Date().toISOString();
    var ok;
    if (editingNoteId) {
      var id = editingNoteId;
      ok = commit(function (next) {
        var n = next.notes.find(function (x) {
          return x.id === id;
        });
        if (!n) return;
        n.kind = kind;
        n.title = title;
        n.sourceUrl = sourceUrl;
        n.body = body;
        n.updatedAt = now;
      });
    } else {
      ok = commit(function (next) {
        next.notes.unshift({
          id: newId("note"),
          kind: kind,
          title: title,
          sourceUrl: sourceUrl,
          body: body,
          createdAt: now,
          updatedAt: now,
        });
      });
    }
    if (!ok) return;
    $("note-dialog").close();
    renderGuides();
    renderCareer();
    showPage(kind === "guide" ? "guides" : "career");
  }

  function deleteNote(id, title) {
    if (!confirm('删除笔记「' + (title || "") + '」？此操作不可撤销。')) return;
    if (commit(function (next) {
      next.notes = next.notes.filter(function (n) {
        return n.id !== id;
      });
    })) {
      renderGuides();
      renderCareer();
    }
  }

  function noteCard(n) {
    var card = el("article", "note-card");
    var top = el("div", "case-top");
    var left = el("div");
    left.append(el("small", null, NOTE_KIND[n.kind] || "笔记"));
    left.append(el("h3", null, n.title || "(无标题)"));
    var actions = el("div", "row-actions");
    var editBtn = el("button", "linkbtn", "编辑");
    editBtn.type = "button";
    editBtn.addEventListener("click", function () {
      openNoteDialog(n.kind, n);
    });
    var delBtn = el("button", "linkbtn", "删除");
    delBtn.type = "button";
    delBtn.addEventListener("click", function () {
      deleteNote(n.id, n.title);
    });
    actions.append(editBtn, delBtn);
    top.append(left, actions);
    card.append(top);

    if (n.kind === "guide" && n.sourceUrl) {
      var href = safeUrl(n.sourceUrl);
      if (href) {
        var a = el("a", null, "来源：" + n.sourceUrl);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        card.append(a);
      } else {
        card.append(el("p", "muted", "来源（链接格式无效，仅文字）：" + n.sourceUrl));
      }
    }
    if (n.body) card.append(el("div", "note-body", n.body));
    return card;
  }

  function renderGuides() {
    var box = $("guide-list");
    clear(box);
    var guides = store.notes.filter(function (n) {
      return n.kind === "guide";
    });
    guides.forEach(function (n) {
      box.append(noteCard(n));
    });
    if (!guides.length) box.append(el("p", "empty", "还没有攻略草稿。点“新建攻略”记一条。"));
    $("guide-count").textContent = String(guides.length);
  }

  function renderCareer() {
    var box = $("career-list");
    clear(box);
    var notes = store.notes.filter(function (n) {
      return n.kind === "weekly" || n.kind === "resume";
    });
    var shown = notes.filter(function (n) {
      return careerFilter === "all" || n.kind === careerFilter;
    });
    shown.forEach(function (n) {
      box.append(noteCard(n));
    });
    if (!shown.length) {
      box.append(el("p", "empty", notes.length ? "这个筛选下没有笔记。" : "还没有工作笔记。点“新建工作笔记”记一条周报或简历素材。"));
    }
    $("career-count").textContent = String(notes.length);
  }

  // ---- 材料库 ----
  function renderMaterials() {
    var q = ($("material-search").value || "").trim().toLowerCase();
    var body = $("material-body");
    clear(body);
    var rows = allMaterials.filter(function (m) {
      if (!q) return true;
      var hay = [
        m.type || "",
        m.sublabel || "",
        CATEGORY_LABEL[m.category] || m.category || "",
        m.status || "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    if (!rows.length) {
      var tr = el("tr");
      var td = el("td", "muted", allMaterials.length ? "没有匹配的材料。" : "材料库暂时没有数据。");
      td.colSpan = 5;
      tr.append(td);
      body.append(tr);
    } else {
      rows.forEach(function (m) {
        var tr = el("tr");
        tr.append(el("td", null, m.type || "(未命名)"));
        tr.append(el("td", null, CATEGORY_LABEL[m.category] || m.category || "—"));
        var stTd = el("td");
        stTd.append(el("span", statusTagClass(m.status), m.status || "—"));
        tr.append(stTd);
        tr.append(el("td", null, m.obtained_date || "—"));
        tr.append(el("td", null, m.sublabel || "—"));
        body.append(tr);
      });
    }
    $("material-count").textContent =
      "显示 " + rows.length + " / 共 " + allMaterials.length + " 条（只读）";
  }

  // ---- 绑定 ----
  function bind() {
    document.querySelectorAll("[data-page]").forEach(function (b) {
      b.addEventListener("click", function () {
        showPage(b.dataset.page);
      });
    });
    document.querySelectorAll("[data-goto]").forEach(function (b) {
      b.addEventListener("click", function () {
        showPage(b.dataset.goto);
      });
    });
    document.querySelectorAll("[data-close]").forEach(function (b) {
      b.addEventListener("click", function () {
        var d = $(b.dataset.close);
        if (d) d.close();
      });
    });

    $("new-item").addEventListener("click", function () {
      openItemDialog(null);
    });
    $("item-form").addEventListener("submit", submitItem);

    $("new-guide").addEventListener("click", function () {
      openNoteDialog("guide", null);
    });
    $("new-career").addEventListener("click", function () {
      openNoteDialog("weekly", null);
    });
    $("note-form").addEventListener("submit", submitNote);
    $("note-kind").addEventListener("change", syncNoteUrlVisibility);

    document.querySelectorAll("[data-career-filter]").forEach(function (b) {
      b.addEventListener("click", function () {
        careerFilter = b.dataset.careerFilter;
        renderCareer();
      });
    });

    $("material-search").addEventListener("input", renderMaterials);

    window.addEventListener("hashchange", function () {
      showPage(location.hash.slice(1));
    });
  }

  // ---- 启动 ----
  function init() {
    store = loadStore();
    bind();
    renderItems();
    renderGuides();
    renderCareer();
    renderMaterials();
    renderTravel();
    showPage(location.hash.slice(1) || "work");
    loadRealData();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
