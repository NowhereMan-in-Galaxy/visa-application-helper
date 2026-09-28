// 通用填表引擎·扫描（specs/005-fill-engine）：列出页面上能填的格子，不读格子里的值。
// 用浏览器工具在官网页面里运行；返回 JSON 字符串，完整结果也放在 window.__paScan。
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

  // 单选项自己的文字（"Male" / "Yes"）
  const optionLabel = (r) => {
    const f = byFor(r);
    if (f && textOf(f)) return textOf(f);
    const wrap = r.closest('label');
    if (wrap && textOf(wrap)) return textOf(wrap);
    const next = r.nextSibling;
    if (next && next.nodeType === 3 && clip(next.textContent, 40)) return clip(next.textContent, 40);
    if (next && next.nodeType === 1) return textOf(next);
    return r.value || '';
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

  const fields = [];
  const seenRadio = new Set();
  let i = 0;
  for (const el of document.querySelectorAll('input, select, textarea')) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (tag === 'input' && SKIP_TYPES.has(type)) continue;
    if (el.disabled || el.readOnly) continue;
    const ident = `${el.name || ''} ${el.id || ''}`;

    if (tag === 'input' && type === 'radio') {
      if (!el.name || seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
      const radios = [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
      if (!radios.some((r) => visible(r) || visible(byFor(r)) || visible(r.closest('label')))) continue;
      const label = groupQuestion(radios);
      if (CAPTCHA.test(ident + label)) continue;
      radios.forEach((r) => r.setAttribute('data-pa-i', String(i)));
      fields.push({
        i: i++, kind: 'radio', label, name: clip(ident, 120), placeholder: '', autocomplete: '',
        options: radios.slice(0, 12).map((r) => clip(optionLabel(r), 40)),
        section: sectionOf(radios[0]), filled: radios.some((r) => r.checked),
      });
      continue;
    }

    if (!visible(el)) continue;
    const label = labelOf(el);
    const placeholder = clip(el.getAttribute('placeholder'), 60);
    if (CAPTCHA.test(ident + label + placeholder)) continue;
    const kind = tag === 'select' ? 'select' : tag === 'textarea' ? 'textarea' : type === 'date' ? 'date' : 'text';
    const filled = tag === 'select'
      ? el.selectedIndex > 0 && clip(el.options[el.selectedIndex].text, 40) !== ''
      : el.value.trim() !== '';
    el.setAttribute('data-pa-i', String(i));
    fields.push({
      i: i++, kind, label, name: clip(ident, 120), placeholder,
      autocomplete: clip(el.getAttribute('autocomplete'), 40), section: sectionOf(el), filled,
    });
  }
  const result = { host: location.host, title: clip(document.title, 80), count: fields.length, fields };
  window.__paScan = result;
  return JSON.stringify(result);
})()
