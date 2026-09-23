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

  function uploadRequest(path, formData) {
    return fetch(path, { method: "POST", body: formData, headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) {
          var detail = data && data.detail;
          throw new Error(typeof detail === "string" ? detail : "上传失败（HTTP " + res.status + "）");
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

  // "2026-10-17" -> "10月17日"（倒排时间的界面展示格式，见 specs/002-guide-to-track/tasks-parallel-1.md 任务 D）
  function fmtMD(iso) {
    var parts = iso.split("-");
    return parseInt(parts[1], 10) + "月" + parseInt(parts[2], 10) + "日";
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
      a.classList.toggle("active", ["", "guide", "track", "tag", "form"].indexOf(parts[0]) !== -1);
    });
    setView(el("p", { class: "muted", text: "加载中…" }));
    if (parts[0] === "guide" && parts[1]) return renderGuide(decodeURIComponent(parts[1]));
    if (parts[0] === "track" && parts[1]) return renderTrack(decodeURIComponent(parts[1]));
    if (parts[0] === "tag" && parts[1]) return renderHome(decodeURIComponent(parts[1]));
    if (parts[0] === "form" && parts[1]) return renderForm(decodeURIComponent(parts[1]));
    return renderHome(null);
  }

  // ---------- 首页：我正在办的 + 攻略库 ----------

  function renderHome(tag) {
    Promise.all([request("GET", "/api/tracks"), request("GET", "/api/guides")])
      .then(function (results) {
        var allTracks = results[0];
        var allGuides = results[1];
        var guideTitle = {};
        allGuides.forEach(function (g) { guideTitle[g.id] = g.title; });

        // 标签 = 攻略的分类（签证 / 工作 / 社保 / 银行补贴 / 其他）；办事跟着它所照着的攻略走
        var counts = {};
        allGuides.forEach(function (g) { if (g.category) counts[g.category] = (counts[g.category] || 0) + 1; });
        allTracks.forEach(function (t) { if (t.category) counts[t.category] = (counts[t.category] || 0) + 1; });
        var match = function (cat) { return !tag || cat === tag; };
        var tracks = allTracks.filter(function (t) { return match(t.category); });
        var guides = allGuides.filter(function (g) { return match(g.category); });
        var active = tracks.filter(function (t) { return !t.completed; });
        var done = tracks.filter(function (t) { return t.completed; });

        var chips = el(
          "nav",
          { class: "chips", "aria-label": "按标签筛选" },
          el("a", { class: "chip", href: "#/", "aria-current": tag ? "false" : "true" }, "全部", el("span", { class: "n", text: allGuides.length + allTracks.length })),
          Object.keys(counts).map(function (cat) {
            return el("a", { class: "chip", href: "#/tag/" + encodeURIComponent(cat), "aria-current": cat === tag ? "true" : "false" }, cat, el("span", { class: "n", text: counts[cat] }));
          })
        );

        var activeCards = active.map(function (t) {
          var foot = [el("span", { text: "已进行 " + (t.elapsed_days || 0) + " 天" })];
          if (t.deadline) {
            var left = daysBetween(todayIso(), t.deadline);
            foot.push(el("span", { class: left <= 14 ? "urgent" : null, text: left >= 0 ? "距截止 " + left + " 天" : "已过截止 " + -left + " 天" }));
          }
          return el(
            "a",
            { class: "card", href: "#/track/" + encodeURIComponent(t.id) },
            el("span", { class: "meta" }, t.category ? el("span", { class: "tag", text: t.category }) : null, " 照着：" + (guideTitle[t.guide_id] || t.guide_id)),
            el("h3", { text: t.title }),
            t.error
              ? el("p", { class: "meta", text: "暂时打不开：" + t.error })
              : [
                  progressBar(t.progress_ready, t.progress_total),
                  el("span", { class: "meta", text: "材料 " + t.progress_ready + " / " + t.progress_total + " 已备齐" }),
                  el("div", { class: "next", text: t.next_step_title ? "下一步：" + t.next_step_title : "没有可以马上做的步骤" }),
                ],
            el("div", { class: "card-foot" }, foot)
          );
        });

        var doneSection = null;
        if (done.length) {
          var days = done.map(function (t) { return t.elapsed_days; }).filter(function (d) { return d !== null && d !== undefined; });
          var avg = days.length ? Math.round(days.reduce(function (a, b) { return a + b; }, 0) / days.length) : null;
          doneSection = el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "已办完", el("span", { class: "count", text: done.length }))),
            days.length
              ? el(
                  "div",
                  { class: "stats" },
                  el("div", { class: "stat" }, el("b", { text: avg + " 天" }), el("span", { text: "平均用时" })),
                  el("div", { class: "stat" }, el("b", { text: Math.min.apply(null, days) + " 天" }), el("span", { text: "最快" })),
                  el("div", { class: "stat" }, el("b", { text: Math.max.apply(null, days) + " 天" }), el("span", { text: "最慢" }))
                )
              : null,
            el(
              "div",
              { class: "cards" },
              done.map(function (t) {
                return el(
                  "a",
                  { class: "card done", href: "#/track/" + encodeURIComponent(t.id) },
                  el("span", { class: "meta" }, t.category ? el("span", { class: "tag", text: t.category }) : null, " 照着：" + (guideTitle[t.guide_id] || t.guide_id)),
                  el("h3", { text: t.title }),
                  el("div", { class: "took", text: "用时 " + t.elapsed_days + " 天" }),
                  el("div", { class: "card-foot" }, el("span", { text: t.created + " → " + t.completed }))
                );
              })
            )
          );
        }

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

        setView(
          el(
            "div",
            { class: "heading" },
            el("div", null, el("h1", { text: "照着攻略，一件件办好。" }), el("p", { class: "muted", text: "攻略由大家共同维护；你的进度只保存在这台电脑上。" }))
          ),
          chips,
          el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "办理中", el("span", { class: "count", text: active.length }))),
            activeCards.length
              ? el("div", { class: "cards" }, activeCards)
              : el("p", { class: "empty", text: tag ? "这个标签下没有正在办的事。" : "还没有。从下面的攻略库里挑一份，点进去开始办。" })
          ),
          doneSection,
          el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "攻略库", el("span", { class: "count", text: guides.length })), el("small", { text: "community/guides/" })),
            guideCards.length ? el("div", { class: "cards" }, guideCards) : el("p", { class: "empty", text: tag ? "这个标签下还没有攻略，欢迎贡献一份。" : "攻略库是空的。" })
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
        setView();
        showError(e.message);
      });
  }

  // ---------- 填表指南 ----------

  function renderForm(id) {
    request("GET", "/api/forms/" + encodeURIComponent(id))
      .then(function (f) {
        setView(
          el(
            "div",
            { class: "heading" },
            el(
              "div",
              null,
              el("div", { class: "crumb" }, el("a", { href: "#", text: "← 返回", onclick: function (ev) { ev.preventDefault(); history.back(); } }), " / 填表指南"),
              el("h1", { text: f.title }),
              f.summary ? el("p", { class: "muted", text: f.summary }) : null
            ),
            el("a", { class: "link-btn official big", href: f.site.url, target: "_blank", rel: "noopener noreferrer", text: "🌐 打开 " + f.site.name + " ↗" })
          ),
          f.level === "procedure"
            ? el("p", { class: "notice", text: "这是流程级指南：按环节列出要做什么、注意什么。每一栏具体怎么填的字段级说明，还需要有人带着 Agent 实际走一遍官网后补充。" })
            : null,
          el(
            "ol",
            { class: "form-sections" },
            f.sections.map(function (sec) {
              return el(
                "li",
                { class: "panel" },
                el("div", { class: "panel-head" }, el("h2", { text: sec.title })),
                el(
                  "div",
                  { class: "form-body" },
                  el("ol", null, sec.items.map(function (t) { return el("li", { text: t }); })),
                  sec.tips.length ? el("div", { class: "tips" }, el("strong", { text: "注意" }), el("ul", null, sec.tips.map(function (t) { return el("li", { text: t }); }))) : null,
                  evidenceBlock(sec.evidence, f.sources)
                )
              );
            })
          ),
          el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", { text: "来源" })),
            el(
              "div",
              { class: "sources" },
              el("ul", null, f.sources.map(function (src) {
                return el("li", null, src.url ? el("a", { href: src.url, target: "_blank", rel: "noopener noreferrer", text: src.title }) : src.title, src.as_of ? el("small", { text: " · 信息截至 " + src.as_of }) : null);
              })),
              f.uncertain.length ? [el("strong", { text: "还不确定、建议核实：" }), el("ul", null, f.uncertain.map(function (u) { return el("li", { text: u }); }))] : null,
              el("p", { class: "muted", text: "以官网实际页面为准。" })
            )
          )
        );
      })
      .catch(function (e) {
        setView(el("p", null, el("a", { href: "#/", text: "← 回到攻略库" })));
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
          setView(
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

        setView(
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
        setView();
        showError(e.message);
      });
  }

  // ---------- 我的办事 ----------

  var myRecords = []; // 我的资料里的真实材料（不含示例），"从我的资料里选"用

  function loadMyRecords() {
    return request("GET", "/api/materials").then(function (list) {
      myRecords = list.filter(function (m) { return m.id.indexOf("example-") !== 0; });
    });
  }

  function renderTrack(id) {
    Promise.all([request("GET", "/api/tracks/" + encodeURIComponent(id)), loadMyRecords()])
      .then(function (results) { drawTrack(results[0]); })
      .catch(function (e) {
        setView(el("p", null, el("a", { href: "#/", text: "← 回到攻略库" })));
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
        el(
          "p",
          { class: "muted" },
          v.completed ? "已办完 · 用时 " + v.elapsed_days + " 天" : "创建于 " + v.created + " · 已进行 " + v.elapsed_days + " 天",
          v.deadline && !v.completed ? " · 截止 " + v.deadline + "（" + deadlineText(v.deadline) + "）" : ""
        )
      ),
      v.completed ? null : deadlineEditor(v)
    );
    // 重新渲染会替换整块内容，先记住滚动位置，避免每点一次就跳回顶部
    var y = window.scrollY;
    setView(head, trackBody(v, { readonly: false }));
    window.scrollTo(0, y);
  }

  // 办事页标题区：设置/修改/清除截止日期，用于倒排时间（PUT /api/tracks/{id}/deadline）
  function deadlineEditor(v) {
    var input = el("input", { type: "date", name: "deadline", value: v.deadline || null });
    return el(
      "form",
      {
        class: "deadline-edit",
        onsubmit: function (ev) {
          ev.preventDefault();
          update(v, "/deadline", { deadline: input.value || null });
        },
      },
      el("label", null, "截止日期", input),
      el("button", { type: "submit", text: v.deadline ? "修改" : "设置" }),
      v.deadline
        ? el("button", { type: "button", text: "清除", onclick: function () { update(v, "/deadline", { deadline: null }); } })
        : null
    );
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
          (function () {
            var phaseById = {};
            v.phases.forEach(function (p, i) { phaseById[p.id] = { p: p, i: i }; });
            var items = [];
            var lastPhase = null;
            visibleSteps.forEach(function (s) {
              if (s.phase && s.phase !== lastPhase && phaseById[s.phase]) {
                var ph = phaseById[s.phase];
                items.push(el(
                  "li",
                  { class: "phase-heading", id: "phase-" + ph.p.id },
                  el("span", { text: "第 " + (ph.i + 1) + " 阶段 · " + ph.p.title }),
                  MODE_LABEL[ph.p.mode] ? el("span", { class: "mode " + ph.p.mode, text: MODE_LABEL[ph.p.mode] }) : null
                ));
                lastPhase = s.phase;
              }
              items.push(stepItem(s, v, { readonly: readonly, reqById: reqById, stepById: stepById, factsByKey: factsByKey, anchored: anchored }));
            });
            return items;
          })()
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

    if (!readonly) side.append(exportPanel(v));

    return el("div", null, phaseBar(v, stepById), el("div", { class: "layout" }, main, el("div", null, side)));
  }

  var MODE_LABEL = { online: "线上", offline: "线下" };
  var PHASE_STATE_LABEL = { done: "已完成", current: "进行中", upcoming: "未开始", skipped: "不需要" };

  function durationText(d) {
    return d ? "通常 " + d.typical + " 天，最长 " + d.max + " 天" : null;
  }

  var phaseObserver = null;

  function jumpTo(id) {
    var target = document.getElementById(id);
    if (!target) return;
    // 用户开了"减少动态效果"、或页面不在前台（浏览器会暂停平滑滚动）时，直接跳过去
    var reduce = (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || document.visibilityState !== "visible";
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  // 页面最上方的"大阶段"进度条：先让人知道整件事分几段、现在走到哪、一般要多久。
  // 每一段都可以点，跳到下面这一段的步骤和材料；往下滑之后，顶部会吸住一条精简版，随时能跳。
  function phaseBar(v) {
    if (phaseObserver) { phaseObserver.disconnect(); phaseObserver = null; }
    if (!v.phases.length) {
      return v.timeline ? el("p", { class: "notice", text: "⏱ " + v.timeline }) : null;
    }
    var bar = el(
      "ol",
      { class: "phase-bar" },
      v.phases.map(function (p, i) {
        var meta = [
          el("span", { text: PHASE_STATE_LABEL[p.state] }),
          p.steps_total ? el("span", { text: "· " + p.steps_done + "/" + p.steps_total + " 步" }) : null,
          MODE_LABEL[p.mode] ? el("span", { class: "mode " + p.mode, text: MODE_LABEL[p.mode] }) : null,
        ];
        var time = p.estimate || durationText(p.duration_days);
        return el(
          "li",
          { "aria-current": p.state === "current" ? "step" : null },
          el(
            "button",
            {
              type: "button",
              class: "phase " + p.state,
              disabled: p.state === "skipped",
              "aria-label": "第 " + (i + 1) + " 阶段：" + p.title + "，" + PHASE_STATE_LABEL[p.state] + "，跳到这一阶段的步骤",
              onclick: function () { jumpTo("phase-" + p.id); },
            },
            el("div", { class: "phase-no", text: "第 " + (i + 1) + " 阶段" }),
            el("div", { class: "phase-title", text: p.title }),
            el("div", { class: "phase-meta" }, meta),
            time ? el("div", { class: "phase-meta", text: "⏱ " + time }) : null,
            p.latest_finish ? el("div", { class: "phase-meta", text: "🕐 最晚 " + fmtMD(p.latest_finish) + " 完成" }) : null,
            p.summary ? el("div", { class: "phase-summary", text: p.summary }) : null,
            p.state === "skipped" ? null : el("div", { class: "phase-go", text: "看这一阶段 ↓" })
          )
        );
      })
    );

    var nextStep = v.steps.filter(function (x) { return x.id === v.next_step; })[0];
    var strip = el(
      "nav",
      { class: "phase-strip", "aria-label": "阶段快捷跳转" },
      v.phases.map(function (p, i) {
        return el("button", {
          type: "button",
          class: p.state,
          disabled: p.state === "skipped",
          text: (p.state === "done" ? "✓ " : (i + 1) + " ") + p.title,
          onclick: function () { jumpTo("phase-" + p.id); },
        });
      }),
      nextStep
        ? el("a", { class: "strip-next", href: "#step-" + nextStep.id, text: "下一步：" + nextStep.title, onclick: function (ev) { ev.preventDefault(); jumpTo("step-" + nextStep.id); } })
        : null
    );

    // 大进度条滑出屏幕时才显示精简条，避免两条同时出现
    if ("IntersectionObserver" in window) {
      phaseObserver = new IntersectionObserver(function (entries) {
        strip.classList.toggle("visible", !entries[0].isIntersecting);
      });
      phaseObserver.observe(bar);
    } else {
      strip.classList.add("visible");
    }

    return el(
      "div",
      null,
      strip,
      el(
        "section",
        { class: "phases", "aria-label": "办理阶段" },
        bar,
        v.timeline ? el("p", { class: "timeline-note", text: "⏱ 全程：" + v.timeline }) : null
      )
    );
  }

  function exportPanel(v) {
    var out = el("div");
    var input = el("input", { type: "text", value: v.export_dir || "", placeholder: "例如 ~/Desktop（留空 = 材料根目录下的 exports/）", "aria-label": "导出到哪个文件夹" });
    var chips = el("div", { class: "chips small" });
    request("GET", "/api/export-locations").then(function (locs) {
      locs.forEach(function (loc) {
        chips.append(el("button", { type: "button", class: "chip", text: loc.label, onclick: function () { input.value = loc.path; } }));
      });
    }).catch(function () { /* 快捷选项拿不到不影响手动填写 */ });
    var sample = v.export_pattern.replace("{seq:02d}", "01").replace("{seq}", "1").replace("{name}", "01-护照复印件").replace("{part}", "");
    var btn = el("button", {
      type: "button",
      class: "primary",
      text: "导出已确认的材料",
      onclick: function () {
        btn.disabled = true;
        showError("");
        var dest = input.value.trim();
        request("POST", "/api/tracks/" + encodeURIComponent(v.id) + "/export", dest ? { dest: dest } : {})
          .then(function (r) {
            // 经过 el() 包一层：它会展开数组、跳过空值，原生 replaceChildren 不会
            out.replaceChildren(el(
              "div",
              null,
              el("p", null, "已复制 " + r.copied.length + " 个文件到："),
              el("code", { text: r.folder }),
              r.copied.length ? el("ul", { class: "file-list" }, r.copied.map(function (m) { return el("li", { text: m }); })) : null,
              r.missing_files.length ? [el("p", { text: "已确认但找不到文件：" }), el("ul", null, r.missing_files.map(function (m) { return el("li", { text: m }); }))] : null,
              r.pending.length
                ? [el("p", { text: "还没备齐（已写进文件夹里的 清单.txt）：" }), el("ul", null, r.pending.map(function (m) { return el("li", { text: m }); }))]
                : el("p", { text: "材料全部备齐了。" })
            ));
          })
          .catch(function (e) { showError(e.message); })
          .then(function () { btn.disabled = false; });
      },
    });
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "导出到文件夹" })),
      el(
        "div",
        { class: "export" },
        el("p", { class: "muted", text: "把状态为「已有」的材料复制到你选的文件夹里（会新建一个以这件事命名的子文件夹），附一份清单。原文件留在材料库里，不移动、不改名。" }),
        el("label", null, "导出到", input),
        chips,
        el("p", { class: "muted", text: "文件名按攻略里的规则生成，例如「" + sample + ".pdf」。" }),
        btn,
        out
      )
    );
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
        allDone ? el("p", { class: "muted", text: (v.completed ? "用时 " + v.elapsed_days + " 天（" + v.created + " → " + v.completed + "）。" : "") + "别忘了最后核对一遍材料之间是否对得上。" }) : null
      );
    }
    var mats = s.requirements
      .map(function (rid) { return reqById[rid]; })
      .filter(function (r) { return r && r.state !== "not_applicable"; });
    return el(
      "section",
      { class: "next-card" + (s.late ? " late" : "") },
      el("div", { class: "label", text: "下一步" + phaseLabel(v, s.phase) }),
      el("h2", { text: s.title }),
      el("div", { class: "step-meta" }, stepMeta(s)),
      linksBlock(s, factsFromView(v)),
      s.late
        ? el("p", { class: "late-alert", text: "⚠ 已经超过建议的最晚开始时间，尽快推进这一步" })
        : null,
      mats.length
        ? el("p", { class: "muted" }, "这一步涉及：", mats.map(function (r, i) { return el("span", null, i ? "、" : "", r.name + "（" + STATE_LABEL[r.state] + "）"); }))
        : null,
      el(
        "div",
        { class: "actions" },
        el("button", { class: "primary", type: "button", text: "✓ 这一步做完了", onclick: function () { update(v, "/steps/" + encodeURIComponent(s.id), { done: true }); } }),
        el("a", { href: "#step-" + s.id, text: "看详情", onclick: function (ev) { ev.preventDefault(); jumpTo("step-" + s.id); } })
      ),
      el("div", { class: "progress-wrap" }, progressBar(v.progress_ready, v.progress_total), el("small", { text: "材料 " + v.progress_ready + " / " + v.progress_total + " 已备齐" }))
    );
  }

  function phaseLabel(v, phaseId) {
    for (var i = 0; i < v.phases.length; i++) {
      if (v.phases[i].id === phaseId) return " · 第 " + (i + 1) + " 阶段：" + v.phases[i].title;
    }
    return "";
  }

  function factsFromView(v) {
    var map = {};
    v.facts.forEach(function (f) { map[f.key] = f; });
    return map;
  }

  var LINK_ICON = { official: "🌐", form_guide: "📋", info: "🔗" };

  // 已适用的链接直接显示成按钮；取决于还没回答的问题的，只提示"先回答哪个问题"，不把十几个国家的官网全堆出来
  function linksBlock(s, factsByKey) {
    if (!s.links || !s.links.length) return null;
    var ready = s.links.filter(function (l) { return l.applies === "yes"; });
    var pendingFacts = {};
    s.links.filter(function (l) { return l.applies === "undecided"; }).forEach(function (l) {
      l.conditions.forEach(function (c) { pendingFacts[c.fact] = true; });
    });
    var hint = Object.keys(pendingFacts).length
      ? el("span", { class: "muted", text: "回答「" + Object.keys(pendingFacts).map(function (k) { return factsByKey[k] ? factsByKey[k].question.replace(/[（(].*$/, "").replace(/[？?]$/, "") : k; }).join("」「") + "」后，这里会出现对应的官网和填表指南" })
      : null;
    return el(
      "div",
      { class: "links" },
      ready.map(function (l) {
        var internal = l.kind === "form_guide" && l.form;
        return el("a", {
          class: "link-btn " + l.kind,
          href: internal ? "#/form/" + encodeURIComponent(l.form) : l.url,
          target: internal ? null : "_blank",
          rel: internal ? null : "noopener noreferrer",
          text: (LINK_ICON[l.kind] || "🔗") + " " + l.title + (internal ? "" : " ↗"),
        });
      }),
      hint
    );
  }

  function stepMeta(s) {
    var bits = [];
    if (s.where) bits.push(el("span", { text: "📍 " + s.where }));
    if (s.estimate) bits.push(el("span", { text: "⏱ " + s.estimate }));
    if (s.duration_days) bits.push(el("span", { text: "⌛ 通常 " + s.duration_days.typical + " 天，最长 " + s.duration_days.max + " 天" }));
    if (s.latest_start) {
      var text = "最晚 " + fmtMD(s.latest_start) + " 开始";
      if (s.late) text += "，已经晚了 " + daysBetween(s.latest_start, todayIso()) + " 天";
      bits.push(el("span", { class: s.late ? "late" : null, text: (s.late ? "⚠ " : "🕐 ") + text }));
    }
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
        linksBlock(s, ctx.factsByKey),
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
    if (r.missing_parts.length) hints.push(el("div", { class: "mat-note", text: "还差：" + r.missing_parts.map(function (p) { return p.name; }).join("、") }));
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
      !ctx.readonly && (r.state === "missing" || r.state === "stale") && !r.type_unresolved ? uploadForm(r, v) : null,
      !ctx.readonly && r.state !== "undecided" ? pickForm(r, v) : null,
      evidenceBlock(r.evidence, v.sources)
    );
  }

  var CATEGORY_NAME = { passport_scan: "证件", financial_snapshot: "财务", employment_doc: "工作", id_photo: "证件照", other: "其他" };

  function recordLabel(m) {
    return m.type + (m.sublabel ? "（" + m.sublabel + "）" : "") + " · " + (m.obtained_date || "未填日期");
  }

  // 自动识别没认出来时（例如签证页和盖章页扫在同一份 PDF 里），让用户自己从材料库里挑。
  // 组合材料每一部分各挑一份；挑过的类型会被记住，下次自动识别。
  function pickForm(r, v) {
    if (!myRecords.length) return null;
    var slots = r.parts.length ? r.parts : [{ key: r.material_type, name: r.name }];
    var toggleText = r.state === "ready" ? "换一份" : "从我的资料里选";
    var box = el("form", { class: "pick", hidden: true });
    var groups = {};
    myRecords.forEach(function (m) { (groups[m.category] = groups[m.category] || []).push(m); });
    var selects = slots.map(function (slot, i) {
      var current = r.records.length === slots.length ? r.records[i].id : "";
      var sel = el(
        "select",
        { required: true, "aria-label": "选择：" + slot.name },
        el("option", { value: "", text: "— 选一份 —" }),
        Object.keys(groups).map(function (cat) {
          return el("optgroup", { label: CATEGORY_NAME[cat] || cat }, groups[cat].map(function (m) {
            return el("option", { value: m.id, text: recordLabel(m), selected: m.id === current });
          }));
        })
      );
      return el("label", null, slots.length > 1 ? slot.name + " " : "", sel);
    });
    var submit = el("button", { type: "submit", text: "就用这些" });
    [selects, submit, el("small", { class: "muted", text: "选过的材料以后会被自动识别" })].forEach(function (n) {
      (Array.isArray(n) ? n : [n]).forEach(function (c) { box.append(c); });
    });
    box.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var ids = selects.map(function (label) { return label.querySelector("select").value; });
      if (ids.some(function (x) { return !x; })) return;
      submit.disabled = true;
      update(v, "/matches/" + encodeURIComponent(r.id), { confirmed: true, records: ids });
    });
    var toggle = el("button", {
      type: "button",
      class: "linkish",
      text: toggleText,
      "aria-expanded": "false",
      onclick: function () {
        box.hidden = !box.hidden;
        toggle.setAttribute("aria-expanded", box.hidden ? "false" : "true");
      },
    });
    return el("div", { class: "pick-wrap" }, toggle, box);
  }

  function uploadForm(r, v) {
    var form = el("form", { class: "upload" });
    var partChoices = r.missing_parts.length ? r.missing_parts : r.parts;
    var select = null;
    if (partChoices.length) {
      select = el("select", { name: "part", "aria-label": "上传的是哪一部分" }, partChoices.map(function (p) { return el("option", { value: p.key, text: p.name }); }));
    }
    var fileInput = el("input", { type: "file", name: "file", required: true, "aria-label": "选择文件：" + r.name });
    var dateInput = el("input", { type: "date", name: "obtained_date", title: "开具/取得日期，不填默认今天" });
    var btn = el("button", { type: "submit", text: r.state === "stale" ? "上传新的一份" : "上传" });
    // 原生 append 会把 null 当成文字 "null" 插进去，所以先过滤掉不需要的控件
    [el("span", { text: r.state === "stale" ? "重新开好了？" : "手上有了？" }), select, fileInput, el("label", null, "取得日期 ", dateInput), btn]
      .filter(Boolean)
      .forEach(function (node) { form.append(node); });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (!fileInput.files.length) return;
      var fd = new FormData();
      fd.set("file", fileInput.files[0]);
      if (dateInput.value) fd.set("obtained_date", dateInput.value);
      if (select) fd.set("part", select.value);
      btn.disabled = true;
      showError("");
      uploadRequest("/api/tracks/" + encodeURIComponent(v.id) + "/requirements/" + encodeURIComponent(r.id) + "/upload", fd)
        .then(function (nv) { return loadMyRecords().then(function () { drawTrack(nv); }); })
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return form;
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
