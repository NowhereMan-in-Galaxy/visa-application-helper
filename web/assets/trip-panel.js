// 办事页的「这次行程」（specs/007-trip-info）：目的、日期、住处、邀请人、费用、同行人。
// 按 TrackView.trip_groups 画输入框；改了（失焦 / 选择）就 PUT /api/tracks/<id>/trip，只发改的那一格。
// guides.js 调用 window.TripPanel.render(v, {el, save, redraw})。
(function () {
  "use strict";

  var expanded = {}; // 哪些办事把这一块展开了（只在页面内存里）

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
    if (t.host_name) parts.push("邀请人 " + t.host_name);
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
    if (f.type === "list") return [companions(el, f, value || [], save)];
    return [cell(el, f.label, input(el, f, value, function (x) {
      var change = {}; change[f.key] = x; save(change);
    }), f.type === "textarea")];
  }

  // 同行人：每人一行（姓名 / 关系 / 删除），列表整体发回去
  function companions(el, f, list, save) {
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
    return el("div", { class: "trip-cell wide" },
      el("span", { text: f.label }),
      rows,
      el("button", { type: "button", class: "linkish", text: "＋ 加一位", onclick: function () {
        send(list.concat([{}]));
      } })
    );
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
      return el("section", { class: "panel facts-summary" },
        el("span", { class: "muted", text: "这次行程：" }),
        el("span", { text: summary(v) || "已填 " + filled + " 项" }),
        el("button", { type: "button", class: "linkish", text: "修改", onclick: function () { toggle(true); } })
      );
    }
    return el("section", { class: "panel trip" },
      el("div", { class: "panel-head" },
        el("h2", { text: "这次行程" }),
        filled ? el("button", { type: "button", class: "linkish", text: "收起", onclick: function () { toggle(false); } }) : null
      ),
      v.trip_groups.map(function (g) {
        return el("fieldset", { class: "trip-group" },
          el("legend", { text: g.label }),
          el("div", { class: "trip-grid" }, g.fields.map(function (f) { return fieldCells(el, f, v.trip[f.key], save); }))
        );
      })
    );
  }

  window.TripPanel = { render: render };
})();
