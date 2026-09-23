/* 攻略库 + 我的办事（specs/002-guide-to-track）。
 *
 * 三个视图，用 URL 的 # 部分切换（刷新页面后仍停留在原来的视图）：
 *   #/                攻略库 + 我正在办的事
 *   #/guide/<id>      攻略预览（用你现有的材料先算一遍"已经有哪些"）+ 开始办
 *   #/track/<id>      我的办事：回答问题、勾步骤、确认材料、最终核对
 *
 * 所有状态（哪条材料缺、下一步是什么）都由后端核心库算好，前端只负责展示和把用户操作发回去。
 * 动态文本一律用 textContent 写入，不用 innerHTML，避免攻略内容里夹带的脚本被执行。
 */
(function () {
  "use strict";

  var STATE_LABEL = {
    ready: "已有",
    unconfirmed: "待确认",
    stale: "需重新开具",
    missing: "缺",
    undecided: "待定",
    not_applicable: "不适用",
  };
  var STATE_ORDER = ["missing", "stale", "unconfirmed", "ready"];
  var KIND_LABEL = { generate: "可让 AI 起草", output: "做完某一步后得到" };

  var view = document.getElementById("view");
  var errorBox = document.getElementById("error");

  // ---------- 小工具 ----------

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

  function daysBetween(fromIso, toIso) {
    return Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 86400000);
  }

  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  function progressBar(ready, total) {
    var pct = total ? Math.round((ready / total) * 100) : 0;
    var bar = el("div", { class: "progress", role: "img", "aria-label": "进度 " + ready + " / " + total });
    var fill = el("i");
    fill.style.width = pct + "%";
    bar.append(fill);
    return bar;
  }

  function stateChip(state) {
    return el("span", { class: "state state-" + state, text: STATE_LABEL[state] || state });
  }

  function evidenceBlock(evidence, sources) {
    if (!evidence || !evidence.length) return null;
    var titles = {};
    (sources || []).forEach(function (s) { titles[s.id] = s.title; });
    return el(
      "details",
      { class: "evidence" },
      el("summary", { text: "攻略原话" }),
      evidence.map(function (e) {
        return el("blockquote", null, "“" + e.quote + "”", el("br"), el("small", { text: "—— " + (titles[e.source] || e.source) }));
      })
    );
  }

  function conditionText(conditions, factsByKey) {
    return conditions
      .map(function (c) {
        var f = factsByKey[c.fact];
        return (f ? f.question.replace(/[？?]$/, "") : c.fact) + "：" + c.in.join(" / ");
      })
      .join("；");
  }

  // ---------- 路由 ----------

  function route() {
    showError("");
    var hash = location.hash.replace(/^#\/?/, "");
    var parts = hash.split("/");
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      a.classList.toggle("active", parts[0] === "" || parts[0] === "guide" || parts[0] === "track");
    });
    view.replaceChildren(el("p", { class: "muted", text: "加载中…" }));
    if (parts[0] === "guide" && parts[1]) return renderGuide(decodeURIComponent(parts[1]));
    if (parts[0] === "track" && parts[1]) return renderTrack(decodeURIComponent(parts[1]));
    return renderHome();
  }

  // ---------- 首页：我正在办的 + 攻略库 ----------

  function renderHome() {
    Promise.all([request("GET", "/api/tracks"), request("GET", "/api/guides")])
      .then(function (results) {
        var tracks = results[0];
        var guides = results[1];
        var guideTitle = {};
        guides.forEach(function (g) { guideTitle[g.id] = g.title; });

        var trackCards = tracks.map(function (t) {
          return el(
            "a",
            { class: "card", href: "#/track/" + encodeURIComponent(t.id) },
            el("span", { class: "meta", text: "照着：" + (guideTitle[t.guide_id] || t.guide_id) }),
            el("h3", { text: t.title }),
            t.error
              ? el("p", { class: "meta", text: "暂时打不开：" + t.error })
              : [
                  progressBar(t.progress_ready, t.progress_total),
                  el("span", { class: "meta", text: "材料 " + t.progress_ready + " / " + t.progress_total + " 已备齐" }),
                  el("div", { class: "next", text: t.next_step_title ? "下一步：" + t.next_step_title : "没有可以马上做的步骤" }),
                ]
          );
        });

        var guideCards = guides.map(function (g) {
          if (!g.valid) {
            return el(
              "div",
              { class: "card invalid" },
              el("span", { class: "meta", text: g.file }),
              el("h3", { text: g.title || g.id }),
              el("p", { class: "meta", text: "这份攻略没有通过校验，暂时不能使用：" }),
              el("ul", null, g.errors.slice(0, 5).map(function (e) { return el("li", { text: e }); }))
            );
          }
          return el(
            "a",
            { class: "card", href: "#/guide/" + encodeURIComponent(g.id) },
            el("span", { class: "tag", text: g.category }),
            el("h3", { text: g.title }),
            g.summary ? el("p", { class: "meta", text: g.summary }) : null,
            el("div", { class: "next", text: g.step_count + " 个步骤 · " + g.requirement_count + " 项材料" + (g.updated ? " · 更新于 " + g.updated : "") })
          );
        });

        view.replaceChildren(
          el(
            "div",
            { class: "heading" },
            el("div", null, el("h1", { text: "照着攻略，一件件办好。" }), el("p", { class: "muted", text: "攻略由大家共同维护；你的进度只保存在这台电脑上。" }))
          ),
          el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "我正在办的", el("span", { class: "count", text: tracks.length }))),
            trackCards.length ? el("div", { class: "cards" }, trackCards) : el("p", { class: "empty", text: "还没有。从下面的攻略库里挑一份，点进去开始办。" })
          ),
          el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "攻略库", el("span", { class: "count", text: guides.length })), el("small", { text: "community/guides/" })),
            guideCards.length ? el("div", { class: "cards" }, guideCards) : el("p", { class: "empty", text: "攻略库是空的。" })
          ),
          el(
            "p",
            { class: "notice" },
            "想贡献一份攻略？把杂乱的图文攻略交给你本地的 Agent，按 ",
            el("code", { text: "specs/002-guide-to-track/prompt.md" }),
            " 整理成 YAML 放进 ",
            el("code", { text: "community/guides/" }),
            "，跑一遍 ",
            el("code", { text: "PYTHONPATH=src uv run python -m core.guides" }),
            " 校验通过即可。详见 ",
            el("code", { text: "community/README.md" }),
            "。"
          )
        );
      })
      .catch(function (e) {
        view.replaceChildren();
        showError(e.message);
      });
  }

  // ---------- 攻略预览 ----------

  function renderGuide(id) {
    request("GET", "/api/guides/" + encodeURIComponent(id))
      .then(function (detail) {
        var s = detail.summary;
        var head = el(
          "div",
          { class: "heading" },
          el(
            "div",
            null,
            el("div", { class: "crumb" }, el("a", { href: "#/", text: "攻略库" }), " / " + s.id),
            el("h1", { text: s.title || s.id }),
            s.summary ? el("p", { class: "muted", text: s.summary }) : null
          )
        );
        if (!s.valid) {
          view.replaceChildren(
            head,
            el("div", { class: "banner" }, "这份攻略没有通过校验，暂时不能使用：", el("ul", null, s.errors.map(function (e) { return el("li", { text: e }); })))
          );
          return;
        }
        var p = detail.preview;
        var form = el(
          "form",
          { class: "start" },
          el("h2", { text: "开始办这件事" }),
          el("label", null, "给这次起个名字（可选）", el("input", { name: "title", type: "text", placeholder: s.title })),
          el("label", null, "最晚什么时候要办完（可选）", el("input", { name: "deadline", type: "date" })),
          el("button", { class: "primary", type: "submit", text: "开始办 →" }),
          el("small", { text: "会在你的材料根目录下新建一个进度文件，不会改动这份攻略。" })
        );
        form.addEventListener("submit", function (ev) {
          ev.preventDefault();
          var btn = form.querySelector("button");
          btn.disabled = true;
          request("POST", "/api/tracks", {
            guide: s.id,
            title: form.elements.title.value || null,
            deadline: form.elements.deadline.value || null,
          })
            .then(function (t) { location.hash = "#/track/" + encodeURIComponent(t.id); })
            .catch(function (e) { btn.disabled = false; showError(e.message); });
        });

        view.replaceChildren(
          head,
          el(
            "p",
            { class: "notice" },
            "这是预览：已经用你材料库里现有的材料先对了一遍。开始办之后回答几个问题，和你无关的材料会自动隐藏。"
          ),
          trackBody(p, { readonly: true, aside: el("section", { class: "panel" }, form) })
        );
      })
      .catch(function (e) {
        view.replaceChildren();
        showError(e.message);
      });
  }

  // ---------- 我的办事 ----------

  function renderTrack(id) {
    request("GET", "/api/tracks/" + encodeURIComponent(id))
      .then(function (v) { drawTrack(v); })
      .catch(function (e) {
        view.replaceChildren(el("p", null, el("a", { href: "#/", text: "← 回到攻略库" })));
        showError(e.message);
      });
  }

  function drawTrack(v) {
    var head = el(
      "div",
      { class: "heading" },
      el(
        "div",
        null,
        el("div", { class: "crumb" }, el("a", { href: "#/", text: "我正在办的" }), " / 照着 ", el("a", { href: "#/guide/" + encodeURIComponent(v.guide_id), text: v.guide_title })),
        el("h1", { text: v.title }),
        v.deadline
          ? el("p", { class: "muted", text: "截止 " + v.deadline + "（" + deadlineText(v.deadline) + "）" })
          : el("p", { class: "muted", text: "创建于 " + v.created })
      )
    );
    // 重新渲染会替换整块内容，先记住滚动位置，避免每点一次就跳回顶部
    var y = window.scrollY;
    view.replaceChildren(head, trackBody(v, { readonly: false }));
    window.scrollTo(0, y);
  }

  function deadlineText(deadline) {
    var d = daysBetween(todayIso(), deadline);
    if (d > 0) return "还有 " + d + " 天";
    if (d === 0) return "就是今天";
    return "已经过了 " + -d + " 天";
  }

  function update(v, path, body) {
    showError("");
    return request("PUT", "/api/tracks/" + encodeURIComponent(v.id) + path, body)
      .then(drawTrack)
      .catch(function (e) { showError(e.message); });
  }

  // 攻略预览和我的办事共用同一套渲染，区别只在 readonly：预览里不能勾选、不能确认
  function trackBody(v, opts) {
    var readonly = opts.readonly;
    var factsByKey = {};
    v.facts.forEach(function (f) { factsByKey[f.key] = f; });
    var reqById = {};
    v.requirements.forEach(function (r) { reqById[r.id] = r; });
    var stepById = {};
    v.steps.forEach(function (s) { stepById[s.id] = s; });

    var main = el("div");

    // --- 下一步 ---
    if (!readonly) main.append(nextCard(v, stepById, reqById));

    // --- 问题 ---
    var asked = v.facts.filter(function (f) { return f.asked; });
    if (asked.length) {
      var unanswered = asked.filter(function (f) { return f.value === null; }).length;
      main.append(
        el(
          "section",
          { class: "panel" },
          el(
            "div",
            { class: "panel-head" },
            el("h2", { text: readonly ? "开始办之后会问你这些问题" : "先回答几个问题" }),
            el("small", { text: readonly ? "回答后，和你无关的材料会自动隐藏" : unanswered ? "还有 " + unanswered + " 个没回答" : "都回答了，可以随时改" })
          ),
          el(
            "div",
            { class: "facts" },
            asked.map(function (f) {
              return el(
                "div",
                { class: "fact" + (f.value !== null ? " answered" : "") },
                el("div", { class: "q", text: f.question }),
                el(
                  "div",
                  { class: "options" },
                  f.options.map(function (opt) {
                    var pressed = f.value === opt;
                    return el("button", {
                      type: "button",
                      text: opt,
                      disabled: readonly,
                      "aria-pressed": pressed ? "true" : "false",
                      onclick: function () { update(v, "/facts/" + encodeURIComponent(f.key), { value: pressed ? null : opt }); },
                    });
                  })
                )
              );
            })
          )
        )
      );
    }

    // --- 步骤时间线 ---
    var anchored = {};
    var visibleSteps = v.steps.filter(function (s) { return s.applies !== "no"; });
    main.append(
      el(
        "section",
        { class: "panel" },
        el(
          "div",
          { class: "panel-head" },
          el("h2", null, "步骤", el("span", { class: "count", text: visibleSteps.length })),
          el("small", { text: "不适用于你的步骤已隐藏" })
        ),
        el(
          "ol",
          { class: "timeline" },
          visibleSteps.map(function (s) {
            return stepItem(s, v, { readonly: readonly, reqById: reqById, stepById: stepById, factsByKey: factsByKey, anchored: anchored });
          })
        )
      )
    );

    // --- 最终核对 ---
    if (v.checks.length) {
      main.append(
        el(
          "section",
          { class: "panel" },
          el("div", { class: "panel-head" }, el("h2", { text: "递交前最后核对" }), el("small", { text: "材料之间必须对得上的地方" })),
          el(
            "div",
            { class: "checks" },
            v.checks.map(function (c) {
              var box = el("input", {
                type: "checkbox",
                id: "chk-" + c.id,
                disabled: readonly,
                onchange: function () { update(v, "/checks/" + encodeURIComponent(c.id), { done: box.checked }); },
              });
              box.checked = c.done;
              return el("label", { class: "check" + (c.done ? " done" : ""), for: "chk-" + c.id }, box, el("span", { text: c.text }));
            })
          )
        )
      );
    }

    // --- 侧栏 ---
    var side = el("div", { class: "sticky" });
    if (opts.aside) side.append(opts.aside);
    side.append(materialSummary(v));
    side.append(sourcesPanel(v, reqById, stepById));

    return el("div", { class: "layout" }, main, el("div", null, side));
  }

  function nextCard(v, stepById, reqById) {
    var s = v.next_step ? stepById[v.next_step] : null;
    if (!s) {
      var pending = v.steps.filter(function (x) { return x.applies === "undecided"; }).length;
      var allDone = v.steps.every(function (x) { return x.applies === "no" || x.done; });
      return el(
        "section",
        { class: "next-card" + (allDone ? " done-all" : "") },
        el("div", { class: "label", text: allDone ? "全部完成" : "下一步" }),
        el("h2", { text: allDone ? "所有步骤都做完了。" : pending ? "先回答下面的问题" : "暂时没有能马上做的步骤" }),
        allDone ? el("p", { class: "muted", text: "别忘了最后核对一遍材料之间是否对得上。" }) : null
      );
    }
    var mats = s.requirements
      .map(function (rid) { return reqById[rid]; })
      .filter(function (r) { return r && r.state !== "not_applicable"; });
    return el(
      "section",
      { class: "next-card" },
      el("div", { class: "label", text: "下一步" }),
      el("h2", { text: s.title }),
      el("div", { class: "step-meta" }, stepMeta(s)),
      mats.length
        ? el("p", { class: "muted" }, "这一步涉及：", mats.map(function (r, i) { return el("span", null, i ? "、" : "", r.name + "（" + STATE_LABEL[r.state] + "）"); }))
        : null,
      el(
        "div",
        { class: "actions" },
        el("button", { class: "primary", type: "button", text: "✓ 这一步做完了", onclick: function () { update(v, "/steps/" + encodeURIComponent(s.id), { done: true }); } }),
        el("a", { href: "#step-" + s.id, text: "看详情", onclick: function (ev) { ev.preventDefault(); var t = document.getElementById("step-" + s.id); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); } })
      ),
      el("div", { class: "progress-wrap" }, progressBar(v.progress_ready, v.progress_total), el("small", { text: "材料 " + v.progress_ready + " / " + v.progress_total + " 已备齐" }))
    );
  }

  function stepMeta(s) {
    var bits = [];
    if (s.where) bits.push(el("span", { text: "📍 " + s.where }));
    if (s.estimate) bits.push(el("span", { text: "⏱ " + s.estimate }));
    if (s.duration_days) bits.push(el("span", { text: "⌛ 通常 " + s.duration_days.typical + " 天，最长 " + s.duration_days.max + " 天" }));
    return bits;
  }

  function stepItem(s, v, ctx) {
    var cls = "step" + (s.id === v.next_step ? " is-next" : "") + (s.done ? " is-done" : "") + (s.applies === "undecided" ? " is-undecided" : "");
    var tick = el("button", {
      type: "button",
      class: "tick",
      text: s.done ? "✓" : "",
      "aria-pressed": s.done ? "true" : "false",
      "aria-label": (s.done ? "取消完成：" : "标记完成：") + s.title,
      disabled: ctx.readonly || s.applies !== "yes",
      onclick: function () { update(v, "/steps/" + encodeURIComponent(s.id), { done: !s.done }); },
    });

    var blocked = null;
    if (s.applies === "undecided") {
      blocked = el("div", { class: "blocked", text: "取决于你的回答：" + conditionText(s.conditions, ctx.factsByKey) });
    } else if (!ctx.readonly && s.applies === "yes" && !s.done && !s.available) {
      var waiting = s.depends_on
        .map(function (d) { return ctx.stepById[d]; })
        .filter(function (d) { return d && d.applies !== "no" && !d.done; })
        .map(function (d) { return d.title; });
      if (waiting.length) blocked = el("div", { class: "blocked", text: "要先完成：" + waiting.join("、") });
    }

    var mats = s.requirements
      .map(function (rid) { return ctx.reqById[rid]; })
      .filter(function (r) { return r && r.state !== "not_applicable"; })
      .map(function (r) { return materialItem(r, v, ctx); });

    return el(
      "li",
      { class: cls, id: "step-" + s.id },
      el("div", null, tick),
      el(
        "div",
        null,
        el("div", { class: "step-title", text: s.title }),
        el("div", { class: "step-meta" }, stepMeta(s)),
        blocked,
        mats.length ? el("div", { class: "mats" }, mats) : null,
        evidenceBlock(s.evidence, v.sources)
      )
    );
  }

  function materialItem(r, v, ctx) {
    var id = ctx.anchored[r.id] ? null : "mat-" + r.id;
    ctx.anchored[r.id] = true;

    var records = null;
    if (r.records.length) {
      var desc = r.records
        .map(function (rec) { return rec.type + (rec.sublabel ? "（" + rec.sublabel + "）" : "") + (rec.obtained_date ? " · " + rec.obtained_date : ""); })
        .join(" + ");
      var action = null;
      if (!ctx.readonly && r.state !== "stale") {
        action = r.confirmed
          ? el("button", { type: "button", text: "取消确认", onclick: function () { update(v, "/matches/" + encodeURIComponent(r.id), { confirmed: false }); } })
          : el("button", { type: "button", text: "就用这份", onclick: function () { update(v, "/matches/" + encodeURIComponent(r.id), { confirmed: true }); } });
      }
      records = el("div", { class: "mat-records" }, el("span", null, (r.confirmed ? "已确认使用：" : "你材料库里有：") + desc), action);
    }

    var hints = [];
    if (r.state === "stale") {
      hints.push(el("div", { class: "mat-note", text: r.freshness_days ? "这份材料已经过期或超过 " + r.freshness_days + " 天，需要重新开一份。" : "这份材料已经过期，需要重新开一份。" }));
    }
    if (r.missing_parts.length) hints.push(el("div", { class: "mat-note", text: "还差：" + r.missing_parts.join("、") }));
    if (r.type_unresolved) hints.push(el("div", { class: "mat-note", text: "词表还不认识这个叫法，暂时没法自动对上你的材料。" }));
    if (r.state === "undecided") hints.push(el("div", { class: "mat-note", text: "取决于你的回答：" + conditionText(r.conditions, ctx.factsByKey) }));

    return el(
      "div",
      { class: "mat", id: id },
      el(
        "div",
        { class: "mat-top" },
        stateChip(r.state),
        el("span", { class: "mat-name", text: r.name }),
        r.raw_name && r.raw_name !== r.name ? el("span", { class: "mat-raw", text: "攻略写作「" + r.raw_name + "」" }) : null,
        KIND_LABEL[r.kind] ? el("span", { class: "badge" + (r.kind === "generate" ? " ai" : ""), text: KIND_LABEL[r.kind] }) : null,
        r.optional ? el("span", { class: "badge", text: "加分项" }) : null
      ),
      r.note ? el("div", { class: "mat-note", text: r.note }) : null,
      hints,
      records,
      evidenceBlock(r.evidence, v.sources)
    );
  }

  function materialSummary(v) {
    var relevant = v.requirements.filter(function (r) { return r.state !== "not_applicable" && r.state !== "undecided"; });
    var undecided = v.requirements.filter(function (r) { return r.state === "undecided"; }).length;
    var body = el("div", { class: "summary-list" });
    STATE_ORDER.forEach(function (state) {
      var group = relevant.filter(function (r) { return r.state === state; });
      if (!group.length) return;
      body.append(el("div", { class: "summary-group", text: STATE_LABEL[state] + " · " + group.length }));
      group.forEach(function (r) {
        body.append(
          el(
            "div",
            { class: "summary-row" },
            el("a", { href: "#mat-" + r.id, text: r.name, onclick: function (ev) { ev.preventDefault(); var t = document.getElementById("mat-" + r.id); if (t) t.scrollIntoView({ behavior: "smooth", block: "center" }); } }),
            r.optional ? el("span", { class: "badge", text: "加分项" }) : null
          )
        );
      });
    });
    if (undecided) body.append(el("p", { class: "muted", text: "另有 " + undecided + " 项取决于你对问题的回答。" }));
    if (!relevant.length && !undecided) body.append(el("p", { class: "muted", text: "没有需要准备的材料。" }));
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "材料一览" }), el("small", { text: v.progress_ready + " / " + v.progress_total + " 已备齐" })),
      body
    );
  }

  function sourcesPanel(v, reqById, stepById) {
    var stale = {};
    v.stale_sources.forEach(function (id) { stale[id] = true; });
    var items = v.sources.map(function (s) {
      var link = s.url && /^https?:\/\//.test(s.url) ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: s.title }) : el("span", { text: s.title });
      return el(
        "li",
        null,
        link,
        s.as_of ? el("small", { text: " · 信息截至 " + s.as_of }) : null,
        stale[s.id] ? el("div", { class: "blocked", text: "这份资料已超过一年，要求可能变了，请以官网为准。" }) : null
      );
    });
    var uncertain = v.uncertain.map(function (path) {
      var id = path.split(".")[0];
      var target = reqById[id] ? reqById[id].name : stepById[id] ? stepById[id].title : id;
      return el("li", { text: target });
    });
    var conflicts = v.conflicts.map(function (k) {
      return el("li", null, k.about + "：", k.claims.map(function (c, i) { return el("span", null, i ? " / " : "", "“" + c.quote + "”"); }));
    });
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "来源与提醒" })),
      el(
        "div",
        { class: "sources" },
        el("ul", null, items),
        conflicts.length ? [el("strong", { text: "资料之间说法不一：" }), el("ul", null, conflicts)] : null,
        uncertain.length ? [el("strong", { text: "整理者没把握、建议你核实：" }), el("ul", null, uncertain)] : null,
        el("p", { class: "muted", text: "攻略是经验总结，所有要求最终以官网为准。" })
      )
    );
  }

  document.getElementById("today").textContent = "今天 " + todayIso();
  window.addEventListener("hashchange", function () {
    // 页内锚点（#step-xxx、#mat-xxx）只是滚动，不切换视图
    if (/^#(step|mat)-/.test(location.hash)) return;
    route();
  });
  route();
})();
