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
    optional: "可选",
  };
  var STATE_ORDER = ["missing", "stale", "unconfirmed", "ready", "optional"];
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

  // 时间窗的日期可能在一两年后，今年内只显示"M月D日"，否则带上年份
  function fmtDate(iso) {
    return iso.slice(0, 4) === todayIso().slice(0, 4) ? fmtMD(iso) : iso.slice(0, 4) + "年" + fmtMD(iso);
  }

  // 步骤的可办时间窗（spec §3c）：还没到时间 / 可以办了 / 只剩 N 天 / 已错过 / 先回答问题
  function windowLine(s, factsByKey, stepById) {
    var w = s.window;
    if (!w) return null;
    var until = w.closes ? "截止 " + fmtDate(w.closes) : "";
    var text;
    if (w.state === "waiting") {
      var names = w.waiting_for.map(function (k) {
        if (factsByKey[k]) return "回答「" + factsByKey[k].question.replace(/[（(].*$/, "").replace(/[？?]$/, "") + "」";
        return "完成「" + (stepById[k] ? stepById[k].title : k) + "」";
      });
      text = "🗓 " + names.join("、") + "后，这里会算出什么时候可以办";
    } else if (w.state === "upcoming") {
      text = "🗓 " + fmtDate(w.opens) + " 起可以办（还有 " + w.days + " 天）" + (until ? " · " + until : "");
    } else if (w.state === "closing") {
      text = "⏰ " + (w.days === 0 ? "今天是最后一天" : "只剩 " + w.days + " 天") + " · " + until;
    } else if (w.state === "missed") {
      text = "已错过：" + until.replace("截止 ", "截止于 ");
    } else {
      text = "🗓 现在可以办" + (until ? " · " + until + "（还有 " + w.days + " 天）" : "");
    }
    return el("div", { class: "window " + w.state, text: text });
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

  // 加分项没有时不算"缺"：它不计入进度、导出时也不算没备齐，所以显示成灰色的"可选"，别吓人
  function displayState(r) {
    return r.optional && r.state === "missing" ? "optional" : r.state;
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
      a.classList.toggle("active", ["", "guide", "track", "tag", "form", "new", "draft"].indexOf(parts[0]) !== -1);
    });
    if (workspaceChat) { workspaceChat.destroy(); workspaceChat = null; }
    setView(el("p", { class: "muted", text: "加载中…" }));
    if (parts[0] === "new" && parts[1]) return renderNewWorkspace(decodeURIComponent(parts[1]), parts[2] ? decodeURIComponent(parts[2]) : null);
    if (parts[0] === "new") return renderNewType();
    if (parts[0] === "draft" && parts[1] && parts[2]) return renderDraft(decodeURIComponent(parts[1]), decodeURIComponent(parts[2]));
    if (parts[0] === "guide" && parts[1]) return renderGuide(decodeURIComponent(parts[1]));
    if (parts[0] === "track" && parts[1]) return renderTrack(decodeURIComponent(parts[1]));
    if (parts[0] === "tag" && parts[1]) return renderHome(decodeURIComponent(parts[1]));
    if (parts[0] === "form" && parts[1]) return renderForm(decodeURIComponent(parts[1]));
    return renderHome(null);
  }

  // ---------- 首页：我正在办的 + 攻略库 ----------
  //
  // 两块各筛各的：「办理中」按分类筛（只有办的事分属两类以上才出现筛选）；
  // 「攻略库」是一个库，有自己的搜索框和标签（分类 + 攻略里写的 tags），以后攻略多了也好找。
  // 筛选状态只存在页面内存里；旧链接 #/tag/<分类> 仍然能用，打开后等于在攻略库里选了这个标签。
  var homeState = { trackCat: null, guideTag: null, query: "" };

  function guideMatches(g, tag, query) {
    if (tag && g.category !== tag && (g.tags || []).indexOf(tag) === -1) return false;
    if (!query) return true;
    var hay = [g.title, g.summary, g.category, g.id].concat(g.tags || []).join(" ").toLowerCase();
    return query.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) !== -1; });
  }

  // 卡片上的"照着：<攻略名>"：名字和标题一样时就是重复信息，不显示
  function followsText(t, guideTitle) {
    var g = guideTitle[t.guide_id] || t.guide_id;
    return g === t.title ? null : " 照着：" + g;
  }

  function renderHome(tag) {
    if (tag) homeState.guideTag = tag;
    Promise.all([request("GET", "/api/tracks"), request("GET", "/api/guides")])
      .then(function (results) {
        var allTracks = results[0];
        var allGuides = results[1];
        var guideTitle = {};
        allGuides.forEach(function (g) { guideTitle[g.id] = g.title; });

        var trackCats = {};
        allTracks.forEach(function (t) { if (t.category) trackCats[t.category] = (trackCats[t.category] || 0) + 1; });
        if (homeState.trackCat && !trackCats[homeState.trackCat]) homeState.trackCat = null;
        var tracks = allTracks.filter(function (t) { return !homeState.trackCat || t.category === homeState.trackCat; });
        var active = tracks.filter(function (t) { return !t.completed; });
        var done = tracks.filter(function (t) { return t.completed; });

        var trackChips = Object.keys(trackCats).length > 1
          ? el(
              "div",
              { class: "chips small", role: "group", "aria-label": "按分类筛选我的办事" },
              [null].concat(Object.keys(trackCats)).map(function (cat) {
                return el("button", {
                  type: "button", class: "chip", "aria-pressed": homeState.trackCat === cat ? "true" : "false",
                  text: cat === null ? "全部" : cat + " " + trackCats[cat],
                  onclick: function () { homeState.trackCat = cat; renderHome(null); },
                });
              })
            )
          : null;

        var activeCards = active.map(function (t) {
          var foot = [el("span", { text: "已进行 " + (t.elapsed_days || 0) + " 天" })];
          if (t.next_reminder && t.next_step_title) foot.push(el("span", { text: "🗓 " + reminderText(t.next_reminder) }));
          if (t.deadline) {
            var left = daysBetween(todayIso(), t.deadline);
            foot.push(el("span", { class: left <= 14 ? "urgent" : null, text: left >= 0 ? "距截止 " + left + " 天" : "已过截止 " + -left + " 天" }));
          }
          return el(
            "a",
            { class: "card", href: "#/track/" + encodeURIComponent(t.id) },
            el("span", { class: "meta" }, t.category ? el("span", { class: "tag", text: t.category }) : null, followsText(t, guideTitle)),
            el("h3", { text: t.title }),
            t.error
              ? el("p", { class: "meta", text: "暂时打不开：" + t.error })
              : [
                  t.progress_total ? progressBar(t.progress_ready, t.progress_total) : null,
                  t.progress_total ? el("span", { class: "meta", text: "材料 " + t.progress_ready + " / " + t.progress_total + " 已备齐" }) : null,
                  el("div", { class: "next", text: t.next_step_title ? "下一步：" + t.next_step_title : t.next_reminder ? "下一件事：" + reminderText(t.next_reminder) : "没有可以马上做的步骤" }),
                ],
            el("div", { class: "card-foot" }, foot)
          );
        });

        var doneSection = null;
        if (done.length) {
          var days = done.map(function (t) { return t.elapsed_days; }).filter(function (d) { return d !== null && d !== undefined; });
          var avg = days.length ? Math.round(days.reduce(function (a, b) { return a + b; }, 0) / days.length) : null;
          // 已办完的默认收起，点标题展开
          doneSection = el(
            "details",
            { class: "panel done-panel" },
            el("summary", { class: "panel-head" }, el("h2", null, "已办完", el("span", { class: "count", text: done.length }))),
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
                  el("span", { class: "meta" }, t.category ? el("span", { class: "tag", text: t.category }) : null, followsText(t, guideTitle)),
                  el("h3", { text: t.title }),
                  el("div", { class: "took", text: "用时 " + t.elapsed_days + " 天" }),
                  el("div", { class: "card-foot" }, el("span", { text: t.created + " → " + t.completed }))
                );
              })
            )
          );
        }

        function guideCard(g) {
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
            // 卡片上最多 3 个标签（分类 + 攻略里写的前两个），简介最多两行（CSS 截断），不写更新日期
            el("span", { class: "meta" }, el("span", { class: "tag", text: g.category }), (g.tags || []).slice(0, 2).map(function (t) { return el("span", { class: "tag soft", text: t }); })),
            el("h3", { text: g.title }),
            g.summary ? el("p", { class: "meta clamp2", text: g.summary }) : null,
            el("div", { class: "next", text: g.step_count + " 个步骤 · " + g.requirement_count + " 项材料" })
          );
        }

        // 攻略库的标签：先分类，再按出现次数排的 tags
        var tagCounts = {};
        allGuides.forEach(function (g) {
          [g.category].concat(g.tags || []).forEach(function (t) { if (t) tagCounts[t] = (tagCounts[t] || 0) + 1; });
        });
        var cats = [];
        allGuides.forEach(function (g) { if (g.category && cats.indexOf(g.category) === -1) cats.push(g.category); });
        // 筛选条只放分类 + 最常用的 6 个标签（其余在搜索框里输入照样能搜到）；当前选中的标签总是显示
        var otherTags = Object.keys(tagCounts).filter(function (t) { return cats.indexOf(t) === -1; })
          .sort(function (x, y) { return tagCounts[y] - tagCounts[x] || x.localeCompare(y, "zh"); })
          .filter(function (t, i) { return i < 6 || t === homeState.guideTag; });
        if (homeState.guideTag && !tagCounts[homeState.guideTag]) homeState.guideTag = null;

        var libCount = el("span", { class: "count" });
        var libList = el("div");
        var tagBox = el("div", { class: "chips small lib-tags", role: "group", "aria-label": "按标签筛选攻略" });
        function drawLibrary() {
          var list = allGuides.filter(function (g) { return guideMatches(g, homeState.guideTag, homeState.query.trim()); });
          libCount.textContent = list.length;
          tagBox.replaceChildren();
          [null].concat(cats, otherTags).forEach(function (t) {
            tagBox.append(el("button", {
              type: "button", class: "chip" + (t && cats.indexOf(t) !== -1 ? " cat" : ""),
              "aria-pressed": homeState.guideTag === t ? "true" : "false",
              text: t === null ? "全部" : t,
              onclick: function () { homeState.guideTag = t; drawLibrary(); },
            }));
          });
          libList.replaceChildren(
            list.length
              ? el("div", { class: "cards" }, list.map(guideCard))
              : el("p", { class: "empty", text: allGuides.length ? "没有符合条件的攻略。换个关键词，或者欢迎贡献一份。" : "攻略库是空的。" })
          );
        }
        var search = el("input", {
          type: "search", class: "lib-search", value: homeState.query, placeholder: "搜索攻略：国家、城市、签证类型……", "aria-label": "搜索攻略",
        });
        search.addEventListener("input", function () { homeState.query = search.value; drawLibrary(); });
        drawLibrary();

        var heading = el(
          "div",
          { class: "heading" },
          el("div", null, el("h1", { text: "照着攻略，一件件办好。" }))
        );
        var trackSection = el(
            "section",
            { class: "panel" },
            el("div", { class: "panel-head" }, el("h2", null, "办理中", el("span", { class: "count", text: active.length })), trackChips),
            activeCards.length
              ? el("div", { class: "cards" }, activeCards)
              : homeState.trackCat || tracks.length
                ? el("p", { class: "empty", text: homeState.trackCat ? "这个分类下没有正在办的事。" : "还没有。从下面的攻略库里挑一份，点进去开始办。" })
                // 第一次用、一件事都没有：可以先开一件示例看看办事页长什么样（看完在办事页里删掉）
                : el("p", { class: "empty" }, "还没有。从下面的攻略库里挑一份，点进去开始办，或者",
                    el("button", { type: "button", class: "link-btn", text: "先看一个示例", onclick: function (ev) {
                      ev.currentTarget.disabled = true;
                      request("POST", "/api/tracks", { guide: "schengen-tourist", title: "示例：申根短期旅游签证" })
                        .then(function (t) { location.hash = "#/track/" + encodeURIComponent(t.id); })
                        .catch(function (e) { showError(e.message); });
                    } }))
          );
        var librarySection = el(
            "section",
            { class: "panel library" },
            el("div", { class: "panel-head" }, el("h2", null, "攻略库", libCount),
              el("button", { type: "button", class: "primary new-guide-btn", text: "+ 新建攻略", onclick: function () { location.hash = "#/new"; } })),
            el("div", { class: "lib-filter" }, search, tagBox),
            libList
          );
        // 在线演示站（docs/demo/site.md）：来看的人先看攻略库
        if (window.PA_DEMO) setView(heading, librarySection, trackSection, doneSection);
        else setView(heading, trackSection, doneSection, librarySection);
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

  // ---------- 新建攻略（spec 004 第 2 步）----------
  //
  //   #/new                    选攻略类型（以后别的办事类攻略在这里加；旅游攻略单独在 /travel.html）+ 没保存的草稿；
  //                            只有一种能新建的类型时直接跳到它的新建窗口（草稿列表在新建窗口右边）
  //   #/new/<类型>[/<草稿 id>]  左边和 Agent 对话，右边是草稿：校验结果、词表建议、保存 / 丢弃
  //   #/draft/<类型>/<草稿 id>  草稿的完整预览（和正式攻略的预览页一样）

  var workspaceChat = null;
  var XHS_LINK = /https?:\/\/(?:xhslink\.(?:cn|com)|(?:www\.)?xiaohongshu\.com)\/\S+/g;

  function renderNewType() {
    Promise.all([request("GET", "/api/guide-types"), request("GET", "/api/guide-drafts")])
      .then(function (results) {
        var types = results[0], drafts = results[1];
        var available = types.filter(function (t) { return t.available; });
        if (available.length === 1) {
          // 只有一种能选，不用再选：直接进新建窗口（replace：按返回键回到攻略库，不会又被跳回来）
          location.replace("#/new/" + encodeURIComponent(available[0].id));
          return;
        }
        var nameOf = {};
        types.forEach(function (t) { nameOf[t.id] = t.name; });
        setView(
          el("div", { class: "heading" }, el("div", null,
            el("div", { class: "crumb" }, el("a", { href: "#/", text: "攻略库" }), " / 新建攻略"),
            el("h1", { text: "新建攻略" }),
            el("p", { class: "muted", text: "先选要写哪一类攻略。不同类型的内容结构不一样，Agent 会按对应的规则整理。" }))),
          el("div", { class: "cards type-cards" }, types.map(function (t) {
            return t.available
              ? el("a", { class: "card", href: "#/new/" + encodeURIComponent(t.id) },
                  el("h3", { text: t.name }), el("p", { class: "meta", text: t.description }), el("div", { class: "next", text: "选这个 →" }))
              : el("div", { class: "card disabled", "aria-disabled": "true" },
                  el("span", { class: "meta" }, el("span", { class: "tag soft", text: "规划中" })),
                  el("h3", { text: t.name }), el("p", { class: "meta", text: t.description }));
          })),
          drafts.length
            ? el("section", { class: "panel" },
                el("div", { class: "panel-head" }, el("h2", null, "还没保存的草稿", el("span", { class: "count", text: drafts.length }))),
                el("div", { class: "cards" }, drafts.map(function (d) {
                  return el("a", { class: "card", href: "#/new/" + encodeURIComponent(d.type) + "/" + encodeURIComponent(d.id) },
                    el("span", { class: "meta" }, el("span", { class: "tag soft", text: nameOf[d.type] || d.type }), " " + d.id),
                    el("h3", { text: d.title || d.id }),
                    el("div", { class: "next", text: (d.valid ? "✓ 校验通过" : "✗ 校验未通过") + " · 继续编辑 →" }));
                })))
            : null
        );
      })
      .catch(function (e) { setView(); showError(e.message); });
  }

  function renderNewWorkspace(typeId, initialDraft) {
    request("GET", "/api/guide-types").then(function (types) {
      var type = types.filter(function (t) { return t.id === typeId; })[0];
      if (!type || !type.available) {
        setView(el("p", null, el("a", { href: "#/new", text: "← 重新选攻略类型" })));
        showError(type ? "「" + type.name + "」还不能新建。" : "没有这种攻略类型：" + typeId);
        return;
      }
      var draftId = initialDraft;
      var draftBox = el("div", { class: "draft-box" });

      function drawEmpty() {
        var empty = el("div", { class: "draft-empty" },
          el("p", { text: "草稿会显示在这里。" }),
          el("p", { class: "muted", text: "Agent 整理好之后，这里会出现草稿和「保存到攻略库」按钮。" }));
        draftBox.replaceChildren(empty);
        // 以前没保存的草稿列在这里，点一下接着编辑（选类型那一页可能被跳过了）
        request("GET", "/api/guide-drafts").then(function (drafts) {
          drafts = drafts.filter(function (d) { return d.type === typeId; });
          if (!drafts.length || draftId) return;
          empty.append(el("div", { class: "draft-older" },
            el("h3", { text: "还没保存的草稿（" + drafts.length + "）" }),
            el("ul", null, drafts.map(function (d) {
              return el("li", null,
                el("a", { href: "#/new/" + encodeURIComponent(d.type) + "/" + encodeURIComponent(d.id), text: d.title || d.id }),
                el("small", { class: "muted", text: d.valid ? "　✓ 校验通过" : "　✗ 校验未通过" }));
            }))));
        }).catch(function () { /* 列不出来也不影响新建 */ });
      }

      function loadDraft() {
        if (!draftId) { drawEmpty(); return; }
        request("GET", "/api/guide-drafts/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(draftId))
          .then(function (d) { drawDraft(d.check); })
          .catch(function (e) { draftBox.replaceChildren(el("p", { class: "banner", text: e.message })); });
      }

      // 草稿面板只放要紧的：能不能保存、看预览、需要留意的几件事。
      // 词表建议收成一个勾选框（默认勾上，保存时一起加进词表）；没有建议的叫法不列出来。
      function drawDraft(c) {
        var base = "/api/guide-drafts/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(c.id);
        var previewHref = "#/draft/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(c.id);
        var suggestions = c.alias_suggestions.filter(function (s) {
          return c.unresolved.some(function (u) { return u.raw_name === s.raw_name; });
        });
        var aliasAll = el("input", { type: "checkbox", checked: true });
        var aliasBoxes = suggestions.map(function (s) { return { box: el("input", { type: "checkbox", checked: true }), s: s }; });
        aliasAll.addEventListener("change", function () { aliasBoxes.forEach(function (b) { b.box.checked = aliasAll.checked; }); });
        aliasBoxes.forEach(function (b) {
          b.box.addEventListener("change", function () { aliasAll.checked = aliasBoxes.some(function (x) { return x.box.checked; }); });
        });

        var notes = [];
        if (c.conflict_count) notes.push(el("li", null, c.conflict_count + " 处各篇说法不同，", el("a", { href: previewHref, target: "_blank", text: "在预览里看" })));
        if (c.uncertain.length) notes.push(el("li", { text: c.uncertain.length + " 处只有一篇提到或来自二手总结，已标为待核实" }));

        var publishBtn = el("button", { type: "button", class: "primary", text: "保存到攻略库", disabled: !c.valid });
        publishBtn.addEventListener("click", function () {
          publishBtn.disabled = true;
          var picked = aliasBoxes.filter(function (b) { return b.box.checked; }).map(function (b) { return { key: b.s.key, alias: b.s.raw_name }; });
          (picked.length ? request("POST", "/api/vocab/aliases", { aliases: picked }) : Promise.resolve())
            .then(function () { return request("POST", base + "/publish"); })
            .then(function (r) {
              draftId = null;
              history.replaceState(null, "", "#/new/" + encodeURIComponent(typeId));
              draftBox.replaceChildren(el("div", { class: "notice" },
                el("p", null, "已保存到攻略库：", el("a", { href: "#/guide/" + encodeURIComponent(r.guide_id), text: c.title || r.guide_id }),
                  picked.length ? "，词表加了 " + picked.length + " 个叫法" : ""),
                el("p", { class: "muted", text: "还没提交到 git，提交前在终端里逐个文件检查。" })));
            })
            .catch(function (e) { publishBtn.disabled = !c.valid; showError(e.message); });
        });
        var discardBtn = el("button", { type: "button", class: "quiet", text: "丢弃" });
        discardBtn.addEventListener("click", function () {
          if (discardBtn.dataset.armed !== "1") { discardBtn.dataset.armed = "1"; discardBtn.textContent = "再点一次确认丢弃"; return; }
          request("DELETE", base).then(function () {
            draftId = null;
            history.replaceState(null, "", "#/new/" + encodeURIComponent(typeId));
            drawEmpty();
          }).catch(function (e) { showError(e.message); });
        });

        // 原生 replaceChildren 会把 null 显示成文字 "null"，所以包一层 el() 让它按规则跳过空值
        draftBox.replaceChildren(el("div", { class: "draft-body" },
          el("span", { class: "meta", text: "草稿" }),
          el("h2", { class: "draft-title", text: c.title || c.id }),
          el("div", { class: "draft-status " + (c.valid ? "ok" : "bad"),
            text: (c.valid ? "✓ 可以保存 · " : "✗ 还有 " + c.errors.length + " 处要改 · ") + c.requirement_count + " 项材料 · " + c.step_count + " 个步骤" }),
          el("a", { class: "draft-preview-link", href: previewHref, target: "_blank", text: "查看完整预览 ↗" }),
          c.errors.length
            ? el("div", { class: "draft-sec" },
                el("ul", { class: "draft-errors" }, c.errors.slice(0, 5).map(function (e) { return el("li", { text: e }); })),
                el("button", { type: "button", text: "让 Agent 改", onclick: function () { if (workspaceChat) workspaceChat.send("把草稿的校验错误改掉"); } }))
            : null,
          notes.length ? el("ul", { class: "draft-notes" }, notes) : null,
          aliasBoxes.length
            ? el("div", { class: "draft-alias" },
                el("label", null, aliasAll, " 保存时把 " + aliasBoxes.length + " 个材料叫法加进词表"),
                el("details", null, el("summary", { text: "是哪几个" }),
                  el("p", { class: "muted", text: "加进去后，这些材料能和「我的资料」自动对上。取消勾选的不加。" }),
                  el("ul", null, aliasBoxes.map(function (b) { return el("li", null, el("label", null, b.box, " " + b.s.raw_name + " → " + b.s.key_name)); }))))
            : null,
          el("div", { class: "draft-actions" }, discardBtn, publishBtn)
        ));
      }

      workspaceChat = window.AgentChat.create({
        kind: "create_guide",
        rows: 7,
        enterNewline: true,
        placeholder: "把小红书分享文字（App 里「复制链接」得到的整段）、帖子正文，或别处的总结贴在这里。⌘ / Ctrl + 回车发送",
        hint: "Agent 会在不登录的浏览器里读帖子（一次最多 6 条链接），按项目规则整理成草稿，显示在右边。之后可以继续跟它说要怎么改，比如「把第 3 步拆开」「冲突的地方再解释一下」。",
        sendLabel: function (hasSession) { return hasSession || draftId ? "发送" : "开始整理"; },
        validate: function (text) {
          var n = (text.match(XHS_LINK) || []).length;
          return n > 6 ? "一次最多 6 条小红书链接（现在 " + n + " 条），分几次发。" : null;
        },
        context: function () { return { page: "new", guide_type: typeId, draft_id: draftId }; },
        onEvent: function (type, data) {
          if (type === "draft" && data.draft_id) {
            draftId = data.draft_id;
            history.replaceState(null, "", "#/new/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(draftId));
            loadDraft();
          }
          if (type === "done" || type === "error") loadDraft();
        },
      });

      setView(
        el("div", { class: "heading" }, el("div", null,
          // 只有一种类型时"新建攻略"那一页会直接跳回这里，面包屑就不给它链接
          types.filter(function (t) { return t.available; }).length > 1
            ? el("div", { class: "crumb" }, el("a", { href: "#/", text: "攻略库" }), " / ", el("a", { href: "#/new", text: "新建攻略" }), " / " + type.name)
            : el("div", { class: "crumb" }, el("a", { href: "#/", text: "攻略库" }), " / 新建攻略"),
          el("h1", { text: "新建" + type.name }),
          el("p", { class: "muted", text: type.description }))),
        el("div", { class: "new-ws" },
          el("section", { class: "panel ws-chat" }, el("div", { class: "panel-head" }, el("h2", { text: "和 Agent 对话" })), workspaceChat.root),
          el("section", { class: "panel ws-draft" }, draftBox))
      );
      loadDraft();
      workspaceChat.input.focus();
    }).catch(function (e) { setView(); showError(e.message); });
  }

  function renderDraft(typeId, id) {
    request("GET", "/api/guide-drafts/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(id))
      .then(function (d) {
        var c = d.check;
        var head = el("div", { class: "heading" }, el("div", null,
          el("div", { class: "crumb" }, el("a", { href: "#/new", text: "新建攻略" }), " / 草稿 / " + id),
          el("h1", { text: c.title || id })));
        var back = el("a", { href: "#/new/" + encodeURIComponent(typeId) + "/" + encodeURIComponent(id), text: "回到新建窗口 →" });
        if (!c.valid) {
          setView(head, el("div", { class: "banner" }, "草稿还没通过校验：", el("ul", null, c.errors.map(function (e) { return el("li", { text: e }); })), back));
          return;
        }
        setView(
          head,
          el("div", { class: "notice preview-notice" }, el("span", { text: "这是草稿预览：还没保存进攻略库。已经用你材料库里现有的材料先对了一遍。" }), back),
          trackBody(d.preview, { readonly: true, aside: el("section", { class: "panel" }, el("h2", { text: "草稿" }),
            el("p", { class: "muted", text: "在新建窗口里继续修改、确认词表建议，然后保存到攻略库。" }), back) })
        );
      })
      .catch(function (e) { setView(); showError(e.message); });
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
            "div",
            { class: "notice preview-notice" },
            el("span", { text: "这是预览（只读）：已经用你材料库里现有的材料先对了一遍。要上传材料、勾选步骤、回答问题，请先开始办。" }),
            // 右侧的"开始办"表单在窄屏上会排到页面最底下，这里放一个随时能点到的入口
            el("button", { class: "primary", type: "button", text: "开始办 →", onclick: function () { form.requestSubmit(); } })
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
      el("div", { class: "track-tools" }, v.completed ? null : deadlineEditor(v), deleteTrackButton(v))
    );
    // 重新渲染会替换整块内容，先记住滚动位置，避免每点一次就跳回顶部
    var y = window.scrollY;
    setView(head, trackBody(v, { readonly: false }));
    window.scrollTo(0, y);
  }

  // 删除这件办事：点两次才删；文件移到材料根目录的 tracks/.trash/，不是真的删掉（DELETE /api/tracks/{id}）
  function deleteTrackButton(v) {
    var btn = el("button", { type: "button", class: "quiet", text: "删除这件事" });
    btn.addEventListener("click", function () {
      if (btn.dataset.armed !== "1") { btn.dataset.armed = "1"; btn.textContent = "再点一次确认删除"; return; }
      btn.disabled = true;
      request("DELETE", "/api/tracks/" + encodeURIComponent(v.id))
        .then(function () { location.hash = "#/"; })
        .catch(function (e) { btn.disabled = false; showError(e.message); });
    });
    return btn;
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

  // 哪些办事页把"你的情况"展开了（只存在页面内存里，刷新后恢复成收起）
  var factsExpanded = {};

  // "你的情况"一行里的短标签：答"是 / 否"的要带上问题，不然看不懂；其他答案本身就说明了
  function factAnswerLabel(f) {
    if (f.value === "是" || f.value === "否") {
      var q = f.question.replace(/[（(].*$/, "").replace(/[？?]$/, "").replace(/^(你|申请人|这次旅行)?(是否|有没有)?/, "");
      return q + "：" + f.value;
    }
    return f.value;
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

    // --- 下一步（刚开始办时先显示"开始清单"，spec 007 第 3 步）---
    if (!readonly) main.append((window.StartCard && window.StartCard.render(v, {
      el: el,
      upload: function (path, fd) {
        showError("");
        return uploadRequest(path, fd).then(function (nv) { return loadMyRecords().then(function () { return nv; }); })
          .catch(function (e) { showError(e.message); throw e; });
      },
      remove: function (recordId) {
        showError("");
        return request("DELETE", "/api/tracks/" + encodeURIComponent(v.id) + "/materials/" + encodeURIComponent(recordId))
          .then(function (nv) { return loadMyRecords().then(function () { return nv; }); })
          .catch(function (e) { showError(e.message); throw e; });
      },
      setFolder: function (path) {
        showError("");
        return request("PUT", "/api/tracks/" + encodeURIComponent(v.id) + "/folder", { path: path })
          .catch(function (e) { showError(e.message); throw e; });
      },
      chooseFolder: function () {
        showError("");
        return fetch("/api/tracks/" + encodeURIComponent(v.id) + "/folder/choose", { method: "POST", headers: { Accept: "application/json" } })
          .then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (b) {
              if (r.ok) return b;
              var err = new Error(b.detail || "出错了（" + r.status + "）");
              err.status = r.status;
              if (r.status !== 501) showError(err.message);
              throw err;
            });
          });
      },
      redraw: drawTrack,
      jump: jumpTo,
      openTrip: function () {
        if (window.TripPanel) window.TripPanel.open(v.id);
        drawTrack(v);
        jumpTo("trip");
        var box = document.querySelector("#trip .trip-extract textarea");
        if (box) box.focus({ preventScroll: true });
      },
    })) || overviewCard(v, stepById));

    // --- 问题 ---
    var asked = v.facts.filter(function (f) { return f.asked; });
    // 答过的问题收成一行"你的情况：…"，点「修改」才展开；没答的问题照常显示在下面
    var factsOpen = readonly || !!factsExpanded[v.id];
    var answered = asked.filter(function (f) { return f.value !== null; });
    var shownFacts = factsOpen ? asked : asked.filter(function (f) { return f.value === null; });
    if (!readonly && answered.length && !factsOpen) {
      main.append(el(
        "section",
        { class: "panel facts-summary" },
        el("span", { class: "muted", text: "你的情况：" }),
        el("span", { text: answered.map(factAnswerLabel).join(" · ") }),
        el("button", { type: "button", class: "linkish", text: "修改", onclick: function () { factsExpanded[v.id] = true; drawTrack(v); } })
      ));
    }
    if (shownFacts.length) {
      var unanswered = asked.filter(function (f) { return f.value === null; }).length;
      main.append(
        el(
          "section",
          { class: "panel", id: "facts" },
          el(
            "div",
            { class: "panel-head" },
            el("h2", { text: readonly ? "开始办之后会问你这些问题" : unanswered ? "先回答几个问题" : "你的情况" }),
            readonly
              ? el("small", { text: "回答后，和你无关的材料会自动隐藏" })
              : factsOpen && answered.length
                ? el("button", { type: "button", class: "linkish", text: "收起", onclick: function () { factsExpanded[v.id] = false; drawTrack(v); } })
                : el("small", { text: "还有 " + unanswered + " 个没回答" })
          ),
          el(
            "div",
            { class: "facts" },
            shownFacts.map(function (f) {
              return el(
                "div",
                { class: "fact" + (f.value !== null ? " answered" : "") },
                el("div", { class: "q", text: f.question }),
                f.type === "date" ? dateFactInput(v, f, readonly) : el(
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

    // --- 这次行程（spec 007）：开始办之后问，预览里不显示 ---
    if (!readonly && window.TripPanel) {
      main.append(window.TripPanel.render(v, {
        el: el,
        redraw: drawTrack,
        save: function (track, change) { update(track, "/trip", change); },
      }));
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
            // 每个阶段最后一个可见步骤的 id：给该阶段的"＋ 加一步"当 after，让新步骤总是插到这个阶段末尾
            var lastStepInPhase = {};
            visibleSteps.forEach(function (s) { if (s.phase) lastStepInPhase[s.phase] = s.id; });
            var items = [];
            var lastPhase = null;
            visibleSteps.forEach(function (s) {
              if (s.phase && s.phase !== lastPhase && phaseById[s.phase]) {
                var ph = phaseById[s.phase];
                items.push(el(
                  "li",
                  { class: "phase-heading", id: "phase-" + ph.p.id },
                  el("span", { text: "第 " + (ph.i + 1) + " 阶段 · " + ph.p.title }),
                  MODE_LABEL[ph.p.mode] ? el("span", { class: "mode " + ph.p.mode, text: MODE_LABEL[ph.p.mode] }) : null,
                  readonly ? null : addStepButton(v, ph.p.id, lastStepInPhase[ph.p.id])
                ));
                lastPhase = s.phase;
              }
              items.push(stepItem(s, v, { readonly: readonly, reqById: reqById, stepById: stepById, factsByKey: factsByKey, anchored: anchored }));
            });
            // 没有阶段的攻略：在整个步骤列表末尾放同样的"＋ 加一步"
            if (!v.phases.length && !readonly) {
              items.push(el(
                "li",
                { class: "add-row" },
                addStepButton(v, null, visibleSteps.length ? visibleSteps[visibleSteps.length - 1].id : null)
              ));
            }
            return items;
          })()
        ),
        readonly ? null : hiddenItemsBlock(v)
      )
    );

    // --- 侧栏 ---
    var side = el("div", { class: "sticky" });
    if (opts.aside) side.append(opts.aside);
    var remindersNode = readonly ? null : remindersPanel(v);  // 没有时间窗的攻略返回 null，原生 append(null) 会显示成文字 "null"
    if (remindersNode) side.append(remindersNode);
    side.append(checklistPanel(v, readonly));
    if (v.requirements.length) {
      side.append(materialSummary(v));
      if (!readonly) side.append(exportPanel(v));
    }

    return el("div", null, phaseBar(v, stepById), el("div", { class: "layout" }, main, el("div", null, side)));
  }

  var MODE_LABEL = { online: "线上", offline: "线下" };
  var PHASE_STATE_LABEL = { done: "已完成", current: "进行中", upcoming: "未开始", skipped: "不需要" };

  function durationText(d) {
    return d ? "通常 " + d.typical + " 天，最长 " + d.max + " 天" : null;
  }

  function jumpTo(id) {
    var target = document.getElementById(id);
    if (!target) return;
    // 用户开了"减少动态效果"、或页面不在前台（浏览器会暂停平滑滚动）时，直接跳过去
    var reduce = (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) || document.visibilityState !== "visible";
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  // 页面最上方的"大阶段"进度条：先让人知道整件事分几段、现在走到哪、一般要多久。
  // 每一段都可以点，跳到下面这一段的步骤和材料。（2026-09-28 去掉了往下滑时吸在顶部的精简条：和这里重复，页面太花。）
  function phaseBar(v) {
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

    return el(
      "div",
      null,
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

  // 日期类问题：选好日期就保存；"清除"撤回回答
  function dateFactInput(v, f, readonly) {
    var input = el("input", {
      type: "date", value: f.value || null, disabled: readonly, "aria-label": f.question,
      onchange: function () { if (input.value) update(v, "/facts/" + encodeURIComponent(f.key), { value: input.value }); },
    });
    return el(
      "div",
      { class: "options" },
      input,
      f.value && !readonly
        ? el("button", { type: "button", text: "清除", onclick: function () { update(v, "/facts/" + encodeURIComponent(f.key), { value: null }); } })
        : null
    );
  }

  // 办事页最上方的总览：把要做的事分成「线上填表」和「材料准备」两块。
  // 不再放"这一步做完了"大按钮：挂着材料的步骤，材料齐了由后端自动算完成（StepView.auto_done）；
  // 其余步骤（例如去现场递签）在下面时间线里点圆圈标记，或者让 Agent 填完表后标记。
  function overviewCard(v, stepById) {
    var s = v.next_step ? stepById[v.next_step] : null;
    var allDone = v.steps.every(function (x) { return x.applies === "no" || x.done; });
    var pending = v.steps.filter(function (x) { return x.applies === "undecided"; }).length;

    var headline;
    if (s) {
      headline = [
        el("div", { class: "label", text: "下一步" + phaseLabel(v, s.phase) }),
        el("h2", null, el("a", { href: "#step-" + s.id, text: s.title, onclick: function (ev) { ev.preventDefault(); jumpTo("step-" + s.id); } })),
        windowLine(s, factsFromView(v), stepById),
        s.late ? el("p", { class: "late-alert", text: "⚠ 已经超过建议的最晚开始时间，尽快推进这一步" }) : null,
      ];
    } else {
      headline = [
        el("div", { class: "label", text: allDone ? "全部完成" : "下一步" }),
        el("h2", { text: allDone ? "所有步骤都做完了。" : pending ? "先回答下面的问题" : "暂时没有能马上做的步骤" }),
        !allDone && v.reminders && v.reminders.length
          ? el("p", { class: "muted", text: "最近的一件事：" + reminderText(v.reminders[0]) + "。到时候来这里，或者把提醒加到日历里。" })
          : null,
        allDone ? el("p", { class: "muted", text: (v.completed ? "用时 " + v.elapsed_days + " 天（" + v.created + " → " + v.completed + "）。" : "") + "别忘了最后核对一遍材料之间是否对得上。" }) : null,
      ];
    }

    // 只说下一步：这一步的官网链接 + 一行总进度。材料清单在右边「材料一览」和各个步骤里，这里不再重复。
    var online = v.steps.filter(function (x) { return x.applies === "yes" && isOnlineStep(v, x); });
    var progress = [];
    if (online.length) progress.push("线上 " + online.filter(function (x) { return x.done; }).length + " / " + online.length + " 步");
    if (v.progress_total) progress.push("材料 " + v.progress_ready + " / " + v.progress_total + " 已备齐");
    var links = s && !s.done ? s.links.filter(function (l) { return l.applies === "yes" && (l.kind === "official" || l.kind === "form_guide"); }).slice(0, 2) : [];
    return el(
      "section",
      { class: "next-card overview" + (allDone ? " done-all" : "") + (s && s.late ? " late" : "") },
      headline,
      links.length
        ? el("div", { class: "ov-links" }, links.map(function (l) {
            return l.kind === "form_guide" && l.form
              ? el("a", { class: "ov-link", href: "#/form/" + encodeURIComponent(l.form), text: l.title })
              : el("a", { class: "ov-link", href: l.url, target: "_blank", rel: "noopener noreferrer", text: l.title + " ↗" });
          }))
        : null,
      progress.length ? el("div", { class: "ov-progress" }, v.progress_total ? progressBar(v.progress_ready, v.progress_total) : null, el("small", { class: "muted", text: progress.join(" · ") })) : null
    );
  }

  // 线上步骤：攻略给阶段标了线上/线下时，只算"线上"阶段里的步骤；
  // 整份攻略都没标时，退一步看这一步有没有官网或填表指南链接
  function isOnlineStep(v, s) {
    if (v.phases.some(function (p) { return p.mode; })) {
      var ph = v.phases.filter(function (p) { return p.id === s.phase; })[0];
      return !!ph && ph.mode === "online";
    }
    return s.links.some(function (l) { return l.applies === "yes" && (l.kind === "official" || l.kind === "form_guide"); });
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
          title: internal ? null : (l.verified ? l.verified + " 已核实能打开、是官方站点" : "这个链接尚未核实，打开后请确认是官方网站"),
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

  // ---------- 个人调整：平铺的操作 / 备注 / 改名 / 删除确认 / 加步骤 / 加材料 / 已隐藏 ----------
  // （specs/002-guide-to-track/tasks-parallel-3.md 任务 F；只在办事页出现，攻略预览页 readonly 时不构造这些控件）

  // 把"再点一次删除"重置回原文字。挂在 document 上，点别处任何地方都会触发。
  function closeAllMenus() {
    document.querySelectorAll(".menu-inline").forEach(resetConfirms);
  }

  function resetConfirms(menu) {
    menu.querySelectorAll("[data-confirming]").forEach(function (b) {
      delete b.dataset.confirming;
      b.textContent = b.dataset.label;
    });
  }

  // 步骤 / 材料的操作直接平铺在后面（2026-09-30 项目主：点开"⋯"再选太麻烦）；桌面上鼠标移到那一项才显示
  function inlineActions(items) {
    return el("div", { class: "menu-wrap" }, el("div", { class: "menu-inline" }, items));
  }

  function menuButton(label, onclick) {
    return el("button", { type: "button", class: "menu-item", text: label, onclick: function () { onclick(); } });
  }

  // "删除"按钮：第一次点变成"确认删除？"，第二次点才真的发请求；不用 window.confirm。
  function confirmDeleteButton(label, doDelete) {
    var btn = el("button", { type: "button", class: "menu-item danger", text: label });  // 平铺在后面，点两次才删
    btn.dataset.label = label;
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation(); // 第一次点击不能让它冒泡到 document 把"确认删除？"状态重置掉
      if (!btn.dataset.confirming) {
        btn.dataset.confirming = "1";
        btn.textContent = "再点一次删除";
        return;
      }
      btn.disabled = true;
      showError("");
      doDelete()
        .then(drawTrack)
        .catch(function (e) {
          showError(e.message);
          btn.disabled = false;
          delete btn.dataset.confirming;
          btn.textContent = label;
        });
    });
    return btn;
  }

  // 步骤/材料的个人备注：浅色便签，点它或点菜单里的"加备注"进入编辑；保存空内容 = 删除备注。
  // kind 是 "steps" 或 "requirements"，对应 PUT /api/tracks/{id}/notes/<kind>/<id>。
  function noteBlock(v, kind, id, note) {
    var display = el("button", { type: "button", class: "note-chip", hidden: !note }, "我的备注：" + (note || ""));
    var input = el("input", { type: "text", maxlength: "500", value: note || "", "aria-label": "备注内容" });
    var form = el(
      "form",
      {
        class: "note-edit",
        hidden: true,
        onsubmit: function (ev) {
          ev.preventDefault();
          update(v, "/notes/" + kind + "/" + encodeURIComponent(id), { note: input.value });
        },
      },
      input,
      el("button", { type: "submit", text: "保存" }),
      el("button", { type: "button", text: "取消", onclick: function () { closeEdit(); } })
    );
    function openEdit() {
      input.value = note || "";
      display.hidden = true;
      form.hidden = false;
      input.focus();
    }
    function closeEdit() {
      form.hidden = true;
      display.hidden = !note;
    }
    display.addEventListener("click", openEdit);
    return { node: el("div", { class: "note-wrap" }, display, form), open: openEdit };
  }

  // 自己加的步骤/材料的"改名"：行内输入框 + 保存/取消。field 是 "title"（步骤）或 "name"（材料）。
  function renameBlock(v, path, field, current) {
    var input = el("input", { type: "text", maxlength: "100", value: current, "aria-label": "新名称" });
    var form = el(
      "form",
      {
        class: "rename-edit",
        hidden: true,
        onsubmit: function (ev) {
          ev.preventDefault();
          if (!input.value.trim()) return;
          var body = {};
          body[field] = input.value;
          update(v, path, body);
        },
      },
      input,
      el("button", { type: "submit", text: "保存" }),
      el("button", { type: "button", text: "取消", onclick: function () { form.hidden = true; } })
    );
    return {
      node: form,
      open: function () {
        input.value = current;
        form.hidden = false;
        input.focus();
      },
    };
  }

  // 阶段末尾/无阶段攻略末尾的"＋ 加一步"：点开行内表单，提交 POST /custom-steps。
  function addStepButton(v, phaseId, afterId) {
    var titleInput = el("input", { type: "text", required: true, maxlength: "100", placeholder: "步骤名称", "aria-label": "新步骤名称" });
    var whereInput = el("input", { type: "text", maxlength: "100", placeholder: "地点（可选）", "aria-label": "地点" });
    var submit = el("button", { type: "submit", text: "添加" });
    var toggle;
    var form = el(
      "form",
      {
        class: "add-inline",
        hidden: true,
        onsubmit: function (ev) {
          ev.preventDefault();
          if (!titleInput.value.trim()) return;
          submit.disabled = true;
          showError("");
          request("POST", "/api/tracks/" + encodeURIComponent(v.id) + "/custom-steps", {
            title: titleInput.value,
            phase: phaseId || null,
            after: afterId || null,
            where: whereInput.value.trim() || null,
          })
            .then(drawTrack)
            .catch(function (e) {
              submit.disabled = false;
              showError(e.message);
            });
        },
      },
      titleInput,
      whereInput,
      submit,
      el("button", {
        type: "button",
        text: "取消",
        onclick: function () {
          form.hidden = true;
          toggle.hidden = false;
          titleInput.value = "";
          whereInput.value = "";
        },
      })
    );
    toggle = el("button", {
      type: "button",
      class: "linkish",
      text: "＋ 加一步",
      onclick: function () {
        toggle.hidden = true;
        form.hidden = false;
        titleInput.focus();
      },
    });
    return el("span", { class: "add-inline-wrap" }, toggle, form);
  }

  // 步骤的材料列表末尾的"＋ 加材料"：点开行内表单，提交 POST /custom-materials。
  function addMaterialButton(v, stepId) {
    var nameInput = el("input", { type: "text", required: true, maxlength: "100", placeholder: "材料名称", "aria-label": "新材料名称" });
    var bonus = el("input", { type: "checkbox" });
    var submit = el("button", { type: "submit", text: "添加" });
    var toggle;
    var form = el(
      "form",
      {
        class: "add-inline",
        hidden: true,
        onsubmit: function (ev) {
          ev.preventDefault();
          if (!nameInput.value.trim()) return;
          submit.disabled = true;
          showError("");
          request("POST", "/api/tracks/" + encodeURIComponent(v.id) + "/custom-materials", {
            name: nameInput.value,
            step: stepId,
            optional: bonus.checked,
          })
            .then(drawTrack)
            .catch(function (e) {
              submit.disabled = false;
              showError(e.message);
            });
        },
      },
      nameInput,
      el("label", { class: "bonus-label" }, bonus, "加分项"),
      submit,
      el("button", {
        type: "button",
        text: "取消",
        onclick: function () {
          form.hidden = true;
          toggle.hidden = false;
          nameInput.value = "";
          bonus.checked = false;
        },
      })
    );
    toggle = el("button", {
      type: "button",
      class: "linkish",
      text: "＋ 加材料",
      onclick: function () {
        toggle.hidden = true;
        form.hidden = false;
        nameInput.focus();
      },
    });
    return el("div", { class: "add-inline-wrap" }, toggle, form);
  }

  // 步骤面板底部："已隐藏 N 项"，默认折叠，展开后每项一行 + 恢复按钮。
  function hiddenItemsBlock(v) {
    if (!v.hidden_items.length) return null;
    return el(
      "details",
      { class: "hidden-items" },
      el("summary", { text: "已隐藏 " + v.hidden_items.length + " 项" }),
      el(
        "ul",
        null,
        v.hidden_items.map(function (item) {
          var path = "/hidden/" + (item.kind === "step" ? "steps/" : "requirements/") + encodeURIComponent(item.id);
          return el(
            "li",
            null,
            el("span", { text: (item.kind === "step" ? "步骤：" : "材料：") + item.title }),
            el("button", { type: "button", text: "恢复", onclick: function () { update(v, path, { hidden: false }); } })
          );
        })
      )
    );
  }

  function stepItem(s, v, ctx) {
    var cls = "step" + (s.id === v.next_step ? " is-next" : "") + (s.done ? " is-done" : "") + (s.applies === "undecided" ? " is-undecided" : "");
    var tick = el("button", {
      type: "button",
      class: "tick",
      text: s.done ? "✓" : "",
      "aria-pressed": s.done ? "true" : "false",
      "aria-label": s.auto_done ? "材料齐了，自动完成：" + s.title : (s.done ? "取消完成：" : "标记完成：") + s.title,
      title: s.auto_done ? "这一步的材料都齐了，自动算完成" : null,
      disabled: ctx.readonly || s.applies !== "yes" || s.auto_done,
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

    var note = ctx.readonly ? null : noteBlock(v, "steps", s.id, s.user_note);
    var rename = !ctx.readonly && s.custom ? renameBlock(v, "/custom-steps/" + encodeURIComponent(s.id), "title", s.title) : null;
    var menu = null;
    if (!ctx.readonly) {
      var menuItems = [
        menuButton("备注", note.open),
        menuButton("隐藏", function () { update(v, "/hidden/steps/" + encodeURIComponent(s.id), { hidden: true }); }),
      ];
      if (s.custom) {
        menuItems.push(menuButton("改名", rename.open));
        menuItems.push(confirmDeleteButton("删除", function () {
          return request("DELETE", "/api/tracks/" + encodeURIComponent(v.id) + "/custom-steps/" + encodeURIComponent(s.id));
        }));
      }
      menu = inlineActions(menuItems);
    }

    var mats = s.requirements
      .map(function (rid) { return ctx.reqById[rid]; })
      .filter(function (r) { return r && r.state !== "not_applicable"; })
      .map(function (r) { return materialItem(r, v, ctx); });
    var matsBlock = mats.length || !ctx.readonly
      ? el("div", { class: "mats" }, mats, ctx.readonly ? null : addMaterialButton(v, s.id))
      : null;

    // 做完的步骤默认只剩一行标题，点标题展开 / 收起（预览页不折叠）
    var foldable = !ctx.readonly && s.done;
    var item = el(
      "li",
      { class: cls + (foldable ? " collapsed" : ""), id: "step-" + s.id },
      el("div", null, tick),
      el(
        "div",
        null,
        el(
          "div",
          { class: "step-head" },
          el("div", {
            class: "step-title" + (foldable ? " foldable" : ""),
            role: foldable ? "button" : null,
            tabindex: foldable ? "0" : null,
            title: foldable ? "点一下展开 / 收起" : null,
            onclick: foldable ? function () { item.classList.toggle("collapsed"); } : null,
            onkeydown: foldable ? function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); item.classList.toggle("collapsed"); } } : null,
          }, s.title, s.custom ? el("span", { class: "badge custom", text: "我加的" }) : null, s.auto_done ? el("span", { class: "badge", text: "材料齐了 · 自动完成" }) : null),
          menu
        ),
        el(
          "div",
          { class: "step-body" },
          el("div", { class: "step-meta" }, stepMeta(s)),
          windowLine(s, ctx.factsByKey, ctx.stepById),
          linksBlock(s, ctx.factsByKey),
          blocked,
          note ? note.node : null,
          rename ? rename.node : null,
          matsBlock,
          evidenceBlock(s.evidence, v.sources)
        )
      )
    );
    return item;
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
    // 预览页是只读的，没有上传按钮：提示要先"开始办"，免得让人以为这里就能传
    if (r.type_unresolved && ctx.readonly) {
      hints.push(el("div", { class: "mat-note", text: "这类材料没法自动对上材料库。开始办之后，可以在这里上传，或从我的资料里选一份。" }));
    } else if (ctx.readonly && r.state === "missing") {
      hints.push(el("div", { class: "mat-note", text: "开始办之后，可以在这里上传。" }));
    }
    if (r.state === "undecided") hints.push(el("div", { class: "mat-note", text: "取决于你的回答：" + conditionText(r.conditions, ctx.factsByKey) }));

    var note = ctx.readonly ? null : noteBlock(v, "requirements", r.id, r.user_note);
    var rename = !ctx.readonly && r.custom ? renameBlock(v, "/custom-materials/" + encodeURIComponent(r.id), "name", r.name) : null;
    var menu = null;
    if (!ctx.readonly) {
      var menuItems = [
        menuButton("备注", note.open),
        menuButton("隐藏", function () { update(v, "/hidden/requirements/" + encodeURIComponent(r.id), { hidden: true }); }),
      ];
      if (r.custom) {
        menuItems.push(menuButton("改名", rename.open));
        menuItems.push(confirmDeleteButton("删除", function () {
          return request("DELETE", "/api/tracks/" + encodeURIComponent(v.id) + "/custom-materials/" + encodeURIComponent(r.id));
        }));
      }
      menu = inlineActions(menuItems);
    }

    return el(
      "div",
      { class: "mat", id: id },
      el(
        "div",
        { class: "mat-top" },
        stateChip(displayState(r)),
        el("span", { class: "mat-name", text: r.name, title: r.raw_name && r.raw_name !== r.name ? "攻略原来写作「" + r.raw_name + "」" : null }),
        KIND_LABEL[r.kind] ? el("span", { class: "badge" + (r.kind === "generate" ? " ai" : ""), text: KIND_LABEL[r.kind] }) : null,
        r.optional ? el("span", { class: "badge", text: "加分项" }) : null,
        r.custom ? el("span", { class: "badge custom", text: "我加的" }) : null,
        menu
      ),
      r.note ? clampedNote(r.note) : null,
      note ? note.node : null,
      rename ? rename.node : null,
      hints,
      records,
      ctx.readonly ? null : matActions(r, v),
      evidenceBlock(r.evidence, v.sources)
    );
  }

  // 攻略给材料写的说明默认只显示一行，点一下展开 / 收起（说明往往很长，全部铺开字太多）
  function clampedNote(text) {
    var node = el("div", {
      class: "mat-note clamp", text: text, role: "button", tabindex: "0", title: "点一下展开 / 收起",
      "aria-expanded": "false",
    });
    function toggle() {
      var open = node.classList.toggle("open");
      node.setAttribute("aria-expanded", open ? "true" : "false");
    }
    node.addEventListener("click", toggle);
    node.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
    return node;
  }

  // 材料的操作收成一行小按钮：「上传文件」「从我的资料里选」，点了才展开对应的表单
  function matActions(r, v) {
    var upload = r.state === "missing" || r.state === "stale" ? uploadForm(r, v) : null;
    var pick = r.state !== "undecided" ? pickForm(r, v) : null;
    if (!upload && !pick) return null;
    var toggle = null;
    if (upload) {
      upload.hidden = true;
      toggle = el("button", {
        type: "button", class: "linkish", text: r.state === "stale" ? "上传新的一份" : "上传文件", "aria-expanded": "false",
        onclick: function () {
          upload.hidden = !upload.hidden;
          toggle.setAttribute("aria-expanded", upload.hidden ? "false" : "true");
        },
      });
    }
    // pickForm 自己带「从我的资料里选」切换按钮和展开的表单；把按钮挪到同一行，表单放在下面
    var pickToggle = pick ? pick.firstChild : null;
    return el(
      "div",
      { class: "mat-actions-wrap" },
      el("div", { class: "mat-actions" }, toggle, pickToggle),
      upload,
      pick
    );
  }

  var CATEGORY_NAME = { passport_scan: "证件", financial_snapshot: "财务", employment_doc: "工作", id_photo: "证件照", other: "其他" };

  function recordLabel(m) {
    return m.type + (m.sublabel ? "（" + m.sublabel + "）" : "") + " · " + (m.obtained_date || "未填日期");
  }

  // 自动识别没认出来时（例如签证页和盖章页扫在同一份 PDF 里），让用户自己从材料库里挑。
  // 组合材料每一部分各挑一份；挑过的类型会被记住，下次自动识别。
  function pickForm(r, v) {
    // 可选的只有：长期资料 + 这件办事自己的专用材料（别的办事的专用材料不出现）
    var usable = myRecords.filter(function (m) { return !m.for_track || m.for_track === v.id; });
    if (!usable.length) return null;
    var slots = r.parts.length ? r.parts : [{ key: r.material_type, name: r.name }];
    var toggleText = r.state === "ready" ? "换一份" : "从我的资料里选";
    var box = el("form", { class: "pick", hidden: true });
    var groups = {};
    usable.forEach(function (m) { (groups[m.category] = groups[m.category] || []).push(m); });
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
    // 长期资料 vs 本次专用：按词表规则预先勾好（证件、流水等长期材料勾上；行程单、邀请函等一次性材料不勾）
    var keepBox = el("input", { type: "checkbox", name: "keep" });
    keepBox.checked = !!r.default_keep;
    var keepLabel = el("label", { class: "keep", title: "勾上：放进「我的资料」，以后别的办事也能用；不勾：只属于这件办事" }, keepBox, " 放进我的资料（以后还会用）");
    var btn = el("button", { type: "submit", text: r.state === "stale" ? "上传新的一份" : "上传" });
    // 原生 append 会把 null 当成文字 "null" 插进去，所以先过滤掉不需要的控件
    [select, fileInput, el("label", null, "取得日期 ", dateInput), keepLabel, btn]
      .filter(Boolean)
      .forEach(function (node) { form.append(node); });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (!fileInput.files.length) return;
      var fd = new FormData();
      fd.set("file", fileInput.files[0]);
      if (dateInput.value) fd.set("obtained_date", dateInput.value);
      if (select) fd.set("part", select.value);
      fd.set("keep", keepBox.checked ? "true" : "false");
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
      var group = relevant.filter(function (r) { return displayState(r) === state; });
      if (!group.length) return;
      body.append(el("div", { class: "summary-group", text: (state === "optional" ? "加分项（没有也行）" : STATE_LABEL[state]) + " · " + group.length }));
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

  // 右侧核对清单：攻略里"材料之间必须对得上"的核对项 + 用户自己记的避坑点
  function reminderText(r) {
    return fmtDate(r.date) + (r.kind === "opens" ? " 起可以办：" : " 截止：") + r.title;
  }

  // 右侧"时间提醒"：以后开始可以办 / 截止的日子（spec §3c），可以导出成日历文件
  function remindersPanel(v) {
    var hasWindows = v.steps.some(function (s) { return s.window; });
    if (!hasWindows && !(v.reminders || []).length) return null;
    var list = (v.reminders || []).map(function (r) {
      return el(
        "li",
        { class: r.kind },
        el("span", { class: "when", text: fmtDate(r.date) }),
        el("span", null, (r.kind === "opens" ? "起可以办：" : "截止：") + r.title)
      );
    });
    return el(
      "section",
      { class: "panel reminders" },
      el("div", { class: "panel-head" }, el("h2", { text: "时间提醒" }), el("small", { text: list.length ? list.length + " 个日子" : "" })),
      list.length
        ? el("ul", null, list)
        : el("p", { class: "muted", text: "回答上面的日期问题后，这里会列出每项什么时候开始可以办、什么时候截止。" }),
      list.length
        ? el("a", {
            class: "link-btn", href: "/api/tracks/" + encodeURIComponent(v.id) + "/calendar.ics", download: v.id + ".ics",
            title: "下载 .ics 文件，用手机或电脑的日历打开即可导入；截止前 7 天会提醒",
            text: "📅 加到日历",
          })
        : null
    );
  }

  function checklistPanel(v, readonly) {
    var checks = v.checks.map(function (c) {
      var box = el("input", {
        type: "checkbox",
        id: "chk-" + c.id,
        disabled: readonly,
        onchange: function () { update(v, "/checks/" + encodeURIComponent(c.id), { done: box.checked }); },
      });
      box.checked = c.done;
      return el("label", { class: "check" + (c.done ? " done" : ""), for: "chk-" + c.id }, box, el("span", { text: c.text }));
    });

    var pits = (v.pitfalls || []).map(function (p) {
      var box = el("input", {
        type: "checkbox",
        id: "pit-" + p.id,
        onchange: function () { update(v, "/pitfalls/" + encodeURIComponent(p.id), { done: box.checked }); },
      });
      box.checked = p.done;
      return el(
        "div",
        { class: "check pit" + (p.done ? " done" : "") },
        box,
        el("label", { for: "pit-" + p.id, text: p.text }),
        el("button", {
          type: "button",
          class: "icon-btn",
          text: "×",
          "aria-label": "删除避坑点：" + p.text,
          onclick: function () {
            showError("");
            request("DELETE", "/api/tracks/" + encodeURIComponent(v.id) + "/pitfalls/" + encodeURIComponent(p.id))
              .then(drawTrack)
              .catch(function (e) { showError(e.message); });
          },
        })
      );
    });

    var addForm = null;
    if (!readonly) {
      var input = el("input", { type: "text", maxlength: "300", placeholder: "例如：流水要柜台打印并盖章", "aria-label": "新的避坑点" });
      addForm = el("form", { class: "pit-add" }, input, el("button", { type: "submit", text: "添加" }));
      addForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (!input.value.trim()) return;
        showError("");
        request("POST", "/api/tracks/" + encodeURIComponent(v.id) + "/pitfalls", { text: input.value })
          .then(drawTrack)
          .catch(function (e) { showError(e.message); });
      });
    }

    var doneCount = v.checks.filter(function (c) { return c.done; }).length + (v.pitfalls || []).filter(function (p) { return p.done; }).length;
    var total = v.checks.length + (v.pitfalls || []).length;
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "panel-head" }, el("h2", { text: "核对清单" }), total ? el("small", { text: doneCount + " / " + total }) : null),
      el(
        "div",
        { class: "checks" },
        checks.length ? [el("div", { class: "summary-group", text: "递交前核对（攻略）" }), checks] : null,
        el("div", { class: "summary-group", text: "我的避坑点" }),
        pits.length ? pits : el("p", { class: "muted", text: readonly ? "开始办之后，可以把自己从攻略里看到的坑记在这里。" : "看到攻略、帖子里提到的坑，随手记在这里。" }),
        addForm
      )
    );
  }

  // 点别处任何地方都把"再点一次删除"恢复原样（删除按钮第一次点击会 stopPropagation，不会跑到这里）
  document.addEventListener("click", closeAllMenus);

  document.getElementById("today").textContent = "今天 " + todayIso();
  // 抽屉里的 Agent 改了办事进度、或者点了撤销：正在看的就是那件办事时，重新读一遍（spec 004 第 3 步）
  window.addEventListener("agent-data-changed", function (e) {
    var m = location.hash.match(/^#\/track\/([^/?#]+)/);
    if (!m) return;
    var id = decodeURIComponent(m[1]);
    if (!e.detail.track_id || e.detail.track_id === id) renderTrack(id);
  });

  window.addEventListener("hashchange", function () {
    // 页内锚点（#step-xxx、#mat-xxx）只是滚动，不切换视图
    if (/^#(step|mat)-/.test(location.hash)) return;
    route();
  });
  route();
})();
