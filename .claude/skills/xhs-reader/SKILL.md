---
name: xhs-reader
description: 用户给出一条或几条小红书链接 / 分享文字（xhslink.cn 短链、带 xsec_token 的 explore 长链），想让 Agent 读取帖子正文和配图文字时使用；通常是为了接着用 guide-author 整理攻略。只在未登录的浏览器里读，一次最多 6 条。不用于读取收藏 / 喜欢列表、搜索、评论或任何需要登录的内容。
---

# 小红书帖子读取（不登录、小批量）

## 目标

把用户给的几篇小红书帖子读成"证据包"（标题、日期、正文、配图文字、读取情况），交给后续整理（通常是 `guide-author`）。
2026-09-28 试验 #7 验证过：5 条链接全部读到，没有登录，也不需要用户手动关弹窗。

## 硬性规则（不能因为"读不到"而放宽）

1. **不登录、不用用户的账号**。只在小红书未登录的浏览器里读；发现浏览器处于已登录状态（侧边栏没有"登录"按钮、能看到"我"）就立即停止，告诉用户，不继续读。
2. **不索取、不读取、不保存** Cookie、Token、密码、浏览器存储。
3. **一次最多 6 条**，由用户发起；逐条读，每条之间停 3–5 秒。不翻页、不搜索、不读评论、不做定时任务。
4. **遇到验证码、"安全限制""访问受限""请稍后重试"立即停止**，把已读到的结果交给用户，不重试、不绕过。
5. **配图里有证件、签证页、邮件截图等个人信息时**，只读流程和材料信息，不抄写任何人的姓名、证件号、邮箱、电话（官方机构的地址和公开邮箱除外）；拿不准就不读那张图，在结果里注明。

## 工具

使用 Claude Code 原装的 **Claude in Chrome**（`mcp__claude-in-chrome__*`）。其他 Agent 工具的适配见 `docs/BACKLOG.md`，本 skill 暂不覆盖。

## 步骤

1. **提取链接**：用户粘贴的分享文字里常夹着标题和 "Copy and open rednote…"，只取其中的 `https://xhslink.cn/...` 或 `https://www.xiaohongshu.com/explore/...?xsec_token=...` 网址。
   - **必须用分享出来的原链接**：去掉了 `xsec_token` 的 explore 链接在未登录时会显示"页面不见了"（错误码 300031）。仓库里 `sources[].url` 存的是净化后的链接，不能拿来重新读取。
2. **开一个新标签页**（`tabs_context_mcp` → 用给出的空白页或 `tabs_create_mcp`），依次对每条链接执行：
   1. `navigate` 到链接，等 4–5 秒。
   2. 用 `javascript_tool` 执行下面的脚本：关掉登录弹窗，确认未登录，取出正文。

      ```js
      const hadModal = !!document.querySelector('.login-modal.reds-modal-open');
      document.querySelector('.login-modal .close-button')?.click();
      await new Promise(r => setTimeout(r, 800));
      const q = s => document.querySelector(s);
      const imgs = [...new Set([...document.querySelectorAll('.note-slider img, .swiper-slide img, .media-container img')]
        .map(i => i.src).filter(s => s && !s.startsWith('data:')))];
      ({ url: location.href.split('?')[0], hadModal,
         modalStillOpen: !!q('.login-modal.reds-modal-open'),
         loginBtnVisible: /登录/.test(q('.side-bar')?.textContent || ''),
         title: q('#detail-title')?.innerText, desc: q('#detail-desc')?.innerText,
         date: q('.date')?.innerText, imgCount: imgs.length, imgs })
      ```

   3. 判断结果：
      - `loginBtnVisible` 为 false → 可能已登录，**停止**（规则 1）。
      - `modalStillOpen` 为 true 或 `title` 为空 → 截图看页面：弹窗没关掉就按截图位置点弹窗右上角的 ×；看到"页面不见了"、验证码或安全提示 → 记为读取失败，按规则 4 处理。页面结构变了导致选择器失效时，也用截图 + `get_page_text` 兜底，不要猜。
3. **读配图**：正文说"细节在图里"、或正文明显只是摘要时，才逐张看图：`navigate` 到脚本返回的图片地址（带时效签名，要在读完该帖子后马上用），全屏截图后读文字。
   - **图片编号**：脚本返回的顺序不一定等于帖子里的"图 1、图 2"。需要引用"图 N"时，以帖子轮播里的实际顺序为准（在帖子页面截图确认），不能直接用数组下标。
   - 读图前先想一下规则 5。
4. **全部读完后关掉标签页**（`tabs_close_mcp`）。

## 输出（给用户看，也作为 guide-author 的输入）

每篇一段：

- 标题 / 净化后的链接（`https://www.xiaohongshu.com/explore/<帖子 id>`，去掉 `xsec_token` 等参数）/ 发布或编辑日期
- 读取状态：成功 / 部分（哪些图没读、为什么）/ 失败（原因）
- 正文要点；读过的配图写"图 N：…"
- 最后一句汇总：有没有弹窗、是否自动关掉、有没有遇到验证码

不要自动保存到任何文件；要整理成攻略时交给 `guide-author`，它会按 `specs/002-guide-to-track/prompt.md` 第 20 条再次净化链接。
