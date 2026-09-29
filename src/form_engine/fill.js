// 通用填表引擎·填写（specs/005-fill-engine）：按计划填值、标黄框，只返回计数，不返回任何值。
// 文件最后一行的占位词由 plan_form_fill 换成具体的计划。先填文本框，再填下拉框和单选（它们可能触发页面刷新）。
((plan) => {
  const norm = (s) => (s || '').toLowerCase().replace(/[^0-9a-z一-鿿]+/g, ' ').trim();
  const clip = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const fire = (el, types) => types.forEach((t) => el.dispatchEvent(new Event(t, { bubbles: true })));
  const mark = (el) => {
    if (!el) return;
    el.style.outline = '2px dashed #d4a017';
    el.style.outlineOffset = '1px';
    el.title = '个人助手自动填写，请核对';
  };
  // 在若干选项里找候选写法：先找完全相同，再找"以候选开头"；只有唯一一项时才选
  const pick = (options, cands) => {
    const cs = cands.map(norm).filter(Boolean);
    for (const mode of ['exact', 'prefix']) {
      const hits = new Set();
      options.forEach((o, idx) => {
        const texts = [norm(o.text), norm(o.value)];
        for (const c of cs) {
          if (texts.some((t) => t && (mode === 'exact' ? t === c : t.startsWith(c + ' ')))) hits.add(idx);
        }
      });
      if (hits.size === 1) return [...hits][0];
      if (hits.size > 1) return -1;
    }
    return -1;
  };
  const radioText = (r) => {
    const f = r.id ? document.querySelector(`label[for="${CSS.escape(r.id)}"]`) : null;
    if (f) return clip(f.textContent);
    const w = r.closest('label');
    if (w) return clip(w.textContent);
    const n = r.nextSibling;
    return n ? clip(n.textContent) : '';
  };

  const out = { filled: 0, skipped: 0, gone: 0, already: 0 };
  const order = { text: 0, select: 1, radio: 2 };
  for (const op of [...plan].sort((a, b) => order[a.k] - order[b.k])) {
    const els = [...document.querySelectorAll(`[data-pa-i="${op.i}"]`)];
    if (!els.length) { out.gone++; continue; }
    const el = els[0];
    if (op.k === 'text') {
      if (el.value.trim() !== '') { out.already++; continue; }
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, op.v);
      fire(el, ['input', 'change', 'blur']);
      mark(el); out.filled++;
    } else if (op.k === 'select') {
      if (el.selectedIndex > 0 && clip(el.options[el.selectedIndex].text) !== '') { out.already++; continue; }
      const idx = pick([...el.options].map((o) => ({ text: o.text, value: o.value })), op.c);
      if (idx < 0) { out.skipped++; continue; }
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(el, el.options[idx].value);
      fire(el, ['input', 'change']);
      mark(el); out.filled++;
    } else if (op.k === 'radio') {
      if (els.some((r) => r.checked)) { out.already++; continue; }
      const idx = pick(els.map((r) => ({ text: radioText(r), value: r.value })), op.c);
      if (idx < 0) { out.skipped++; continue; }
      const r = els[idx];
      r.click();
      if (!r.checked) { r.checked = true; fire(r, ['change']); }
      mark(r.closest('label') || (r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`)) || r);
      out.filled++;
    }
  }
  return JSON.stringify(out);
})(__PLAN__)
