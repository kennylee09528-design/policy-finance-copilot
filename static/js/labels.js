/* 代码 → 中文名：模块 M1~M5、来源等级 A1~C2、来源编号 S1…、M5 数据项 F1…
   页面渲染后自动把裸代码改为「中文名（代码）」，等级/编号加悬停说明；不改输入框、文本域、代码块与数据值。 */
const MODULE_NAMES = { M1: '财金协同知识库', M2: '今日行业 Brief', M3: '行业研究院', M4: '机构授信管理', M5: '机构看板' };
const LEVEL_NAMES = { A1: '官方正式文件', A2: '官方发布', B1: '权威媒体', B2: '一般媒体', C1: '自媒体', C2: '其他线索' };
const LEVEL_DESC = {
  A1: '政府部门/监管机构官网正式文件栏目（通知、办法、规划等原文）',
  A2: '政府部门/监管机构官网的其他栏目（新闻、解读、工作动态）',
  B1: '中央及权威财经媒体（新华社、人民日报、金融时报、经济日报、证券时报等）',
  B2: '一般媒体、门户网站',
  C1: '微信公众号等自媒体，仅作线索',
  C2: '未列入权威发布方规则的站点，仅作线索（默认不保留）',
};
function levelLabel(l) { return LEVEL_NAMES[l] ? `${LEVEL_NAMES[l]}（${l}）` : (l || '—'); }
function codeLegendHtml(kind) {
  const lv = Object.keys(LEVEL_NAMES).map(k => `<b>${k}</b> ${LEVEL_NAMES[k]}：${LEVEL_DESC[k]}`).join('；');
  const parts = [];
  if (!kind || kind.includes('level')) parts.push(`<div><b>来源等级</b>：${lv}。</div>`);
  if (!kind || kind.includes('cite')) parts.push('<div><b>来源编号</b>：S1、S2… 为本篇报告「资料清单」中的第 1、2… 份资料，正文句末 [S1] 表示该句出自 S1；'
    + 'F1、F2… 为 M5 机构看板台账数据项，正文中 [M5] 表示该数字由系统从台账填入；【待核实】表示系统内暂无可核实数据，需人工补充。</div>');
  if (!kind || kind.includes('module')) parts.push('<div><b>模块代码</b>：' + Object.entries(MODULE_NAMES).map(([k, v]) => `${k} ${v}`).join('；') + '。</div>');
  return `<details class="note-box mb code-legend"><summary>代码说明（点击展开）</summary>${parts.join('')}</details>`;
}
(function () {
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'CODE', 'PRE', 'SELECT']);
  const MOD_RE = /(^|[^A-Za-z0-9（(\-_.])M([1-5])(?![0-9A-Za-z）)\-_.])( ?)/g;  // 仅独立代码；模型名如 MiniMax-M3 不改
  const LV_RE = /(^|[^A-Za-z0-9（(·\-_.])([ABC][12])(?![0-9A-Za-z）)·\-_.])/g;
  function fixText(s, inOption) {
    let t = s;
    for (const [k, name] of Object.entries(MODULE_NAMES)) t = t.split(`${k} ${name}`).join(`${name}（${k}）`).split(`${k}${name}`).join(`${name}（${k}）`);
    t = t.replace(MOD_RE, (m, pre, n, sp) => `${pre}${MODULE_NAMES['M' + n]}（M${n}）${sp}`);
    if (inOption || /[\u4e00-\u9fa5]/.test(t)) t = t.replace(LV_RE, (m, pre, l) => `${pre}${l}·${LEVEL_NAMES[l]}`);
    return t;
  }
  function fixOptions(root) {
    const opts = root.tagName === 'OPTION' ? [root] : root.querySelectorAll ? root.querySelectorAll('option') : [];
    opts.forEach(o => { const v = fixText(o.textContent, true); if (v !== o.textContent) o.textContent = v; });
  }
  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { fixNode(root); return; }
    if (root.nodeType !== 1 || root.closest('[data-nolabel],textarea,pre,code')) return;
    if (root.tagName === 'OPTION' || root.tagName === 'SELECT') { fixOptions(root); return; }
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = []; let n; while ((n = tw.nextNode())) nodes.push(n);
    nodes.forEach(fixNode);
    fixOptions(root);
    tips(root);
  }
  function fixNode(n) {
    const p = n.parentElement;
    if (!p || SKIP.has(p.tagName) || p.closest('[data-nolabel],textarea,pre,code')) return;
    const s = n.nodeValue;
    if (!/[MABC][1-5]/.test(s)) return;
    const exact = s.trim();
    if (/^[ABC][12]$/.test(exact)) { n.nodeValue = s.replace(exact, levelLabel(exact)); p.title = LEVEL_DESC[exact]; return; }
    const v = fixText(s);
    if (v !== s) n.nodeValue = v;
  }
  function tips(root) {
    root.querySelectorAll('td,span,b').forEach(el => {
      if (el.children.length) return;
      const t = el.textContent.trim();
      if (/^S\d+$/.test(t)) el.title = `来源编号 ${t}：本篇「资料清单」第 ${t.slice(1)} 份资料；正文 [${t}] 表示该句出自此资料`;
      else if (/^F\d+$/.test(t)) el.title = `数据项 ${t}：机构看板（M5）台账数据，数值由系统填入`;
    });
  }
  let busy = false;
  const obs = new MutationObserver(muts => {
    if (busy) return; busy = true;
    try { muts.forEach(m => m.addedNodes.forEach(walk)); } finally { obs.takeRecords(); busy = false; }
  });
  document.addEventListener('DOMContentLoaded', () => { walk(document.body); obs.observe(document.body, { childList: true, subtree: true }); });
  if (document.readyState !== 'loading') { walk(document.body); obs.observe(document.body, { childList: true, subtree: true }); }
})();
