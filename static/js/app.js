/* 普惠业务工作台 · 前端核心（无框架，原生 JS） */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let ME = { role: 'internal', name: '', org: null };  // 当前登录身份（/api/auth/me）
const ident = () => ({ role: ME.role, org: ME.org || '', user: ME.name });

async function api(path, opt = {}) {
  const headers = Object.assign({}, opt.headers || {});
  if (opt.json !== undefined) { headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(opt.json); }
  const r = await fetch(path, Object.assign({}, opt, { headers, credentials: 'same-origin' }));
  if (!r.ok) {
    let msg = r.status + '';
    let detail = null;
    try {
      const j = await r.json();
      detail = j.detail;
      if (detail && typeof detail === 'object' && detail.message) msg = String(detail.message);
      else msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
    } catch (e) {}
    const err = new Error(msg);
    err.detail = detail;
    err.status = r.status;
    const needLogin = r.status === 401 || r.headers.get('X-App-Auth') === 'login-required';
    if (!opt.quiet && (needLogin || (r.status === 403 && /修改密码/.test(msg))) && !path.startsWith('/api/auth/') && !path.startsWith('/api/admin/')) { initIdentity(); throw err; }
    if (!opt.quiet) toast('⚠ ' + msg, 4000);
    throw err;
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r;
}
async function download(path, opt = {}) {
  const r = await api(path, opt);
  const cd = r.headers.get('content-disposition') || '';
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : 'download';
  const blob = await r.blob();
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function toast(msg, ms = 2200) { const t = $('#toast'); t.textContent = msg; t.style.display = 'block'; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', ms); }
function openModal(title, html) { $('#modalT').textContent = title; $('#modalB').innerHTML = html; $('#modal').classList.add('show'); }
function closeModal() { $('#modal').classList.remove('show'); }
// 数字格式：全局统一万元、2 位小数（Q5）
const f2 = v => (v === null || v === undefined || v === '' || isNaN(v)) ? '—' : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const f0 = v => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
const f4 = v => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(4);
const pct = v => (v === null || v === undefined || isNaN(v)) ? '—' : (v * 100).toFixed(2) + '%';
const sgn = v => (v === null || v === undefined || isNaN(v)) ? '—' : (v >= 0 ? '+' : '') + f2(v);
const yi = v => (v === null || v === undefined) ? '—' : (v / 10000).toFixed(2) + ' 亿';

const PAGES = {};
const PAGE_NAMES = { home: '工作台', m1: '财金协同知识库（M1）', m2: '今日行业 Brief（M2）', m3: '行业研究院（M3）', ppt: 'PPT 生成', m4: '机构授信管理（M4）',
  m5: '机构看板（M5）', inst: '机构主数据', selftest: '单机构自测', admin: '系统管理', audit: '操作留痕' };
function nav(page, sub) { location.hash = page + (sub ? '/' + sub : ''); }
async function route() {
  const [page, sub] = (location.hash.replace('#', '') || 'home').split('/');
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  $('#pageName').textContent = PAGE_NAMES[page] || '';
  const v = $('#view');
  if (page === 'selftest') { v.innerHTML = '<iframe class="legacy" src="/selftest" title="单机构自测"></iframe>'; return; }
  const fn = PAGES[page] || PAGES.home;
  v.innerHTML = '<div class="small">加载中…</div>';
  try { await fn(v, sub); } catch (e) { console.error(e); v.innerHTML = `<div class="alert error">页面加载失败：${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', route);
$$('.nav-item').forEach(b => b.addEventListener('click', () => nav(b.dataset.page)));

function subtabs(tabs, cur, base) {
  return `<div class="subtabs">${tabs.map(([k, t]) => `<button class="${k === cur ? 'active' : ''}" onclick="nav('${base}','${k}')">${t}</button>`).join('')}</div>`;
}
function alertsHtml(list) {
  if (!list || !list.length) return '';
  return `<div class="alerts">${list.map(a => `<div class="alert ${a.level === 'error' ? 'error' : a.level === 'info' ? 'info' : 'warn'}">${a.type ? '【' + esc(a.type) + '】' : ''}${esc(a.msg)}</div>`).join('')}</div>`;
}

/* ---------- 登录 / 身份（业务账号会话；系统管理员会话视为管理员角色） ---------- */
let AUTH = { kind: null };
async function initIdentity() {
  const r = await api('/api/auth/me');
  AUTH = r;
  if (!r.logged_in) { showLogin(); return false; }
  if (r.user.must_change) { showChangePw(true); return false; }
  $('#loginMask').classList.add('hidden');
  ME = r.user;
  const inst = ME.role === 'institution';
  $$('.nav-item[data-internal]').forEach(b => b.classList.toggle('hidden', inst));
  $('#meRole').textContent = ME.role_name + (r.kind === 'admin' ? '（管理员账号）' : '');
  $('#meName').textContent = (inst ? (ME.org || ME.name) : ME.name).slice(0, 12);
  $('#userBox').innerHTML = r.mode === 'header' ? '' : `${esc(ME.name)}${inst ? ' · ' + esc(ME.org || '') : ''} ${ME.role !== 'admin' ? '<a class="edit" onclick="feishuBindDialog()">绑定飞书</a><a class="edit" onclick="wechatBindDialog()">绑定微信</a>' : ''}<a class="edit" onclick="showChangePw(false)">修改密码</a><a class="edit" onclick="doLogout()">退出</a>`;
  return true;
}
function showLogin(msg) {
  $('#loginMask').classList.remove('hidden');
  $('#loginCard').innerHTML = `<div class="login-brand"><div class="brand-mark">示</div><div><h2>普惠业务工作台</h2><p class="small">请使用分配的账号登录（内部资料，注意保密）</p></div></div>
  ${msg ? `<div class="alert warn">${esc(msg)}</div>` : ''}
  <label>用户名<input class="in" id="li_u" autocomplete="username" autofocus></label>
  <label>密码<input class="in" id="li_p" type="password" autocomplete="current-password"></label>
  <button class="primary" id="li_ok" style="width:100%">登录</button>
  <p class="small" style="margin-top:12px">账号由系统管理员在「系统管理 → 用户与权限」中创建；首次登录须修改初始密码。系统管理员可直接使用管理员账号登录。</p>`;
  const go = async () => {
    const body = { username: $('#li_u').value.trim(), password: $('#li_p').value };
    try { await api('/api/auth/login', { method: 'POST', json: body, quiet: true }); }
    catch (e) {
      if (!/用户名或密码错误/.test(e.message)) return toast('⚠ ' + e.message, 4000);
      try { await api('/api/admin/login', { method: 'POST', json: body, quiet: true }); }
      catch (e2) { return toast('⚠ ' + (/次数过多/.test(e2.message) ? e2.message : e.message), 4000); }
    }
    if (await initIdentity()) route();
  };
  $('#li_ok').onclick = go; $('#li_u').onkeydown = $('#li_p').onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) go(); };
}
function showChangePw(forced) {
  $('#loginMask').classList.remove('hidden');
  $('#loginCard').innerHTML = `<h2 class="mb">${forced ? '首次登录：请修改初始密码' : '修改密码'}</h2>
  <label>原密码<input class="in" id="pw_o" type="password" autocomplete="current-password"></label>
  <label>新密码（至少 10 位，含字母与数字/符号）<input class="in" id="pw_n" type="password" autocomplete="new-password"></label>
  <label>确认新密码<input class="in" id="pw_n2" type="password" autocomplete="new-password"></label>
  <button class="primary" id="pw_ok">确认修改</button> ${forced ? '<button class="ghost" onclick="doLogout()">退出</button>' : `<button class="ghost" onclick="$('#loginMask').classList.add('hidden')">取消</button>`}`;
  $('#pw_ok').onclick = async () => {
    if ($('#pw_n').value !== $('#pw_n2').value) return toast('两次输入不一致');
    await api(AUTH.kind === 'admin' ? '/api/admin/password' : '/api/auth/password', { method: 'POST', json: { old: $('#pw_o').value, new: $('#pw_n').value } });
    toast('密码已修改'); if (await initIdentity()) route();
  };
}
async function doLogout() {
  await api('/api/auth/logout', { method: 'POST', quiet: true }).catch(() => {});
  await api('/api/admin/logout', { method: 'POST', quiet: true }).catch(() => {});
  ME = { role: 'internal', name: '', org: null }; $('#view').innerHTML = ''; showLogin();
}

/* ---------- PDF 导出：浏览器打印视图（带平铺水印与导出人信息），留痕并计入导出历史 ---------- */
function mdToHtml(md) {
  const inline = t => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  const out = []; let list = null;
  for (const line of String(md || '').split('\n')) {
    const h = /^(#{1,4})\s+(.*)$/.exec(line), li = /^\s*(?:[-*]|\d+[.、])\s+(.*)$/.exec(line);
    if (li) { if (!list) { list = []; } list.push(`<li>${inline(li[1])}</li>`); continue; }
    if (list) { out.push(`<ul>${list.join('')}</ul>`); list = null; }
    if (h) out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
    else if (/^>\s?/.test(line)) out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`);
    else if (/^---+$/.test(line.trim())) out.push('<hr>');
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`<ul>${list.join('')}</ul>`);
  return out.join('\n');
}
async function printView(module, target, filename, title, bodyHtml) {
  const w = window.open('', '_blank');
  if (!w) return toast('浏览器拦截了弹出窗口，请允许后重试');
  const r = await api('/api/exports/log', { method: 'POST', json: { module, target, filename } });
  const wm = r.watermark;
  const tile = encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200"><text x="20" y="120" transform="rotate(-24 180 100)" font-size="15" fill="rgba(160,160,160,0.22)" font-family="sans-serif">${esc(wm.who)} ${esc(wm.at)} 内部资料</text></svg>`);
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(filename)}</title><style>
   body{font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#1f2633;margin:0;padding:24px 32px;font-size:13px;line-height:1.7}
   .wm{position:fixed;inset:0;background:url("data:image/svg+xml,${tile}");pointer-events:none;z-index:9}
   .ph-head{display:flex;justify-content:space-between;border-bottom:2px solid #b3202f;padding-bottom:6px;margin-bottom:14px;font-size:11px;color:#888}
   .ph-head b{color:#b3202f;font-size:13px} h1{font-size:20px} h2{font-size:16px;border-left:4px solid #b3202f;padding-left:8px} table{border-collapse:collapse;width:100%;font-size:11px;margin:8px 0}
   th,td{border:1px solid #ddd;padding:3px 5px;text-align:right} th{background:#f6f1f1} td.l,th.l{text-align:left} img{max-width:100%} blockquote{color:#666;border-left:3px solid #ddd;margin:6px 0;padding-left:8px}
   .ph-foot{margin-top:18px;border-top:1px solid #ddd;padding-top:6px;font-size:10.5px;color:#999;text-align:center}
   button,.page-actions,.subtabs,.rec-tabs,.edit,input[type=checkbox],select{display:none!important} .tbl-wrap{overflow:visible!important;max-height:none!important}
   @media print{body{padding:0}@page{margin:14mm 12mm}}
  </style></head><body><div class="wm"></div><div class="ph-head"><span><b>${esc(title)}</b></span><span>${esc(wm.text)}</span></div>${bodyHtml}
  <div class="ph-foot">本文件由普惠业务工作台导出，仅限内部使用，请勿外传 · ${esc(wm.who)} · ${esc(wm.at)}</div>
  <script>setTimeout(()=>{window.print()},600)<\/script></body></html>`);
  w.document.close();
}
function cloneWithCharts(el) {  // 把 ECharts 画布转为图片，便于打印
  const c = el.cloneNode(true), src = el.querySelectorAll('canvas'), dst = c.querySelectorAll('canvas');
  src.forEach((cv, i) => { try { const img = document.createElement('img'); img.src = cv.toDataURL('image/png'); img.style.width = cv.style.width || cv.width + 'px'; dst[i].replaceWith(img); } catch (e) {} });
  return c.innerHTML;
}

/* ---------- 执行记录：归档 / 删除 / 回收站（各模块通用） ---------- */
const RV = {};  // kind -> '' | 'archived' | 'deleted'
const recQ = (kind, pre = '?') => RV[kind] ? pre + 'view=' + RV[kind] : '';
function recTabs(kind) {
  const v = RV[kind] || '';
  const tabs = [['', '当前'], ['archived', '已归档']].concat(ME.role === 'admin' ? [['deleted', '回收站']] : []);
  const batch = v === 'deleted' ? [['restore', '批量恢复'], ['purge', '批量彻底清除']] : v === 'archived' ? [['unarchive', '批量取消归档'], ['delete', '批量删除']] : [['archive', '批量归档'], ['delete', '批量删除']];
  return `<span class="rec-tabs" onclick="event.stopPropagation()">${tabs.map(([k, t]) => `<button class="${k === v ? 'active' : ''}" onclick="RV['${kind}']='${k}';route()">${t}</button>`).join('')}
   <span class="rec-batch">${batch.map(([a, t]) => `<button class="ghost mini" onclick="recBatch('${kind}','${a}')">${t}</button>`).join('')}</span></span>`;
}
const recCb = (kind, r) => r.can_manage ? `<input type="checkbox" class="rec-cb" data-kind="${kind}" value="${r.id}" onclick="event.stopPropagation()" title="勾选后可批量操作">` : '';
function recBtns(kind, r) {
  if (!r.can_manage) return '';
  const v = RV[kind] || '';
  const acts = r.deleted_at ? [['restore', '恢复'], ['purge', '彻底清除']] : r.archived_at ? [['unarchive', '取消归档'], ['delete', '删除']] : [['archive', '归档'], ['delete', '删除']];
  return `<span class="rec-acts" onclick="event.stopPropagation()">${(v === 'deleted' && ME.role !== 'admin') ? '' : acts.map(([a, t]) => `<a class="edit ${a === 'delete' || a === 'purge' ? 'danger' : ''}" onclick="recAct('${kind}','${a}',[${r.id}])">${t}</a>`).join('')}</span>`;
}
const recBadge = r => r.archived_at ? `<span class="pill gray" title="${esc(r.archived_by || '')} 于 ${esc(r.archived_at)} 归档">已归档</span>` : r.deleted_at ? `<span class="pill red" title="${esc(r.deleted_by || '')} 于 ${esc(r.deleted_at)} 删除">已删除</span>` : '';
function recBatch(kind, action) {
  const ids = $$(`.rec-cb[data-kind="${kind}"]:checked`).map(x => +x.value);
  if (!ids.length) return toast('请先勾选记录');
  recAct(kind, action, ids);
}
const REC_CONFIRM = { archive: n => `归档选中的 ${n} 条记录？归档后默认列表不显示，可在「已归档」中查看和恢复。`,
  unarchive: n => `取消归档 ${n} 条记录？`, delete: n => `删除 ${n} 条记录？\n删除后移入回收站（仅管理员可恢复或彻底清除），操作将记录在操作留痕中。`,
  restore: n => `从回收站恢复 ${n} 条记录？`, purge: n => `彻底清除 ${n} 条记录？\n此操作不可恢复（会同时删除附属数据，如 PPT 文件）。` };
async function recAct(kind, action, ids, force = false) {
  if (!force && !confirm(REC_CONFIRM[action](ids.length))) return;
  const r = await fetch(`/api/records/${kind}/${action}`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, force }) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 409 && j.detail && typeof j.detail === 'object') {
    const d = j.detail;
    const list = d.items.map(x => `<li><b>#${x.id} ${esc(x.title || '')}</b><ul>${x.reasons.map(s => `<li>${esc(s)}</li>`).join('')}</ul></li>`).join('');
    openModal(d.blocked ? '无法删除' : '删除前请确认引用关系', `<div class="alert ${d.blocked ? 'error' : 'warn'} mb">${esc(d.msg)}</div><ul class="ref-list">${list}</ul>
      ${d.blocked ? '<button class="secondary" onclick="closeModal()">知道了</button>' : `<button class="primary danger-btn" id="rec_force">仍然删除（移入回收站）</button> <button class="ghost" onclick="closeModal()">取消</button>`}`);
    if (!d.blocked) $('#rec_force').onclick = () => { closeModal(); recAct(kind, action, ids, true); };
    return;
  }
  if (!r.ok) return toast('⚠ ' + (typeof j.detail === 'string' ? j.detail : r.status), 4000);
  toast({ archive: '已归档', unarchive: '已取消归档', delete: '已删除（可由管理员在回收站恢复）', restore: '已恢复', purge: '已彻底清除' }[action] + `（${j.count} 条）`);
  if (typeof recAfter === 'function') recAfter(kind, action, ids);
  route();
}
let recAfter = (kind, action, ids) => {  // 删除/归档当前选中的记录后，清空各页面的选中项
  if (!['archive', 'delete', 'purge'].includes(action)) return;
  const sel = { m2_brief: typeof M2 !== 'undefined' && M2, m3_task: typeof M3T !== 'undefined' && M3T };
  const o = sel[kind]; if (o && ids.includes(o.id)) o.id = null;
};

/* ---------- 工作台 ---------- */
PAGES.home = async v => {
  const h = await api('/api/home');
  const inst = h.role === 'institution';
  const n = x => (x === null || x === undefined) ? '—' : f0(x);
  const card = (no, stage, mod, page, title, big, bigLabel, lines, tone) => `<div class="story-card ${tone || ''}" onclick="nav('${page}')" title="进入 ${esc(mod)}">
    <div class="story-no">${no}</div><div class="story-stage">${stage}<span>${mod}</span></div><h3>${title}</h3>
    <div class="story-big">${big}<small>${bigLabel}</small></div><ul>${lines.filter(Boolean).map(l => `<li>${l}</li>`).join('')}</ul></div>`;
  const m1 = h.m1 || {}, m2 = h.m2 || {}, m3 = h.m3 || {}, m4 = h.m4, m5 = h.m5, ppt = h.ppt || {};
  const rateTone = m5 && m5.rate != null ? (m5.rate >= 0.95 ? 'risk' : (m5.time_progress && m5.rate < m5.time_progress * 0.67 ? 'warn' : 'ok')) : '';
  const cards = inst ? [
    card('①', '资讯', 'M2', 'm2', '今日行业 Brief', n(m2.published), '期已发布', [m2.latest ? `最新：${esc(m2.latest.date)}（${m2.latest.items ?? 0} 条要闻）` : '暂无已发布简报']),
    card('②', '监控', 'M5', 'm5', '本机构额度使用', m5 ? esc(m5.stat_date) : '—', '最新统计时点', [m5 ? `时间进度 ${pct(m5.time_progress)}` : '尚无快照', m5 && m5.red ? `<b class="bad">本机构有 ${m5.red} 项红色预警</b>` : '', m5 && m5.yellow ? `进度滞后提示 ${m5.yellow} 项` : ''], m5 && m5.red ? 'risk' : ''),
  ] : [
    card('①', '采集', 'M1', 'm1', '财金协同知识库', n(m1.items), '条权威知识', [`A1/A2 部委与省级发布 ${n(m1.authority)} 条`, `近 7 天新增 ${n(m1.week)} 条`, `90 天内到期 ${n(m1.expiring)} 条`, m1.last_run ? `最近采集 ${esc(m1.last_run.started_at)} · ${esc(m1.last_run.status)}` : '尚未采集（可加载演示数据）']),
    card('②', '沉淀', 'M2', 'm2', '今日行业 Brief', n(m2.published), '期已发布', [m2.latest ? `最新：${esc(m2.latest.date)}（${m2.latest.items ?? 0} 条）` : '暂无已发布简报', `待发布草稿 ${n(m2.drafts)} 期`, '关键数字找不到原文即拦截']),
    card('③', '生产', 'M3 · PPT', 'm3', '研究写作与汇报', n(m3.final), '篇已定稿', [`写作任务 ${n(m3.tasks)} 个 · 引用登记 ${n(m3.citations)} 条`, `沉淀写作规范 ${n(m3.style)} 条`, `PPT ${n(ppt.files)} 个版本（${n(ppt.jobs)} 个任务）`]),
    card('④', '核算', 'M4', 'm4', '机构授信测算', m4 ? f0(m4.sumFinal) : '—', '万元 最终授信合计', [m4 ? `当前 v${m4.version}「${esc(m4.name)}」· ${esc(m4.status)}` : '请导入附件2', m4 ? `${m4.count} 家机构 · 人工调整 ${m4.adjustments} 笔留痕` : '', m4 ? `方案版本 ${m4.versions} 个，可对比回滚` : '']),
    card('⑤', '监控', 'M5', 'm5', '额度使用看板', m5 && m5.rate != null ? pct(m5.rate) : '—', '常规额度使用率', [m5 ? `统计时点 ${esc(m5.stat_date)} · 时间进度 ${pct(m5.time_progress)}` : '请上传国担台账', m5 ? `<b class="${m5.red ? 'bad' : ''}">红色预警 ${m5.red} 家</b> · 进度滞后 ${m5.yellow} 家` : '', m5 ? `系统预警 ${m5.alerts} 条` : ''], rateTone),
  ];
  v.innerHTML = `
  <div class="page-head"><div><h1>普惠业务工作台</h1><p>${inst ? '合作机构视图：查看本机构额度使用情况与已发布的行业简报。' : '一条数据主线：采集 → 沉淀 → 生产 → 核算 → 监控。M1 的权威资料支撑 M2 简报与 M3 写作；M4 测算出的授信额度流入 M5，按周监控使用进度。下列数字均为系统实时数据。'}</p></div>
  ${inst ? '' : `<div class="page-actions"><button class="primary" onclick="nav('m4')">进入授信测算</button><button class="secondary" onclick="nav('m5')">查看机构看板</button></div>`}</div>
  <div class="storyline ${inst ? 'two' : ''}">${cards.join('<div class="story-arrow">→</div>')}</div>
  ${inst ? '' : `<div class="dashboard-grid">
    <div class="panel"><div class="panel-head"><div><h2>演示路线（约 8 分钟）</h2><p>按顺序点击即可走完一条完整业务链；讲稿见 docs/demo_script.md</p></div></div><div class="panel-b demo-route">
      ${[['m1', '①', '知识库：看权威来源分级与 AI 要点（1 分钟）'], ['m2', '②', '今日 Brief：重要度分档、数字拦截、发布（1 分钟）'], ['m3', '③', '行业研究院：三 Agent 写作 → 标红核对 → 定稿（2 分钟）'], ['m4', '④', '授信测算：系数 → 人工调整留痕 → 版本对比 → 请示（1.5 分钟）'], ['m5', '⑤', '机构看板：四端口台账 → 预警 → 机构视角（1.5 分钟）'], ['ppt', '⑥', 'PPT：需求确认 → 大纲 → 原生图表 .pptx（1 分钟）']].map(([p, no, t]) => `<div class="task-row" style="cursor:pointer" onclick="nav('${p}')"><span class="type agent-type">${no}</span><div><strong>${t}</strong></div><em class="status done">进入</em></div>`).join('')}
    </div></div>
    <div class="panel"><div class="panel-head"><div><h2>快捷入口</h2></div></div>
      <div class="quick-grid">
        <button onclick="nav('m4','data')"><b>⇪</b><span>导入附件2</span></button>
        <button onclick="nav('m4','qingshi')"><b>✎</b><span>生成请示</span></button>
        <button onclick="nav('m2')"><b>⌁</b><span>今日简报</span></button>
        <button onclick="nav('ppt')"><b>▣</b><span>生成汇报 PPT</span></button>
        <button onclick="nav('admin','demo')"><b>⚙</b><span>演示数据与就绪</span></button>
      </div></div>
  </div>`}`;
};

/* ---------- M1/M2/M3：复用原型页面 ---------- */
function legacyPage(title, desc, tabs, cur, base, extra = '') {
  const t = tabs.find(x => x[0] === cur) || tabs[0];
  return `<div class="page-head"><div><h1>${title}</h1><p>${desc}</p></div><span class="demo-badge">一期为交互原型 · 真实采集/大模型链路下一阶段接入</span></div>
  ${extra}${tabs.length > 1 ? subtabs(tabs.map(x => [x[0], x[1]]), t[0], base) : ''}
  <iframe class="legacy" src="${t[2]}" title="${title}"></iframe>`;
}
PAGES.m1 = async (v, sub) => {
  sub = sub || 'collect';
  if (M1X[sub]) return M1X[sub](v);
  if (sub !== 'collect') sub = 'collect';  // 原型页（作品_网页 / 3.网站）已下线，未知子页回到采集列表
  const [cfg, runs, hist] = await Promise.all([api('/api/m1/config'), api('/api/m1/runs'), api('/api/m1/runs' + recQ('m1_run'))]);
  const f = M1F;
  const q = new URLSearchParams({ level: f.level || '', layer: f.layer || '', kw: f.kw || '', validity: f.validity || '' });
  const [d, exp] = await Promise.all([api('/api/m1/items?' + q), api('/api/m1/expiring?limit=30')]);
  const lastRun = runs.runs[0];
  v.innerHTML = `<div class="page-head"><div><h1>财金协同知识库（M1）</h1><p>搜索驱动采集：按「查询模板 × 主题 × 地域（国家 / 31 省 / 重点城市 / 广东各地市）」调用联网搜索 → 仅保留权威发布方（A1/A2/B1 等，规则可在系统管理中编辑）→ 抓取正文 → AI 要点摘要。</p></div>
   <div class="page-actions"><button class="secondary" onclick="nav('m1','manual')">补录政策</button><button class="primary" onclick="m1Run()" ${runs.running ? 'disabled' : ''}>${runs.running ? '采集中…' : '立即采集一轮'}</button></div></div>
  ${M1_TABS.length ? subtabs(M1_TABS.map(x => [x[0], x[1]]), 'collect', 'm1') : ''}
  ${typeof codeLegendHtml === 'function' ? codeLegendHtml('level') : ''}
  ${await modelPicker('m1', [['extract', '要点摘要/抽取'], ['embed', '语义检索向量模型（可选）']])}
  <div class="kv mb"><div><span>知识条目（去重后）</span><b>${Object.values(d.stats).reduce((a, b) => a + b, 0)}</b></div><div><span>等级分布</span><b style="font-size:13px">${Object.entries(d.stats).map(([k, n]) => k + ' ' + n).join(' · ') || '—'}</b></div>
   <div><span>下一轮检索</span><b>${cfg.plan_total} 次</b></div><div><span>定时采集</span><b style="font-size:14px">${cfg.config.schedule.enabled ? '每日 ' + esc(cfg.config.schedule.times.join('、')) : '未启用'}</b></div></div>
  ${lastRun ? `<div class="alert ${lastRun.status === '失败' ? 'error' : 'info'} mb">最近一轮 #${lastRun.id}（${esc(lastRun.trigger)}，${esc(lastRun.started_at)}）${esc(lastRun.status)}：检索 ${lastRun.stats.queries ?? 0} 次，结果 ${lastRun.stats.results ?? 0} 条，保留 ${lastRun.stats.kept ?? 0}，新增 ${lastRun.stats.new ?? 0}，非权威丢弃 ${lastRun.stats.dropped ?? 0}，抓取 ${lastRun.stats.fetched ?? 0}/失败 ${lastRun.stats.fetch_fail ?? 0}，AI 摘要 ${lastRun.stats.summarized ?? 0}${lastRun.log ? `<br><span class="small">${esc(lastRun.log.slice(0, 300))}</span>` : ''}</div>` : '<div class="alert info mb">尚未执行采集。请管理员先在「系统管理 · 联网搜索」配置 Tavily 或阿里云 IQS，然后点击「立即采集一轮」或开启定时采集。</div>'}
  <div class="panel mb"><div class="panel-head"><div><h2>即将到期（90天内）</h2><p>现行有效，且失效日期早于 ${esc(exp.cutoff)}（含已过期但仍标「现行有效」）。请人工核定；非现行有效的文件勿作决策依据。</p></div>
   <button class="secondary mini" onclick="M1F={...M1F,validity:'expiring'};route()">只看这些</button></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>失效日期</th><th>等级</th><th>标题</th><th>发布方</th><th>文号</th><th></th></tr></thead><tbody>
   ${exp.items.map(i => `<tr><td class="small">${esc(i.expiry_date)}${i.overdue ? ' <span class="pill red">已过期</span>' : ' <span class="pill gold">将到期</span>'}</td><td>${LV_PILL(i.level)}</td><td class="l" style="max-width:420px">${M1LINK(i.url, i.title)}</td><td class="l">${esc(i.publisher || '')}</td><td class="small">${esc(i.doc_no || '—')}</td><td><a class="edit" onclick="m1Item(${i.id})">核定</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">暂无。把条目标为「现行有效」并填写失效日期后，90 天内到期的会列在这里。</td></tr>'}
   </tbody></table></div></div>
  <div class="panel"><div class="panel-head"><div><h2>采集结果</h2></div><div class="form-row" style="margin:0">
   <select class="in" id="f_lv"><option value="">全部等级</option>${['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map(l => `<option ${f.level === l ? 'selected' : ''}>${l}</option>`).join('')}</select>
   <select class="in" id="f_ly"><option value="">全部层级</option>${['国家', '省级', '重点特殊财政管理城市', '普通地市'].map(l => `<option ${f.layer === l ? 'selected' : ''}>${l}</option>`).join('')}</select>
   <select class="in" id="f_val"><option value="">全部效力</option>${[['expiring', '即将到期（90天内）'], ['abolished', '已废止'], ['现行有效', '现行有效'], ['已失效', '已失效'], ['未知', '未知']].map(([k, n]) => `<option value="${k}" ${f.validity === k ? 'selected' : ''}>${n}</option>`).join('')}</select>
   <input class="in" id="f_kw" placeholder="关键词" value="${esc(f.kw || '')}"><button class="secondary mini" onclick="M1F={level:$('#f_lv').value,layer:$('#f_ly').value,kw:$('#f_kw').value,validity:$('#f_val').value};route()">筛选</button></div></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>等级</th><th>效力</th><th>标题</th><th>发布方</th><th>发布日期</th><th>层级/地域</th><th>主题</th><th>正文</th><th>要点</th><th></th></tr></thead><tbody>
  ${d.items.map(i => `<tr><td><span class="pill ${i.level === 'A1' ? 'red' : i.level === 'A2' ? 'gold' : 'blue'}">${i.level}</span>${i.level_manual ? '<span class="small">✎</span>' : ''}</td><td>${VAL_PILL(i.validity_status)}</td><td class="l" style="max-width:380px">${M1LINK(i.url, i.title)}${M1MANUAL(i)}</td>
   <td class="l">${esc(i.publisher)}</td><td>${esc(i.pub_date || '—')}</td><td class="small">${esc(i.layer)}·${esc(i.region)}</td><td class="small">${esc(i.topic)}</td><td class="small">${esc(i.fetch_status || '')}</td><td>${i.summary ? '✓' : ''}${i.cited ? ` <a class="pill blue" style="cursor:pointer" onclick="m1Cited(${i.id})" title="被 M3 写作引用">被引用 ${i.cited}</a>` : ''}</td><td><a class="edit" onclick="m1Item(${i.id})">详情</a></td></tr>`).join('') || '<tr><td colspan="10" class="small">暂无条目</td></tr>'}
  </tbody></table></div></div>
  <div class="panel mt"><div class="panel-head"><div><h2>采集记录</h2><p>每轮采集的执行日志（归档/删除只影响记录本身，不删除已采集的知识条目）</p></div>${recTabs('m1_run')}</div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>#</th><th>触发</th><th>开始</th><th>结束</th><th>状态</th><th>检索/保留/新增</th><th>发起人</th><th></th></tr></thead><tbody>
  ${hist.runs.map(x => `<tr><td>${recCb('m1_run', x)}</td><td>${x.id}</td><td>${esc(x.trigger)}</td><td class="small">${esc(x.started_at)}</td><td class="small">${esc(x.finished_at || '')}</td><td>${esc(x.status)} ${recBadge(x)}</td>
   <td>${x.stats.queries ?? 0} / ${x.stats.kept ?? 0} / ${x.stats.new ?? 0}</td><td class="small">${esc(x.created_by || '系统')}</td><td>${recBtns('m1_run', x)}</td></tr>`).join('') || '<tr><td colspan="9" class="small">暂无记录</td></tr>'}</tbody></table></div></div>`;
};
let M1F = {};
const M1H = (sub, desc) => `<div class="page-head"><div><h1>财金协同知识库（M1）</h1><p>${desc}</p></div></div>${subtabs(M1_TABS.map(x => [x[0], x[1]]), sub, 'm1')}`;
const LV_PILL = l => `<span class="pill ${l === 'A1' ? 'red' : l === 'A2' ? 'gold' : 'blue'}">${esc(l || '—')}</span>`;
const M1MANUAL = i => i && i.provider === 'manual' ? ' <span class="pill gray">补录</span>' : '';
const VAL_PILL = s => { const t = s || '未知'; const c = t === '现行有效' ? 'green' : (t === '已废止' || t === '已失效' ? 'red' : 'gray'); return `<span class="pill ${c}">${esc(t)}</span>`; };
async function m1Rag(q) {
  const box = $('#m1rag'); if (!box) return;
  const head = '<b>AI 回答</b> <span class="pill gold">AI 生成，仅供参考</span>';
  try {
    const a = await api('/api/m1/semantic/answer', { method: 'POST', json: { q } });
    if ($('#m1rag') !== box) return;
    const html = esc(a.answer).replace(/\n/g, '<br>').replace(/\[(\d+)\]/g, (m, n) => { const s = a.sources[n - 1]; return s ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" title="${esc(s.title)}">[${n}]</a>` : ''; });
    const bans = a.validity_notices || [];
    const banHtml = bans.length ? `<div class="alert warn mb">${bans.map(x => `${esc(x.notice)} <span class="small">（[${x.n}] ${esc(x.title || '')}）</span>`).join('<br>')}</div>` : '';
    box.innerHTML = `${head}${banHtml}<div class="mt mb" style="line-height:1.8">${html}</div>
     <div class="small"><b>参考条目</b>（仅依据以下知识库条目；[n] 点击打开原文）：${a.sources.map(s => `<div>[${s.n}] ${M1LINK(s.url, s.title)} <span class="small">${esc(s.publisher || '')} · ${esc(s.level || '')} · ${esc(s.pub_date || '—')}</span> ${VAL_PILL(s.validity_status)}${s.validity_notice ? ` <span class="small">${esc(s.validity_notice)}</span>` : ''} <a class="edit" onclick="m1Item(${s.id})">详情</a>${s.cited ? '' : ' <span class="small" style="color:var(--muted)">（未被引用）</span>'}</div>`).join('')}</div>
     <p class="small" style="color:var(--muted)">${a.covered ? '' : '知识库可能未覆盖该问题，请以原文为准。'}检索方式：${esc(a.method)}${a.model ? ' · 模型：' + esc(a.model) : ''}</p>`;
  } catch (e) { box.innerHTML = head + `<p class="small">AI 回答生成失败：${esc(e.message || e)}。下方检索结果不受影响。</p>`; }
}
const M1KB = { ly: '', kw: '', val: '', open: {} };
const M1LINK = (url, title) => /^https?:\/\//.test(url || '') ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="打开原文（新标签页）">${esc(title || url)}</a>` : `${esc(title || '')} <span class="small" style="color:var(--muted)">暂无原文链接</span>`;
async function m1KbToggle(id, a) {
  const tr = a.closest('tr').nextElementSibling;
  if (tr.style.display !== 'none') { tr.style.display = 'none'; a.textContent = '展开'; return; }
  const i = await api('/api/m1/items/' + id);
  $('td', tr).innerHTML = `${i.summary ? `<div class="note-box mb"><b>AI 要点（请对照原文核实）</b><br>${esc(i.summary).replace(/\n/g, '<br>')}</div>` : ''}<div class="small mb"><b>检索摘要：</b>${esc(i.snippet || '—')}</div><div class="small"><b>正文摘录（${esc(i.fetch_status || '')}）：</b></div><div class="small" style="white-space:pre-wrap;max-height:260px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px">${esc((i.content || '').slice(0, 3000)) || '—'}</div>`;
  tr.style.display = ''; a.textContent = '收起';
}
const M1X = {
  async kb(v) {
    const d = await api('/api/m1/items?' + new URLSearchParams({ layer: M1KB.ly, kw: M1KB.kw, validity: M1KB.val || '', limit: 1000 }));
    const by = {}; d.items.forEach(x => { by[x.layer || '其他'] = (by[x.layer || '其他'] || 0) + 1; });
    v.innerHTML = M1H('kb', '已入库的真实政策条目（均来自权威来源采集，标题点击在新标签页打开原文；「展开」查看要点/摘要/正文摘录）。') + `
    <div class="kv mb"><div><span>条目（去重后）</span><b>${d.items.length}</b></div><div><span>层级分布</span><b style="font-size:13px">${Object.entries(by).map(([k, n]) => k + ' ' + n).join(' · ') || '—'}</b></div></div>
    <div class="panel"><div class="panel-head"><div><h2>政策知识库</h2></div><div class="form-row" style="margin:0">
     <select class="in" id="kb_ly"><option value="">全部层级</option>${['国家', '省级', '重点特殊财政管理城市', '普通地市'].map(l => `<option ${M1KB.ly === l ? 'selected' : ''}>${l}</option>`).join('')}</select>
     <select class="in" id="kb_val"><option value="">全部效力</option>${[['expiring', '即将到期（90天内）'], ['abolished', '已废止'], ['现行有效', '现行有效'], ['已失效', '已失效'], ['未知', '未知']].map(([k, n]) => `<option value="${k}" ${M1KB.val === k ? 'selected' : ''}>${n}</option>`).join('')}</select>
     <input class="in" id="kb_kw" placeholder="关键词（标题/正文）" value="${esc(M1KB.kw)}"><button class="secondary mini" id="kb_go">检索</button></div></div>
    <div class="tbl-wrap"><table class="grid"><thead><tr><th>等级</th><th>效力</th><th>标题</th><th>发布方</th><th>发布日期</th><th>层级/地域</th><th></th></tr></thead><tbody>
    ${d.items.map(i => `<tr><td>${LV_PILL(i.level)}</td><td>${VAL_PILL(i.validity_status)}</td><td class="l" style="max-width:480px">${M1LINK(i.url, i.title)}${M1MANUAL(i)}</td><td class="l">${esc(i.publisher)}</td><td>${esc(i.pub_date || '—')}</td><td class="small">${esc(i.layer)}·${esc(i.region)}</td>
     <td style="white-space:nowrap"><a class="edit" onclick="m1KbToggle(${i.id},this)">展开</a><a class="edit" onclick="m1Item(${i.id})">详情</a></td></tr><tr style="display:none"><td colspan="7" class="l"></td></tr>`).join('') || '<tr><td colspan="7" class="small">暂无条目</td></tr>'}</tbody></table></div></div>`;
    const go = () => { M1KB.ly = $('#kb_ly').value; M1KB.kw = $('#kb_kw').value.trim(); M1KB.val = $('#kb_val').value; route(); };
    $('#kb_go').onclick = go; $('#kb_kw').onkeydown = e => { if (e.key === 'Enter') go(); };
  },
  async semantic(v) {
    const q = M1X.q || '';
    const r = q ? await api('/api/m1/semantic?' + new URLSearchParams({ q })) : null;
    v.innerHTML = M1H('semantic', '用一句话描述想找的政策（不必与原文用词一致）。配置了向量模型（系统管理或本页上方「语义检索向量模型」）时按语义相似度排序，否则按字面相近度排序。') + `
    <div class="panel panel-b mb"><div class="form-row" style="margin:0"><input class="in" id="sq" style="flex:1" placeholder="例如：对降低担保费率的机构有什么奖励政策" value="${esc(q)}"><button class="primary" onclick="M1X.q=$('#sq').value.trim();route()">检索</button></div></div>
    ${r ? `<div class="panel panel-b mb" id="m1rag"><b>AI 回答</b> <span class="pill gold">AI 生成，仅供参考</span><p class="small">正在根据知识库检索结果生成回答…</p></div>` : ''}
    ${r ? `<div class="small mb">检索方式：${esc(r.method)} · 命中 ${r.results.length} 条</div><div class="panel"><div class="tbl-wrap"><table class="grid"><thead><tr><th>相似度</th><th>等级</th><th>标题 / 摘要</th><th>发布方</th><th>发布日期</th><th></th></tr></thead><tbody>
    ${r.results.map(x => `<tr><td class="n">${(x.score * 100).toFixed(1)}</td><td>${LV_PILL(x.level)}</td><td class="l" style="max-width:560px">${M1LINK(x.url, x.title)}<br><span class="small">${esc(x.excerpt)}</span>${x.validity_notice ? `<div class="small">${VAL_PILL(x.validity_status)} ${esc(x.validity_notice)}</div>` : `<div class="small">${VAL_PILL(x.validity_status)}</div>`}</td><td class="l">${esc(x.publisher)}</td><td>${esc(x.pub_date || '—')}</td><td><a class="edit" onclick="m1Item(${x.id})">详情</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">无结果</td></tr>'}</tbody></table></div></div>` : ''}`;
    const i = $('#sq'); i.onkeydown = e => { if (e.key === 'Enter') { M1X.q = i.value.trim(); route(); } };
    if (r) m1Rag(q);
  },
  async health(v) {
    const rows = await api('/api/m1/sources/health');
    const cnt = s => rows.filter(x => x.status === s).length;
    v.innerHTML = M1H('health', '按发布方统计采集量、近 7 天新增、正文抓取失败率与最近发布日期，及时发现网站改版、反爬或长期不更新的来源。') + `
    <div class="kv mb"><div><span>来源数</span><b>${rows.length}</b></div><div><span>异常</span><b style="color:var(--red)">${cnt('异常')}</b></div><div><span>需关注</span><b style="color:var(--gold)">${cnt('关注')}</b></div><div><span>正常</span><b>${cnt('正常')}</b></div></div>
    <div class="panel"><div class="tbl-wrap"><table class="grid"><thead><tr><th>状态</th><th>发布方</th><th>域名</th><th>条目</th><th>近 7 天</th><th>抓取失败率</th><th>等级分布</th><th>最近发布</th><th>最近采集</th><th>提示</th></tr></thead><tbody>
    ${rows.map(x => `<tr><td><span class="pill ${x.status === '异常' ? 'red' : x.status === '关注' ? 'gold' : 'green'}">${x.status}</span></td><td class="l">${esc(x.publisher)}</td><td class="small l">${esc(x.domain || '')}</td><td class="n">${x.items}</td><td class="n">${x.week}</td>
     <td class="n ${x.fail_rate >= 0.5 ? 'bad' : ''}">${pct(x.fail_rate)}</td><td class="small">${Object.entries(x.levels).map(([k, n]) => k + '×' + n).join(' ')}</td><td class="small">${esc(x.last_pub || '—')}</td><td class="small">${esc(x.last_collected || '')}</td><td class="small l">${x.flags.map(esc).join('；')}</td></tr>`).join('') || '<tr><td colspan="10" class="small">暂无数据</td></tr>'}</tbody></table></div></div>`;
  },
  async review(v) {
    const d = await api('/api/m1/review');
    v.innerHTML = M1H('review', '自动挑出“低置信度”条目：正文未抓到、缺发布日期/发布方、来源等级低、无 AI 要点。同事补录的条目也会留在这里，直到人工确认。确认、改等级或标记为重复后移出队列，全程留痕。') + `
    <div class="kv mb"><div><span>待复核</span><b>${d.total}</b></div><div><span>已复核</span><b>${d.reviewed}</b></div></div>
    <div class="panel"><div class="tbl-wrap"><table class="grid"><thead><tr><th>等级</th><th>标题</th><th>发布方</th><th>发布日期</th><th>原因</th><th>复核</th></tr></thead><tbody>
    ${d.queue.map(x => `<tr><td>${LV_PILL(x.level)}</td><td class="l" style="max-width:420px">${M1LINK(x.url, x.title)}${x.uploaded_by ? `<div class="small">补录人：${esc(x.uploaded_by)}</div>` : ''}</td><td class="l">${esc(x.publisher || '—')}</td><td>${esc(x.pub_date || '—')}</td>
     <td class="small l">${x.reasons.map(r => `<span class="pill gold">${esc(r)}</span>`).join(' ')}</td>
     <td style="white-space:nowrap"><a class="edit" onclick="m1Rev(${x.id},'confirm')">确认无误</a><select class="in" style="width:70px;padding:2px" onchange="this.value&&m1Rev(${x.id},'level',this.value)"><option value="">改等级</option>${['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map(l => `<option>${l}</option>`).join('')}</select><a class="edit" onclick="m1Rev(${x.id},'duplicate')">标记重复</a><a class="edit" onclick="m1Item(${x.id})">详情</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">队列为空 👍</td></tr>'}</tbody></table></div></div>`;
  },
  async dedup(v) {
    const d = await api('/api/m1/dedup/sample?n=10');
    v.innerHTML = M1H('dedup', '从系统判定为“重复”的条目中随机抽样，人工核对是否真的重复，统计去重准确率；判为误判的条目自动恢复为独立条目。') + `
    <div class="kv mb"><div><span>系统判重条目</span><b>${d.total_duplicates}</b></div><div><span>已抽检</span><b>${d.checked}</b></div><div><span>判对</span><b>${d.correct}</b></div><div><span>去重准确率</span><b>${d.accuracy == null ? '—' : pct(d.accuracy)}</b></div><div><span>未抽检</span><b>${d.unchecked}</b></div></div>
    <div class="panel"><div class="panel-head"><div><h2>本次抽样（${d.sample.length}）</h2></div><button class="secondary mini" onclick="route()">换一批</button></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>被判重条目</th><th>原条目</th><th>判定</th></tr></thead><tbody>
    ${d.sample.map(x => `<tr><td class="l" style="max-width:420px"><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a><br><span class="small">${esc(x.publisher || '')} · ${esc(x.pub_date || '')}</span></td>
     <td class="l" style="max-width:420px"><a href="${esc(x.o_url)}" target="_blank" rel="noopener noreferrer">${esc(x.o_title)}</a><br><span class="small">${esc(x.o_publisher || '')} · ${esc(x.o_pub_date || '')}</span></td>
     <td style="white-space:nowrap"><button class="secondary mini" onclick="m1Dedup(${x.id},'correct',this)">确实重复</button> <button class="ghost mini" onclick="m1Dedup(${x.id},'wrong',this)">误判</button></td></tr>`).join('') || '<tr><td colspan="3" class="small">没有待抽检的判重条目</td></tr>'}</tbody></table></div></div>`;
  },
  async manual(v) {
    const picker = await modelPicker('m1', [['extract', '要点摘要/抽取（链接摘要与文件预填）'], ['embed', '语义检索向量模型（可选）']]);
    const tab = M1MAN.tab === 'file' ? 'file' : 'url';
    const f = M1MAN.fields || {};
    const s = M1MAN.sugg || {};
    const val = k => (f[k] != null && f[k] !== '') ? f[k] : (s[k] || '');
    const levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
    const lv = val('level');
    v.innerHTML = M1H('manual', '内部同事自行补录政策。链接走现有抓取、清洗、分级和要点摘要；PDF / Word 先抽正文，再由模型预填元数据，可改后入库。效力默认为「未知」，成功后进入列表和待复核。') + picker + `
    <div class="subtabs">
      <button class="${tab === 'url' ? 'active' : ''}" onclick="m1ManualRead();M1MAN.tab='url';route()">粘贴链接</button>
      <button class="${tab === 'file' ? 'active' : ''}" onclick="m1ManualRead();M1MAN.tab='file';route()">上传文件</button>
    </div>
    ${tab === 'url' ? `<div class="panel"><div class="panel-head"><div><h2>粘贴政策链接</h2><p>只采集这一条，不跑整轮搜索。重复链接会拒绝并告知已有条目编号。PDF 链接不解析正文，请改用上传文件。</p></div></div>
      <div class="form-row"><label style="flex:1">政策原文链接<input class="in" id="mu_url" placeholder="https://" value="${esc(M1MAN.url || '')}"></label></div>
      <div class="form-row"><label><span><input type="checkbox" id="mu_allow" ${M1MAN.allowUrl ? 'checked' : ''}> 标题相同仍入库（标记为疑似重复，默认列表不显示）</span></label>
      <button class="primary" id="mu_go">采集并入库</button></div></div>` : `<div class="panel"><div class="panel-head"><div><h2>上传 PDF 或 Word</h2><p>支持 .pdf 与 .docx。扫描件若抽不出文字会直接失败，不会当成成功。请先在上方选择「要点摘要」模型；未配置时仍可手工填写。</p></div></div>
      ${M1MAN.llmWarning ? `<div class="alert warn mb">${esc(M1MAN.llmWarning)}</div>` : ''}
      <div class="form-row"><label>文件<input class="in" id="mf_file" type="file" accept=".pdf,.docx,application/pdf"></label>
      <span class="small" id="mf_name">${M1MAN.fileName ? '已选：' + esc(M1MAN.fileName) : '未选择文件'}</span>
      <button class="secondary" id="mf_preview">解析并预填</button></div>
      <div class="form-row"><label style="flex:1">标题<input class="in" id="mf_title" value="${esc(val('title'))}"></label>
      <label style="flex:1">发布机构<input class="in" id="mf_pub" value="${esc(val('publisher'))}"></label></div>
      <div class="form-row"><label>文号<input class="in" id="mf_doc" value="${esc(val('doc_no'))}"></label>
      <label>发布日期<input class="in" id="mf_date" type="date" value="${esc(val('pub_date'))}"></label>
      <label>来源等级<select class="in" id="mf_lv"><option value="">请选择</option>${levels.map(l => `<option ${l === lv ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      ${s.level ? `<span class="small">模型建议 ${esc(s.level)}；若改选其他等级，将记为人工覆盖</span>` : ''}</div>
      <div class="form-row"><label style="flex:1">要点<textarea class="in" id="mf_sum" style="min-height:90px">${esc(val('summary'))}</textarea></label></div>
      <div class="form-row"><label style="flex:1">原文链接（可选，用于去重）<input class="in" id="mf_url" placeholder="https://" value="${esc(val('url'))}"></label></div>
      <div class="form-row"><label><span><input type="checkbox" id="mf_allow" ${M1MAN.allowFile ? 'checked' : ''}> 标题相同仍入库（标记为疑似重复，默认列表不显示）</span></label>
      <button class="primary" id="mf_go">确认入库</button></div>
      ${M1MAN.previewText ? `<h3 class="small">正文预览（已清洗，共 ${M1MAN.chars || M1MAN.previewText.length} 字）</h3><div class="small" style="white-space:pre-wrap;max-height:220px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px">${esc(M1MAN.previewText)}</div>` : ''}
    </div>`}`;
    if ($('#mu_go')) $('#mu_go').onclick = () => m1ManualUrl();
    if ($('#mu_url')) $('#mu_url').onkeydown = e => { if (e.key === 'Enter') m1ManualUrl(); };
    if ($('#mf_file')) $('#mf_file').onchange = () => {
      M1MAN_FILE = $('#mf_file').files[0] || null;
      M1MAN.fileName = M1MAN_FILE ? M1MAN_FILE.name : '';
      M1MAN.sugg = null; M1MAN.previewText = ''; M1MAN.llmWarning = ''; M1MAN.fields = {}; M1MAN.chars = 0;
      route();
    };
    if ($('#mf_preview')) $('#mf_preview').onclick = () => m1ManualPreview();
    if ($('#mf_go')) $('#mf_go').onclick = () => m1ManualSave();
  },
};
async function m1Rev(id, action, level) {
  const body = { action };
  if (action === 'level') body.level = level;
  if (action === 'duplicate') { const o = prompt('与哪个条目重复？请输入原条目编号（详情窗口标题处可见 #编号）'); if (!o) return; body.duplicate_of = +o; }
  await api(`/api/m1/items/${id}/review`, { method: 'POST', json: body }); toast('已复核'); route();
}
async function m1Dedup(id, verdict, btn) { await api('/api/m1/dedup/' + id, { method: 'POST', json: { verdict } }); btn.closest('tr').style.opacity = .4; btn.closest('td').innerHTML = verdict === 'correct' ? '✓ 确实重复' : '✗ 误判（已恢复）'; }
async function m1Cited(id) {
  const rows = await api(`/api/m1/items/${id}/citations`);
  openModal('被引用情况', `<p class="small mb">该条目在 M3 引用来源登记表中被登记 ${rows.length} 次：</p><table class="grid"><thead><tr><th>文稿</th><th>写作任务</th><th>位置</th><th>核验</th><th>时间</th></tr></thead><tbody>
  ${rows.map(r => `<tr><td class="l">${esc(r.doc_name || '')}</td><td class="l">${r.task_id ? `<a class="edit" onclick="closeModal();M3T.id=${r.task_id};nav('m3')">#${r.task_id} ${esc(r.task_title || '')}</a>` : '—'}</td><td class="small">${esc(r.location || '')}</td><td class="small">${esc(r.verify_status || '')}</td><td class="small">${esc(r.created_at || '')}</td></tr>`).join('')}</tbody></table>`);
}
const M1_TABS = [['collect', '搜索采集', ''], ['manual', '补录政策', ''], ['semantic', '语义检索', ''], ['health', '来源健康', ''], ['review', '待复核', ''], ['dedup', '去重抽检', ''], ['kb', '政策知识库', '']];
async function m1Run() { await api('/api/m1/run', { method: 'POST' }); toast('采集已开始，完成后刷新查看'); setTimeout(route, 1500); }
let M1MAN = { tab: 'url', url: '', allowUrl: false, allowFile: false, fileName: '', sugg: null, fields: {}, llmWarning: '', previewText: '', chars: 0 };
let M1MAN_FILE = null;
function m1ManualRead() {
  if ($('#mu_url')) { M1MAN.url = $('#mu_url').value; M1MAN.allowUrl = $('#mu_allow').checked; }
  if ($('#mf_title')) {
    M1MAN.fields = { title: $('#mf_title').value, publisher: $('#mf_pub').value, doc_no: $('#mf_doc').value, pub_date: $('#mf_date').value, summary: $('#mf_sum').value, level: $('#mf_lv').value, url: $('#mf_url').value };
    M1MAN.allowFile = $('#mf_allow').checked;
  }
}
function m1ManualDone(r) {
  const warn = (r && r.warning) || '';
  toast(warn || '已补录，已进入待复核', 4000);
  const dup = r && r.item && r.item.duplicate_of;
  M1MAN.sugg = null; M1MAN.fields = {}; M1MAN.previewText = ''; M1MAN.llmWarning = ''; M1MAN.fileName = ''; M1MAN.chars = 0; M1MAN_FILE = null;
  if (dup) route(); else nav('m1', 'review');
}
async function m1ManualUrl() {
  m1ManualRead();
  const r = await api('/api/m1/manual/url', { method: 'POST', json: { url: (M1MAN.url || '').trim(), allow_title_dup: !!M1MAN.allowUrl } });
  m1ManualDone(r);
}
async function m1ManualPreview() {
  m1ManualRead();
  if (!M1MAN_FILE) { toast('请先选择 PDF 或 Word（.docx）'); return; }
  const keepUrl = (M1MAN.fields || {}).url || '';
  const fd = new FormData(); fd.append('file', M1MAN_FILE);
  const r = await api('/api/m1/manual/preview', { method: 'POST', body: fd });
  M1MAN.sugg = r.suggestions || {};
  M1MAN.fields = Object.assign({ url: keepUrl }, r.suggestions || {});
  M1MAN.llmWarning = r.llm_warning || '';
  M1MAN.previewText = r.text || '';
  M1MAN.chars = r.chars || 0;
  M1MAN.tab = 'file';
  route();
}
async function m1ManualSave() {
  m1ManualRead();
  if (!M1MAN_FILE) { toast('请先选择 PDF 或 Word（.docx）'); return; }
  const f = M1MAN.fields || {};
  const fd = new FormData();
  fd.append('file', M1MAN_FILE);
  const suggLv = (M1MAN.sugg || {}).level || '';
  for (const [k, v] of Object.entries({ title: f.title, publisher: f.publisher, doc_no: f.doc_no, pub_date: f.pub_date, summary: f.summary, level: f.level, url: f.url, suggested_level: suggLv, allow_title_dup: M1MAN.allowFile ? 'true' : 'false' })) fd.append(k, v || '');
  const r = await api('/api/m1/manual/file', { method: 'POST', body: fd });
  m1ManualDone(r);
}
async function m1Item(id) {
  const i = await api('/api/m1/items/' + id);
  const urlLine = /^https?:\/\//.test(i.url || '') ? `<a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.url)}</a>` : '暂无原文链接';
  const who = i.provider === 'manual'
    ? `同事补录${i.uploaded_by ? ' · 上传人 ' + esc(i.uploaded_by) : ''}${i.source_filename ? ' · 原文件 ' + esc(i.source_filename) : ''}`
    : `检索词：${esc(i.query)} · 搜索：${esc(i.provider)}`;
  openModal('#' + i.id + ' ' + (i.title || '条目'), `<p class="small mb">${urlLine}<br>发布方：${esc(i.publisher)} · 发布日期：${esc(i.pub_date || '—')} · ${who} · 采集：${esc(i.collected_at)}</p>
  <div class="note-box mb"><b>政策效力</b>（人工核定，不自动抽取失效日）${i.validity_notice ? `<br><b>${esc(i.validity_notice)}</b>` : '<br>现行有效'}
  ${i.validity_updated_at ? `<br><span class="small">上次核定：${esc(i.validity_updated_by || '')} ${esc(i.validity_updated_at)}</span>` : ''}</div>
  <div class="form-row"><label>效力状态<select class="in" id="it_vs">${['现行有效', '已废止', '已失效', '未知'].map(s => `<option ${(i.validity_status || '未知') === s ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
   <label>文号<input class="in" id="it_doc" value="${esc(i.doc_no || '')}"></label>
   <label>生效日期<input class="in" id="it_eff" type="date" value="${esc(i.effective_date || '')}"></label>
   <label>失效日期<input class="in" id="it_exp" type="date" value="${esc(i.expiry_date || '')}"></label>
   <label>废止日期<input class="in" id="it_abo" type="date" value="${esc(i.abolished_at || '')}"></label></div>
  <div class="form-row"><label style="flex:1">替代文件<input class="in" id="it_sup" value="${esc(i.superseded_by || '')}" placeholder="标题或文号，不自动关联"></label>
   <label style="flex:1">备注<input class="in" id="it_note" value="${esc(i.validity_note || '')}"></label><button class="secondary mini" id="it_val">保存效力</button></div>
  <div class="form-row"><label>来源等级（人工可改）<select class="in" id="it_lv">${['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map(l => `<option ${l === i.level ? 'selected' : ''}>${l}</option>`).join('')}</select></label><label style="flex:1">修改原因<input class="in" id="it_rs"></label><button class="secondary mini" id="it_save">保存等级</button>
  <button class="secondary mini" id="it_ref">重新抓取正文</button><button class="secondary mini" id="it_sum">AI 提炼要点</button></div>
  ${i.summary ? `<div class="note-box mb"><b>AI 要点（请对照原文核实）</b><br>${esc(i.summary).replace(/\n/g, '<br>')}</div>` : ''}
  <h3 class="small">检索摘要</h3><p class="small mb">${esc(i.snippet || '')}</p><h3 class="small">正文（${esc(i.fetch_status || '')}）</h3><div class="small" style="white-space:pre-wrap;max-height:300px;overflow:auto;background:var(--bg);padding:8px;border-radius:8px">${esc((i.content || '').slice(0, 8000))}</div>`);
  $('#it_save').onclick = async () => { await api('/api/m1/items/' + id, { method: 'PUT', json: { level: $('#it_lv').value, reason: $('#it_rs').value } }); toast('已保存'); closeModal(); route(); };
  $('#it_val').onclick = async () => {
    await api('/api/m1/items/' + id + '/validity', { method: 'PUT', json: { validity_status: $('#it_vs').value, doc_no: $('#it_doc').value, effective_date: $('#it_eff').value, expiry_date: $('#it_exp').value, abolished_at: $('#it_abo').value, superseded_by: $('#it_sup').value, validity_note: $('#it_note').value } });
    toast('效力已保存'); closeModal(); route();
  };
  $('#it_ref').onclick = async () => { await api(`/api/m1/items/${id}/refetch`, { method: 'POST' }); m1Item(id); };
  $('#it_sum').onclick = async () => { await api(`/api/m1/items/${id}/summarize`, { method: 'POST' }); m1Item(id); };
}
PAGES.m3 = async (v, sub) => {
  sub = sub || 'tasks';
  const tabs = [['tasks', '写作任务（三 Agent）'], ['style', '写作规范库'], ['research', '公开资料联网检索 · 引用登记']];
  const picker = await modelPicker('m3', [['writer', '研究及写作 Agent'], ['checker', '核对 Agent'], ['summarizer', '总结 Agent']]);
  if (sub !== 'research') return m3Page(v, sub, tabs, picker);
  const cits = await api('/api/m3/citations' + (M3.doc ? '?doc_name=' + encodeURIComponent(M3.doc) : ''));
  v.innerHTML = `<div class="page-head"><div><h1>行业研究院（M3）</h1><p>公开资料须经联网检索并登记出处后方可入稿（需求 5.4 / Q1）：检索结果自带 标题 · 链接 · 发布日期 · 来源等级，一键登记进《引用来源登记表》。</p></div></div>
  ${picker}${subtabs(tabs.map(x => [x[0], x[1]]), 'research', 'm3')}
  <div class="panel panel-b mb"><div class="form-row"><label style="flex:1">检索词<input class="in" id="m3q" placeholder="例如：广东 政府性融资担保 风险补偿 2026" value="${esc(M3.q || '')}"></label>
   <label>时间范围<select class="in" id="m3tr">${[['none', '不限'], ['year', '一年内'], ['month', '一月内'], ['week', '一周内']].map(([k, n]) => `<option value="${k}" ${M3.tr === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
   <label>所属稿件<input class="in" id="m3doc" placeholder="稿件名称" value="${esc(M3.doc || '')}"></label><button class="primary" onclick="m3Search()">联网检索</button></div><div id="m3res"></div></div>
  <div class="panel"><div class="panel-head"><div><h2>引用来源登记表${M3.doc ? '：' + esc(M3.doc) : '（全部）'}</h2><p>出处位置、原文摘录、核验状态需人工核对后填写；「存疑/未找到出处」的引用不得进入终稿。</p></div>
   <button class="secondary mini" onclick="download('/api/m3/citations/export.xlsx${M3.doc ? '?doc_name=' + encodeURIComponent(M3.doc) : ''}')">导出 Excel</button></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>#</th><th>稿件</th><th>来源名称</th><th>类型</th><th>出处位置</th><th>原文摘录</th><th>链接</th><th>发布日期</th><th>核验状态</th><th></th></tr></thead><tbody>
   ${cits.map((c, i) => `<tr data-id="${c.id}"><td>${i + 1}</td><td class="small">${esc(c.doc_name || '')}</td><td class="l" title="${esc(c.title)}">${esc(c.source_name || c.title)}</td><td>${esc(c.level || '')}</td>
    <td><input class="in c_loc" value="${esc(c.location || '')}" style="width:90px"></td><td><input class="in c_ex" value="${esc(c.excerpt || '')}" style="width:200px"></td>
    <td class="l"><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a></td><td>${esc(c.pub_date || '')}</td>
    <td><select class="in c_vs">${['已核实', '存疑（待核实）', '未找到出处'].map(s => `<option ${s === c.verify_status ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
    <td><a class="edit" onclick="m3SaveCit(this)">保存</a><a class="edit" onclick="m3DelCit(${c.id})">删除</a></td></tr>`).join('') || '<tr><td colspan="10" class="small">暂无登记</td></tr>'}</tbody></table></div></div>`;
};
const M3 = { res: [] };
async function m3Search() {
  M3.q = $('#m3q').value; M3.tr = $('#m3tr').value; M3.doc = $('#m3doc').value;
  $('#m3res').innerHTML = '<p class="small">检索中…</p>';
  try { const r = await api('/api/m3/search', { method: 'POST', json: { query: M3.q, time_range: M3.tr, max_results: 10 } }); M3.res = r.results; }
  catch (e) { $('#m3res').innerHTML = ''; return; }
  $('#m3res').innerHTML = `<table class="grid"><thead><tr><th>等级</th><th>标题</th><th>发布方</th><th>日期</th><th>摘要</th><th></th></tr></thead><tbody>${M3.res.map((x, i) => `<tr><td><span class="pill ${['A1', 'A2'].includes(x.level) ? 'red' : x.level === 'B1' ? 'blue' : 'gray'}">${x.level}</span></td>
   <td class="l" style="max-width:320px"><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a></td><td class="l">${esc(x.publisher)}</td><td>${esc(x.date || '—')}</td><td class="l small" style="max-width:360px" title="${esc(x.snippet)}">${esc(x.snippet)}</td>
   <td><a class="edit" onclick="m3Cite(${i})">登记出处</a></td></tr>`).join('') || '<tr><td colspan="6">无结果</td></tr>'}</tbody></table><p class="small">C2 = 非权威来源，仅作线索；关键金额/比例须有 A1 支撑。</p>`;
}
async function m3Cite(i) {
  const x = M3.res[i];
  await api('/api/m3/citations', { method: 'POST', json: { doc_name: $('#m3doc').value, title: x.title, source_name: x.publisher, level: x.level, url: x.url, pub_date: x.date, excerpt: (x.snippet || '').slice(0, 200), query: M3.q, provider: x.provider } });
  toast('已登记到引用来源登记表'); const keep = $('#m3res').innerHTML; await route(); $('#m3res').innerHTML = keep;
}
async function m3SaveCit(a) { const tr = a.closest('tr'); await api('/api/m3/citations/' + tr.dataset.id, { method: 'PUT', json: { location: $('.c_loc', tr).value, excerpt: $('.c_ex', tr).value, verify_status: $('.c_vs', tr).value } }); toast('已保存'); }
async function m3DelCit(id) { if (confirm('删除该登记？')) { await api('/api/m3/citations/' + id, { method: 'DELETE' }); route(); } }
// 模型选择下拉（由 admin.js 实现；未配置时提示）
async function modelPicker(module, slots) { return window.renderModelPicker ? window.renderModelPicker(module, slots) : ''; }

/* ---------- 机构主数据 ---------- */
PAGES.inst = async v => {  // 「机构主数据」页按 PRD 1018 红线划掉：导航已移除，直接访问跳回工作台（/api/institutions 保留）
  if (!window.PH_SHOW_INST) { nav('home'); return; }
  const rows = await api('/api/institutions');
  v.innerHTML = `<div class="page-head"><div><h1>机构主数据</h1><p>M4、M5 共用同一份机构主数据（需求 9.1），导入附件2 时自动建立；可补充简称、地市、控股、注册资本等。</p></div></div>
  <div class="panel"><div class="tbl-wrap"><table class="grid"><thead><tr><th>ID</th><th>机构全称</th><th>简称</th><th>所属地市</th><th>控股机构</th><th>固定额度</th><th>注册资本</th><th>注册资本调整</th><th>状态</th><th>组织编码(行级权限)</th><th></th></tr></thead>
  <tbody>${rows.map(r => `<tr><td>${r.id}</td><td class="l">${esc(r.full_name)}</td><td>${esc(r.short_name)}</td><td>${esc(r.city || '')}</td><td>${r.is_holding ? '是' : ''}</td><td>${r.is_fixed_quota ? '<span class="pill gold">固定额度</span>' : ''}</td><td class="n">${f2(r.reg_capital)}</td><td class="n">${f2(r.reg_capital_adj)}</td><td>${esc(r.status)}</td><td class="small">${esc(r.org_code || '')}</td><td><a class="edit" onclick='editInst(${JSON.stringify(r).replace(/'/g, "&#39;")})'>编辑</a></td></tr>`).join('') || '<tr><td colspan="11">暂无，请先在 M4 导入附件2</td></tr>'}</tbody></table></div></div>`;
};
function editInst(r) {
  openModal('编辑机构：' + r.full_name, `<div class="form-row">
    <label>简称<input class="in" id="ei_s" value="${esc(r.short_name || '')}"></label><label>所属地市<input class="in" id="ei_c" value="${esc(r.city || '')}"></label>
    <label>控股机构<select class="in" id="ei_h"><option value="0">否</option><option value="1" ${r.is_holding ? 'selected' : ''}>是</option></select></label>
    <label>固定额度<select class="in" id="ei_f"><option value="0">否</option><option value="1" ${r.is_fixed_quota ? 'selected' : ''}>是</option></select></label></div>
    <div class="form-row"><label>注册资本(万元)<input class="in" id="ei_rc" value="${r.reg_capital ?? ''}"></label><label>注册资本调整(万元)<input class="in" id="ei_ra" value="${r.reg_capital_adj ?? ''}"></label>
    <label>状态<input class="in" id="ei_st" value="${esc(r.status || '')}"></label></div>
    <button class="primary" id="ei_ok">保存</button>`);
  $('#ei_ok').onclick = async () => {
    const n = id => $(id).value === '' ? null : Number($(id).value);
    await api('/api/institutions/' + r.id, { method: 'PUT', json: { short_name: $('#ei_s').value, city: $('#ei_c').value, is_holding: +$('#ei_h').value, is_fixed_quota: +$('#ei_f').value, reg_capital: n('#ei_rc'), reg_capital_adj: n('#ei_ra'), status: $('#ei_st').value } });
    closeModal(); toast('已保存'); route();
  };
}

/* ---------- 操作留痕 ---------- */
const KIND_NAMES = { m1_run: 'M1 采集记录', m2_brief: 'M2 简报', m3_task: 'M3 写作任务', m4_scheme: 'M4 方案版本', m4_dataset: 'M4 导入数据集', m5_snapshot: 'M5 看板快照', m5_limit_set: 'M5 额度表', ppt_job: 'PPT 任务', export: '导出记录', mail: '邮件发送记录' };
PAGES.audit = async (v, sub) => {
  sub = sub || 'log';
  const tabs = [['log', '操作留痕'], ['exports', '导出记录']].concat(ME.role !== 'institution' ? [['mails', '邮件发送记录']] : []).concat(ME.role === 'admin' ? [['bin', '回收站']] : []);
  const head = `<div class="page-head"><div><h1>操作留痕</h1><p>所有导入、人工调整、状态变更、导出、归档/删除均记录操作人、时间与内容（需求 10：人工调整全流程留痕）。</p></div></div>` + subtabs(tabs, sub, 'audit');
  if (sub === 'mails') return auditMails(v, head);
  if (sub === 'exports') {
    const rows = await api('/api/exports' + recQ('export'));
    v.innerHTML = head + `<div class="panel"><div class="panel-head"><div><h2>导出记录（${rows.length}）</h2><p>Word / Excel / PPT / Markdown 等导出与下载历史；归档/删除只影响历史记录，不影响已下载文件。</p></div>${recTabs('export')}</div>
    <div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>时间</th><th>操作人</th><th>模块</th><th>动作</th><th>对象</th><th>文件名</th><th></th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${recCb('export', r)}</td><td class="small">${esc(r.ts)}</td><td>${esc(r.user)}</td><td>${esc(r.module)}</td><td>${esc(r.action)}</td><td>#${esc(r.target)}</td><td class="l">${esc(r.filename || '')}</td><td>${recBtns('export', r)} ${recBadge(r)}</td></tr>`).join('') || '<tr><td colspan="8" class="small">暂无导出记录</td></tr>'}</tbody></table></div></div>`;
    return;
  }
  if (sub === 'bin') {
    const rows = await api('/api/records/bin');
    v.innerHTML = head + `<div class="panel"><div class="panel-head"><div><h2>回收站（${rows.length}）</h2><p>各模块已删除的记录。恢复后回到原列表；「彻底清除」会物理删除记录及附属数据（如 PPT 文件、台账明细），不可恢复。</p></div></div>
    <div class="tbl-wrap"><table class="grid"><thead><tr><th>类型</th><th>#</th><th>标题</th><th>创建人</th><th>删除人</th><th>删除时间</th><th></th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(KIND_NAMES[r.kind] || r.kind_name)}</td><td>${r.id}</td><td class="l">${esc(r.title || '')}</td><td>${esc(r.owner || '')}</td><td>${esc(r.deleted_by || '')}</td><td class="small">${esc(r.deleted_at)}</td>
     <td><a class="edit" onclick="recAct('${r.kind}','restore',[${r.id}])">恢复</a><a class="edit danger" onclick="recAct('${r.kind}','purge',[${r.id}])">彻底清除</a></td></tr>`).join('') || '<tr><td colspan="7" class="small">回收站为空</td></tr>'}</tbody></table></div></div>`;
    return;
  }
  const rows = await api('/api/audit');
  v.innerHTML = head + `<div class="panel"><div class="tbl-wrap"><table class="grid"><thead><tr><th>时间</th><th>操作人</th><th>账号</th><th>角色</th><th>模块</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
  <tbody>${rows.map(r => `<tr><td>${esc(r.ts)}</td><td>${esc(r.user)}</td><td class="small">${esc(r.username || '')}</td><td>${esc(r.role)}</td><td>${esc(r.module)}</td><td>${esc(r.action)}</td><td class="l">${esc(r.target)}</td><td class="l" title="${esc(r.detail)}">${esc((r.detail || '').slice(0, 120))}</td></tr>`).join('')}</tbody></table></div></div>`;
};

window.addEventListener("DOMContentLoaded", () => initIdentity().then(ok => ok && route()));
