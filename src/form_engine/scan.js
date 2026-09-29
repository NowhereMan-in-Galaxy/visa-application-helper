// 通用填表引擎·扫描（specs/005-fill-engine）：列出页面上能填的格子，不读格子里的值。
// 用浏览器工具在官网页面里运行。浏览器工具一次只回传约 1000 字，所以结果压缩后放在
// window.__paScanText，这里只返回 {"chars", "parts"}；再用 window.__paScanText.slice(900*k, 900*(k+1))
// 逐段读回（k = 0..parts-1），原样拼起来交给 plan_form_fill。
(() => {
  const clip = (s, n) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const SKIP_TYPES = new Set(['hidden', 'password', 'file', 'checkbox', 'submit', 'button', 'reset', 'image', 'range', 'color']);
  const CAPTCHA = /captcha|验证码|verification code/i;

  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // 取一个元素的文字，去掉其中下拉框的选项文字
  const textOf = (node) => {
    if (!node) return '';
    const c = node.cloneNode(true);
    c.querySelectorAll('select, option, script, style').forEach((x) => x.remove());
    return clip(c.textContent, 100);
  };

  const byFor = (el) => (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);

  // 往前找最近的一段文字（表格布局、div 布局常见），遇到别的输入框就停
  const precedingText = (el) => {
    let node = el;
    for (let depth = 0; depth < 4 && node && node !== document.body; depth++) {
      let sib = node.previousElementSibling;
      for (let k = 0; k < 3 && sib; k++, sib = sib.previousElementSibling) {
        if (sib.matches('input, select, textarea') || sib.querySelector('input:not([type=hidden]), select, textarea')) return '';
        const t = textOf(sib);
        if (t) return t;
      }
      node = node.parentElement;
    }
    return '';
  };

  const labelOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return clip(aria, 100);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map((id) => textOf(document.getElementById(id))).join(' ');
      if (clip(t, 100)) return clip(t, 100);
    }
    const f = byFor(el);
    if (f && textOf(f)) return textOf(f);
    const wrap = el.closest('label');
    if (wrap && textOf(wrap)) return textOf(wrap);
    return precedingText(el);
  };

  // 单选组的问题：fieldset 的 legend，或者包住整组的容器前面的文字
  const groupQuestion = (radios) => {
    const fs = radios[0].closest('fieldset');
    if (fs && radios.every((r) => fs.contains(r))) {
      const lg = fs.querySelector('legend');
      if (lg && textOf(lg)) return textOf(lg);
    }
    let box = radios[0].parentElement;
    while (box && !radios.every((r) => box.contains(r))) box = box.parentElement;
    const aria = box && (box.getAttribute('aria-label') || '');
    return aria ? clip(aria, 100) : precedingText(box || radios[0]);
  };

  const headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, legend, [role=heading]')];
  const sectionOf = (el) => {
    let last = null;
    for (const h of headings) {
      if (h.contains(el)) continue;
      // fieldset 的 legend 只管它自己那一组，不当后面格子的小节标题
      if (h.tagName === 'LEGEND' && h.parentElement && !h.parentElement.contains(el)) continue;
      if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) last = h; else break;
    }
    return last ? textOf(last) : '';
  };

  const PART = 900;
  const sections = [];
  const sid = (el) => {
    const s = sectionOf(el);
    let k = sections.indexOf(s);
    if (k < 0) { sections.push(s); k = sections.length - 1; }
    return k;
  };
  // name 和 id 一样时只留一个；很长的控件编号只留末尾（有意义的部分在最后，例如 ..._tbxPPT_NUM）
  const identOf = (el) => {
    const n = el.name || '', id = el.id || '';
    const s = n.replace(/\$/g, '_') === id || !n ? id : !id ? n : `${n} ${id}`;
    return s.length > 50 ? s.slice(-50) : s;
  };
  // 改了会让页面刷新的下拉框（ASP.NET 的 __doPostBack）：计划里不自动填，交给用户手动选
  const postsBack = (el) => /__doPostBack/.test(el.getAttribute('onchange') || '');
  // 每个格子一行：[序号, 类型, 标签, 小节序号, 名字, 占位符, autocomplete, 已有内容, 会刷新页面]
  // 类型：t 文本 / d 日期 / a 多行文本 / s 下拉框 / r 单选组
  const fields = [];
  const seenRadio = new Set();
  let i = 0;
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (tag === 'input' && SKIP_TYPES.has(type)) continue;
    if (el.disabled || el.readOnly) continue;
    const ident = identOf(el);

    if (tag === 'input' && type === 'radio') {
      if (!el.name || seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
      const radios = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
      if (!radios.some((r) => visible(r) || visible(byFor(r)) || visible(r.closest('label')))) continue;
      const label = clip(groupQuestion(radios), 80);
      if (CAPTCHA.test(ident + label)) continue;
      radios.forEach((r) => r.setAttribute('data-pa-i', String(i)));
      fields.push([i++, 'r', label, sid(radios[0]), clip(el.name, 50), '', '', radios.some((r) => r.checked) ? 1 : 0]);
      continue;
    }

    if (!visible(el)) continue;
    const label = clip(labelOf(el), 80);
    const placeholder = clip(el.getAttribute('placeholder'), 40);
    if (CAPTCHA.test(ident + label + placeholder)) continue;
    const kind = tag === 'select' ? 's' : tag === 'textarea' ? 'a' : type === 'date' ? 'd' : 't';
    const filled = tag === 'select'
      ? el.selectedIndex > 0 && clip(el.options[el.selectedIndex].text, 40) !== ''
      : el.value.trim() !== '';
    el.setAttribute('data-pa-i', String(i));
    fields.push([i++, kind, label, sid(el), ident, placeholder, clip(el.getAttribute('autocomplete'), 30), filled ? 1 : 0,
      tag === 'select' && postsBack(el) ? 1 : 0]);
  }
  const text = JSON.stringify({ v: 1, host: location.host, sections: sections.map((x) => clip(x, 60)), f: fields });
  window.__paScanText = text;
  return JSON.stringify({ count: fields.length, chars: text.length, parts: Math.ceil(text.length / PART) });
})()
