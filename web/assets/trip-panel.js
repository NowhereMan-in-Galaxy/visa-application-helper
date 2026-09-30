// 办事页的「这次行程」（specs/007-trip-info）：目的、日期、交通、行程安排、住处、邀请人、费用、同行人。
// 按 TrackView.trip_groups 画输入框；改了（失焦 / 选择）就 PUT /api/tracks/<id>/trip，只发改的那一格。
// 顶部「让 Agent 整理」（第 2 步）：说几句话、勾选这件事的材料，Agent 提议，确认卡片点了才存。
// guides.js 调用 window.TripPanel.render(v, {el, save, redraw})。
(function () {
  "use strict";

  var expanded = {}; // 哪些办事把这一块展开了（只在页面内存里）
  var extractors = {}; // 办事 id → {chat, picked, v}：对话窗口整页只建一份，重画时挂回去，不丢对话

  function isEmpty(v) {
    if (v === null || v === undefined || v === "") return true;
    if (Array.isArray(v)) return !v.length;
    if (typeof v === "object") return Object.keys(v).every(function (k) { return isEmpty(v[k]); });
    return false;
  }

  function filledCount(v) {
    var n = 0;
    v.trip_groups.forEach(function (g) {
      g.fields.forEach(function (f) { if (!isEmpty(v.trip[f.key])) n++; });
    });
    return n;
  }

  // 收起时的一行摘要：目的 · 日期 · 住处城市 · 邀请人
  function summary(v) {
    var t = v.trip, parts = [];
    if (t.purpose) parts.push(t.purpose);
    if (t.arrival_date || t.departure_date) parts.push((t.arrival_date || "?") + " → " + (t.departure_date || "?"));
    var stay = t.stay_name || (t.stay_address && t.stay_address.city);
    if (stay) parts.push("住 " + stay);
    if (t.itinerary && t.itinerary.length) parts.push("行程 " + t.itinerary.length + " 段");
    var host = t.host_organization || t.host_name;
    if (host) parts.push("邀请 " + host);
    if (t.companions && t.companions.length) parts.push("同行 " + t.companions.length + " 人");
    return parts.join(" · ");
  }

  function input(el, f, value, onSave) {
    var node;
    if (f.type === "select") {
      node = el("select", null, el("option", { value: "", text: "—" }), f.options.map(function (o) {
        return el("option", { value: o.value, text: o.label, selected: value === o.value });
      }));
    } else if (f.type === "textarea") {
      node = el("textarea", { rows: "2" });
      node.value = value || "";
    } else {
      node = el("input", { type: f.type === "date" ? "date" : "text", value: value || null });
    }
    node.setAttribute("aria-label", f.label);
    node.addEventListener("change", function () { onSave(node.value.trim() || null); });
    return node;
  }

  function cell(el, label, control, wide) {
    return el("label", { class: "trip-cell" + (wide ? " wide" : "") }, el("span", { text: label }), control);
  }

  function fieldCells(el, f, value, save) {
    if (f.type === "object") {
      var obj = value || {};
      return f.fields.map(function (sub) {
        return cell(el, f.label + " · " + sub.label, input(el, sub, obj[sub.key], function (x) {
          var change = {}; change[f.key] = {}; change[f.key][sub.key] = x; save(change);
        }), sub.key === "street");
      });
    }
    if (f.type === "list") return [listField(el, f, value || [], save)];
    return [cell(el, f.label, input(el, f, value, function (x) {
      var change = {}; change[f.key] = x; save(change);
    }), f.type === "textarea")];
  }

  // 同行人、行程安排：每项一行（各个小格 / 删除），列表整体发回去
  function listField(el, f, list, save) {
    function send(next) { var change = {}; change[f.key] = next; save(change); }
    var rows = list.map(function (item, idx) {
      return el("div", { class: "trip-row" },
        f.item_fields.map(function (sub) {
          return input(el, sub, item[sub.key], function (x) {
            var next = list.map(function (it) { return Object.assign({}, it); });
            next[idx][sub.key] = x;
            send(next);
          });
        }),
        el("button", { type: "button", class: "linkish", text: "删除", onclick: function () {
          send(list.filter(function (_, k) { return k !== idx; }));
        } })
      );
    });
    return el("div", { class: "trip-cell wide" },  // 列表自己占一组，组名就是它的名字，不再重复
      rows,
      el("button", { type: "button", class: "linkish", text: f.key === "companions" ? "＋ 加一位" : "＋ 加一段", onclick: function () {
        send(list.concat([{}]));
      } })
    );
  }

  function materialLabel(m) { return m.type + (m.sublabel ? " · " + m.sublabel : ""); }

  // 「让 Agent 整理」：输入框 + 勾选材料 + 对话记录（确认卡片也出现在这里）
  function extractBox(el, v) {
    if (!window.AgentChat) return null;
    var st = extractors[v.id];
    if (!st) {
      st = extractors[v.id] = { picked: {} };
      v.trip_materials.forEach(function (m) { st.picked[m.id] = m.one_off; });
      st.chat = window.AgentChat.create({
        kind: "trip_extract",
        context: function () { return { page: "track", track_id: st.v.id, materials: pickedIds() }; },
        placeholder: "用几句话说说这次行程，例如：10 月 1 日到 15 日去悉尼开会，住会场旁边的酒店，学校出钱",
        rows: 2,
        enterNewline: true,
        sendLabel: function (again) { return again ? "接着说" : "让 Agent 整理"; },
        emptyText: function () { return pickedIds().length ? "读我勾选的材料" : ""; },
      });
    }
    st.v = v;
    function pickedIds() {
      return st.v.trip_materials.filter(function (m) { return st.picked[m.id]; }).map(function (m) { return m.id; });
    }
    var chips = v.trip_materials.length ? el("div", { class: "trip-mats" },
      el("span", { class: "muted", text: "读材料：" }),
      v.trip_materials.map(function (m) {
        var box = el("input", { type: "checkbox" });
        box.checked = !!st.picked[m.id];
        box.addEventListener("change", function () { st.picked[m.id] = box.checked; });
        return el("label", { class: "trip-mat" }, box, el("span", { text: materialLabel(m) }));
      })
    ) : null;
    return el("div", { class: "trip-extract" }, chips, st.chat.root);
  }

  function render(v, deps) {
    var el = deps.el;
    if (!v.trip_groups || !v.trip_groups.length) return null;
    var filled = filledCount(v);
    var open = expanded[v.id] !== undefined ? expanded[v.id] : !filled; // 一项都没填时默认展开
    function toggle(on) { expanded[v.id] = on; deps.redraw(v); }
    // 开始填了就保持展开，不然填完第一格这一块就收起来了
    function save(change) { expanded[v.id] = true; deps.save(v, change); }

    if (!open) {
      return el("section", { class: "panel facts-summary", id: "trip" },
        el("span", { class: "muted", text: "这次行程：" }),
        el("span", { text: summary(v) || "已填 " + filled + " 项" }),
        el("button", { type: "button", class: "linkish", text: "修改", onclick: function () { toggle(true); } })
      );
    }
    return el("section", { class: "panel trip", id: "trip" },
      el("div", { class: "panel-head" },
        el("h2", { text: "这次行程" }),
        filled ? el("button", { type: "button", class: "linkish", text: "收起", onclick: function () { toggle(false); } }) : null
      ),
      extractBox(el, v),
      v.trip_groups.map(function (g) {
        return el("fieldset", { class: "trip-group" },
          el("legend", { text: g.label }),
          el("div", { class: "trip-grid" }, g.fields.map(function (f) { return fieldCells(el, f, v.trip[f.key], save); }))
        );
      })
    );
  }

  // 开始清单的"让 Agent 整理"：展开这一块（spec 007 第 3 步）
  function open(id) { expanded[id] = true; }

  window.TripPanel = { render: render, open: open };
})();
