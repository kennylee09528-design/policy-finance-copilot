/* PPT 生成 Agent：选择类型与数据 → Agent 确认需求 → 编辑/确认大纲 → 生成 .pptx（数字全部来自数据库） */
const PPT = { job: null, opt: null };
const PPT_STEPS = ['选择类型与数据', '确认需求单', '编辑并确认大纲', '生成与下载'];
const PPT_ICON = { usage: '▧', scheme: '◈', policy: '⌁', research: '✦' };
PAGES.ppt = async (v, sub) => {
  const head = `<div class="page-head"><div><h1>PPT 生成 Agent</h1><p>Agent 先与您确认需求、给出大纲，经人工修改确认后生成可编辑 .pptx。大模型只写结构与文字；所有数字、表格、图表由系统从数据库插入，并逐页做数字溯源检查。</p></div>
   <div class="page-actions"><button class="secondary" onclick="nav('ppt')">＋ 新建演示稿</button><button class="ghost" onclick="nav('ppt','history')">历史任务</button></div></div>`;
  if (sub && /^\d+$/.test(sub)) return pptJob(v, head, +sub);
  if (sub === 'history') return pptHistory(v, head);
  return pptNew(v, head);
};
function pptStepper(step) {
  return `<div class="ppt-steps mb">${PPT_STEPS.map((s, i) => `<div class="${i + 1 < step ? 'done' : i + 1 === step ? 'cur' : ''}"><b>${i + 1 < step ? '✓' : i + 1}</b>${s}</div>`).join('<i></i>')}</div>`;
}
async function pptNew(v, head) {
  const o = PPT.opt = await api('/api/ppt/options');
  const cur = PPT.deck || 'usage';
  v.innerHTML = head + pptStepper(1) + `<div class="ppt-decks mb">${Object.entries(o.decks).map(([k, d]) => `<button class="${k === cur ? 'active' : ''}" onclick="PPT.deck='${k}';route()">
     <b>${PPT_ICON[k]}</b><strong>${esc(d.name)}</strong><span>数据来源：${esc(d.source)}</span>${d.sensitive ? '<em class="pill red">含内部数据 · 建议使用公司自有大模型</em>' : '<em class="pill gray">公开资料</em>'}</button>`).join('')}</div>
  <div class="panel panel-b mb"><div class="form-row">${pptScope(cur, o)}</div>
   <div class="form-row"><label style="min-width:320px">PPT Agent 模型<select class="in" id="p_model"><option value="">（不使用模型：规则生成需求单与大纲）</option>
     ${o.models.map(m => `<option value="${m.id}" ${m.id === o.default_model ? 'selected' : ''}>${esc(m.label)}${m.allow_sensitive ? ' 🔒' : (o.decks[cur].sensitive ? '（公网模型）' : '')}</option>`).join('')}</select></label>
    <label>版式模板<select class="in" id="p_tpl"><option value="">工作台深红主题（16:9，默认）</option>${o.templates.map(t => `<option value="${t.id}" ${t.active ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
    <label style="flex:1">演示稿名称（可选）<input class="in" id="p_title" placeholder="留空使用系统标题"></label>
    <button class="primary" onclick="pptCreate()">开始：请 Agent 确认需求 →</button></div>
   ${o.decks[cur].sensitive ? '<div class="note-box">本类演示稿使用 M4/M5 机构授信与额度数据（需求第 10 章），建议使用公司自有大模型（🔒）；也可选择公网模型，不影响生成。大模型仅看到数据目录（编号与名称），看不到数值，数字均由系统从数据库填入。</div>' : ''}</div>`;
}
function pptScope(k, o) {
  if (k === 'usage') return `<label>M5 看板快照<select class="in" id="s_a">${o.snapshots.map(s => `<option value="${s.id}">${esc(s.stat_date)} · #${s.id} ${esc(s.label || '')}</option>`).join('') || '<option value="">（无快照，请先在 M5 上传台账）</option>'}</select></label>
    <label>汇报周期<select class="in" id="s_b"><option>周报</option><option>月报</option></select></label>`;
  if (k === 'scheme') return `<label>M4 授信方案版本<select class="in" id="s_a">${o.schemes.map(s => `<option value="${s.id}">v${s.version} · ${esc(s.name)} · ${esc(s.status)}${s.is_current ? '（当前）' : ''}</option>`).join('') || '<option value="">（无方案）</option>'}</select></label>`;
  if (k === 'policy') { const d = o.brief_dates; return `<label>起始日期<input class="in" type="date" id="s_a" value="${d[d.length - 1] || ''}"></label><label>截止日期<input class="in" type="date" id="s_b" value="${d[0] || ''}"></label>
    <span class="small">已有简报 ${d.length} 期${d.length ? '（' + d[d.length - 1] + ' ~ ' + d[0] + '）' : ''}；同一日期优先取已发布版本</span>`; }
  return `<label>M3 已定稿写作任务<select class="in" id="s_a">${o.m3_tasks.map(t => `<option value="${t.id}">#${t.id} ${esc(t.title)}（${esc(t.status)}）</option>`).join('') || '<option value="">（无已定稿任务）</option>'}</select></label>`;
}
async function pptCreate() {
  const k = PPT.deck || 'usage', a = $('#s_a')?.value, b = $('#s_b')?.value;
  const scope = { usage: { snapshot_id: a, period: b }, scheme: { scheme_id: a }, policy: { date_from: a, date_to: b }, research: { task_id: a } }[k];
  toast('Agent 正在阅读数据目录并准备问题…', 6000);
  const j = await api('/api/ppt/jobs', { method: 'POST', json: { deck_type: k, scope, model_id: $('#p_model').value || null, template_id: $('#p_tpl').value || null, title: $('#p_title').value || null } });
  nav('ppt', j.id);
}
async function pptHistory(v, head) {
  const rows = await api('/api/ppt/jobs' + recQ('ppt_job'));
  v.innerHTML = head + `<div class="panel"><div class="panel-head"><div><h2>历史任务（${rows.length}）</h2><p>每次生成保留一个版本，可随时下载；修改大纲后可再次生成新版本。</p></div>${recTabs('ppt_job')}</div><div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>#</th><th>类型</th><th>名称</th><th>状态</th><th>版本数</th><th>创建人</th><th>更新时间</th><th></th></tr></thead><tbody>
  ${rows.map(r => `<tr><td>${recCb('ppt_job', r)}</td><td>${r.id}</td><td>${esc(r.deck_name)}</td><td class="l">${esc(r.title)}</td><td><span class="pill ${r.status === '已生成' ? 'green' : 'gold'}">${esc(r.status)}</span></td><td>${r.versions || 0}</td><td>${esc(r.created_by)}</td><td class="small">${esc(r.updated_at)}</td><td>${r.deleted_at ? '' : `<a class="edit" onclick="nav('ppt',${r.id})">打开</a>`}${recBtns('ppt_job', r)} ${recBadge(r)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">暂无任务</td></tr>'}</tbody></table></div></div>`;
}
async function pptJob(v, head, id) {
  const j = PPT.job = await api('/api/ppt/jobs/' + id);
  PPT.edit = JSON.parse(JSON.stringify(j.outline || []));
  const chat = j.messages.map(m => `<div class="ppt-msg ${m.role}"><div class="who">${m.role === 'agent' ? 'PPT Agent' + (m.via ? ' · ' + esc(m.via) : '') : '我'}<span>${esc(m.at)}</span></div>
     <div>${esc(m.text).replace(/\n/g, '<br>')}</div>${m.questions ? `<ol>${m.questions.map(q => `<li>${esc(q)}</li>`).join('')}</ol>` : ''}</div>`).join('');
  v.innerHTML = head + pptStepper(j.step) + `<div class="kv mb"><div><span>任务</span><b style="font-size:14px">#${j.id} ${esc(j.deck_name)}</b></div><div><span>数据来源</span><b style="font-size:12.5px">${esc(JSON.stringify(j.source || {}))}</b></div>
    <div><span>状态</span><b style="font-size:14px">${esc(j.status)}</b></div><div><span>Tokens / 提示词版本</span><b style="font-size:14px">${j.tokens || 0} / v${j.prompt_version || 0}</b></div></div>
  ${j.warnings.length ? `<div class="alerts">${j.warnings.map(w => `<div class="alert warn">${esc(w)}</div>`).join('')}</div>` : ''}
  <div class="ppt-layout"><div class="panel"><div class="panel-head"><div><h2>与 Agent 的对话</h2><p>需求确认 → 大纲 → 生成，每一步都由您确认</p></div></div><div class="panel-b ppt-chat">${chat}</div></div>
   <div>${j.step === 2 ? pptSheet(j) : pptOutline(j)}${pptFiles(j)}</div></div>
  ${pptCatalog(j)}`;
}
function pptSheet(j) {
  const s = j.sheet, F = [['title', '演示稿名称'], ['audience', '汇报对象 / 受众'], ['purpose', '目的'], ['style', '风格'], ['tone', '语气'], ['emphasis', '重点突出']];
  return `<div class="panel mb"><div class="panel-head"><div><h2>第 2 步 · 需求单（可直接修改）</h2><p>回答 Agent 的问题并核对需求单，确认后 Agent 生成大纲</p></div></div><div class="panel-b">
   ${(j.questions || []).map((q, i) => `<div class="form-row"><label style="flex:1">${i + 1}. ${esc(q)}<input class="in p_ans" placeholder="您的回答（可留空）"></label></div>`).join('')}
   <div class="grid2">${F.map(([k, n]) => `<label class="small">${n}<input class="in" style="width:100%" id="sh_${k}" value="${esc(s[k] || '')}"></label>`).join('')}
    <label class="small">期望页数<input class="in" type="number" id="sh_pages" value="${s.pages || 12}" style="width:100%"></label>
    <label class="small">章节（每行一个）<textarea class="in" id="sh_sections">${esc((s.sections || []).join('\n'))}</textarea></label></div>
   ${PPT.job.model_notice ? `<div class="note-box" style="margin-top:12px">⚠ ${esc(PPT.job.model_notice)}</div>` : ''}
   <div class="form-row" style="margin-top:12px"><label style="flex:1">其他补充<input class="in" id="p_msg" placeholder="例如：只展示使用率低于时间进度的机构；附系数规则页"></label><button class="primary" onclick="pptConfirmSheet()">确认需求单，生成大纲 →</button></div></div></div>`;
}
async function pptConfirmSheet() {
  const sh = {}; ['title', 'audience', 'purpose', 'style', 'tone', 'emphasis'].forEach(k => sh[k] = $('#sh_' + k).value);
  sh.pages = +$('#sh_pages').value; sh.sections = $('#sh_sections').value.split('\n').map(x => x.trim()).filter(Boolean);
  toast('Agent 正在生成大纲…', 8000);
  await api(`/api/ppt/jobs/${PPT.job.id}/sheet`, { method: 'POST', json: { sheet: sh, answers: $$('.p_ans').map(i => i.value), message: $('#p_msg').value } });
  route();
}
function pptDataOpts(kind, cur) {
  const c = PPT.job.catalog, src = { chart: c.charts, table: c.tables, text: c.texts }[kind];
  if (!src) return '';
  return `<select class="in o_data">${Object.entries(src).map(([k, d]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${k} ${esc(d.title)}（${d.n}）</option>`).join('')}</select>`;
}
function pptOutline(j) {
  const K = j.kinds || { cover: '封面', agenda: '目录', section: '章节页', content: '要点页', kpi: '指标卡片', chart: '图表', table: '表格', text: '文字块', closing: '封底' };
  PPT.kinds = K;
  const done = j.step >= 4;
  return `<div class="panel mb"><div class="panel-head"><div><h2>第 3 步 · 大纲（${PPT.edit.length} 页）</h2><p>可改标题/要点/类型/数据、调整顺序、删除或新增页面。要点里不要写数字，用 {{F1}} 这类编号引用指标（见下方数据目录）。</p></div>
    <div><button class="ghost mini" onclick="pptAdd()">＋ 页面</button> <button class="secondary mini" onclick="pptSave()">保存修改</button></div></div>
   <div class="panel-b ppt-outline">${PPT.edit.map((p, i) => pptPageCard(p, i, K, j.preview[i])).join('')}</div>
   <div class="panel-b" style="border-top:1px solid var(--line)"><div class="form-row" style="margin:0"><label style="flex:1">让 Agent 按意见重做大纲<input class="in" id="p_re" placeholder="例如：压缩到 8 页，删去民投专项，增加下一步工作建议"></label><button class="ghost" onclick="pptRegen()">重新生成大纲</button>
    <label><span><input type="checkbox" id="p_refresh"> 生成前刷新数据</span></label><button class="primary" onclick="pptGenerate()">${done ? '确认大纲并生成新版本' : '确认大纲，生成 PPT →'}</button></div></div></div>`;
}
function pptPageCard(p, i, K, pv) {
  const needsData = ['chart', 'table', 'text'].includes(p.kind), multi = ['kpi', 'content'].includes(p.kind);
  return `<div class="ppt-page" data-i="${i}"><div class="no">${i + 1}</div><div class="body">
   <div class="form-row" style="margin-bottom:6px"><select class="in o_kind" onchange="pptKind(${i},this.value)">${Object.entries(K).map(([k, n]) => `<option value="${k}" ${k === p.kind ? 'selected' : ''}>${n}</option>`).join('')}</select>
    <input class="in o_title" style="flex:1" value="${esc(p.title)}">${needsData ? pptDataOpts(p.kind, p.data) : ''}${multi ? `<input class="in o_facts" style="width:150px" title="指标编号，逗号分隔" placeholder="指标 F1,F2" value="${esc((p.data || []).join(','))}">` : ''}
    <span class="ops"><a onclick="pptMove(${i},-1)">↑</a><a onclick="pptMove(${i},1)">↓</a><a onclick="pptDel(${i})">✕</a></span></div>
   ${['content', 'kpi'].includes(p.kind) ? `<textarea class="in o_bullets" placeholder="每行一条要点">${esc((p.bullets || []).join('\n'))}</textarea>` : ''}
   ${pv && pv.bullets && pv.bullets.length ? `<div class="small pv">预览：${pv.bullets.map(esc).join(' ｜ ')}</div>` : ''}</div></div>`;
}
function pptCollect() {
  $$('.ppt-page').forEach(el => { const p = PPT.edit[+el.dataset.i];
    p.kind = $('.o_kind', el).value; p.title = $('.o_title', el).value;
    if ($('.o_bullets', el)) p.bullets = $('.o_bullets', el).value.split('\n').map(x => x.trim()).filter(Boolean);
    if ($('.o_data', el)) p.data = $('.o_data', el).value;
    if ($('.o_facts', el)) p.data = $('.o_facts', el).value.split(/[,，\s]+/).filter(Boolean); });
  return PPT.edit;
}
function pptRerender() { const box = $('.ppt-outline'); box.innerHTML = PPT.edit.map((p, i) => pptPageCard(p, i, PPT.kinds, null)).join(''); }
function pptKind(i, k) { pptCollect(); PPT.edit[i].kind = k; PPT.edit[i].data = ['chart', 'table', 'text'].includes(k) ? Object.keys(PPT.job.catalog[{ chart: 'charts', table: 'tables', text: 'texts' }[k]])[0] : k === 'kpi' ? ['F1'] : null; pptRerender(); }
function pptMove(i, d) { pptCollect(); const j = i + d; if (j < 0 || j >= PPT.edit.length) return; [PPT.edit[i], PPT.edit[j]] = [PPT.edit[j], PPT.edit[i]]; pptRerender(); }
function pptDel(i) { pptCollect(); PPT.edit.splice(i, 1); pptRerender(); }
function pptAdd() { pptCollect(); PPT.edit.splice(Math.max(PPT.edit.length - 1, 0), 0, { kind: 'content', title: '新页面', bullets: ['要点'], data: null }); pptRerender(); }
async function pptSave(quiet) {
  const r = await api(`/api/ppt/jobs/${PPT.job.id}/outline`, { method: 'PUT', json: { pages: pptCollect() } });
  if (!quiet) { toast(r.outline_warnings.length ? `已保存，自动修正 ${r.outline_warnings.length} 处（见提示）` : '大纲已保存', 3500); route(); }
  return r;
}
async function pptRegen() { toast('Agent 正在重新生成大纲…', 8000); await api(`/api/ppt/jobs/${PPT.job.id}/outline/regenerate`, { method: 'POST', json: { message: $('#p_re').value } }); route(); }
async function pptGenerate() {
  if (!confirm((PPT.job.model_notice ? '提示：' + PPT.job.model_notice + '\n\n' : '') + '确认当前大纲并生成 PPT？')) return;
  await pptSave(true);
  toast('正在生成 PPT 并做数字溯源检查…', 15000);
  await api(`/api/ppt/jobs/${PPT.job.id}/generate`, { method: 'POST', json: { confirm: true, refresh_data: $('#p_refresh').checked } });
  toast('已生成'); route();
}
function pptFiles(j) {
  if (!j.files.length) return '';
  return `<div class="panel mb"><div class="panel-head"><div><h2>第 4 步 · 生成结果（${j.files.length} 个版本）</h2><p>原生可编辑图表与表格，可在 PowerPoint / WPS 中直接修改</p></div></div><div class="panel-b">
   ${j.files.map(f => `<div class="ppt-file"><div class="form-row" style="margin-bottom:6px"><b>v${f.version}</b><span>${esc(f.filename)} · ${f.pages} 页 · ${esc(f.created_by)} ${esc(f.created_at)}</span>
     <span class="pill ${f.trace.ok ? 'green' : 'red'}" title="${esc(JSON.stringify(f.trace.violations || []))}">数字溯源${f.trace.ok ? '通过' : '异常 ' + f.trace.violations.length}：${f.trace.numbers_checked} 个数字 / ${f.trace.chart_series_checked} 个图表序列</span>
     <button class="primary mini" onclick="download('/api/ppt/files/${f.id}/download')">下载 .pptx</button> ${mailBtn('ppt_file', f.id)}</div>
     ${f.thumbs.length ? `<div class="ppt-thumbs">${f.thumbs.map(t => `<img loading="lazy" src="/api/ppt/files/${f.id}/thumbs/${t}" onclick="window.open(this.src)">`).join('')}</div>` : '<div class="small">（服务器未安装 LibreOffice，不生成缩略图；大纲预览见上方）</div>'}</div>`).join('')}</div></div>`;
}
function pptCatalog(j) {
  const c = j.catalog;
  return `<div class="panel"><div class="panel-head"><div><h2>数据目录（数值由系统从数据库取得）</h2><p>大模型只看到编号与名称；生成时由代码插入下列数值/图表/表格</p></div></div><div class="panel-b grid2 small">
   <div><b>指标 {{Fn}}</b>${Object.entries(c.facts).map(([k, f]) => `<div>${k}　${esc(f.name)}：<b style="color:var(--red-d)">${esc(f.value)}</b></div>`).join('') || '<div>无</div>'}</div>
   <div><b>图表 / 表格 / 文字块</b>${[...Object.entries(c.charts).map(([k, d]) => `${k}　图表：${esc(d.title)}（${d.n} 类）`), ...Object.entries(c.tables).map(([k, d]) => `${k}　表格：${esc(d.title)}（${d.n} 行）`), ...Object.entries(c.texts).map(([k, d]) => `${k}　文字：${esc(d.title)}（${d.n} 条）`)].map(x => `<div>${x}</div>`).join('')}</div></div></div>`;
}

/* ================= 系统管理：PPT Agent ================= */
async function admPPT(v, head) {
  const [d, models] = await Promise.all([api('/api/admin/ppt/config'), api('/api/llm/models')]);
  const c = d.config;
  v.innerHTML = head + `<div class="note-box mb">PPT Agent 只生成结构与文字；数字一律以 {{Fn}} 占位、由系统从数据库填入。额度/授信类演示稿（及使用 M5 数据的研究报告配套稿）只能使用允许处理敏感数据的模型。</div>
  <div class="panel mb"><div class="panel-head"><div><h2>默认模型与参数</h2></div><button class="primary mini" onclick="admPPTSave()">保存</button></div><div class="panel-b form-row">
   <label>默认模型<select class="in" id="pc_model"><option value="">（沿用「大模型配置」中的环节分配）</option>${models.models.map(m => `<option value="${m.id}" ${c.model_id === m.id ? 'selected' : ''}>${esc(m.label)}${m.allow_sensitive ? ' 🔒' : ''}</option>`).join('')}</select></label>
   <label>temperature<input class="in" id="pc_t" type="number" step="0.1" value="${c.temperature ?? ''}" style="width:80px"></label><label>top_p<input class="in" id="pc_p" type="number" step="0.05" value="${c.top_p ?? ''}" style="width:80px"></label>
   <label>超时(秒)<input class="in" id="pc_to" type="number" value="${c.timeout}" style="width:80px"></label><label>最大页数<input class="in" id="pc_mp" type="number" value="${c.max_pages}" style="width:80px"></label></div></div>
  ${Object.entries(d.decks).map(([k, dk]) => { const ps = d.prompts.filter(p => p.deck_type === k); const act = ps.find(p => p.active) || ps[0] || {};
    return `<div class="panel mb" data-deck="${k}"><div class="panel-head"><div><h2>提示词模板 · ${esc(dk.name)}</h2><p>当前启用 v${act.version || 0}</p></div></div><div class="panel-b">
     <textarea class="in d_prompt" style="min-height:130px">${esc(act.content || '')}</textarea>
     <div class="form-row" style="margin-top:8px"><label style="flex:1">版本说明<input class="in d_note"></label><button class="secondary mini" onclick="admPPTPrompt('${k}')">保存为新版本并启用</button></div>
     <div class="small">历史版本：${ps.map(p => `<span class="pill ${p.active ? 'green' : 'gray'}" style="cursor:pointer" title="${esc(p.note || '')} ${esc(p.created_by)} ${esc(p.created_at)}" onclick="admPPTAct(${p.id})">v${p.version}${p.active ? ' 启用中' : ''}</span>`).join(' ')}</div></div></div>`; }).join('')}
  <div class="panel"><div class="panel-head"><div><h2>PPT 模板（母版 / 版式）</h2><p>上传公司 .pptx 模板后，生成时使用其母版与版式（封面/节标题/仅标题等按版式名称匹配）；未上传时使用工作台深红主题。</p></div></div><div class="panel-b">
   <div class="form-row"><label>模板名称<input class="in" id="tp_name"></label><label>.pptx 文件<input type="file" id="tp_file" accept=".pptx"></label><button class="primary mini" onclick="admPPTUpload()">上传</button>
    <button class="ghost mini" onclick="admPPTTpl(0)">恢复默认深红主题</button></div>
   <table class="grid"><thead><tr><th>默认</th><th>名称</th><th>文件</th><th>版式</th><th>上传</th><th></th></tr></thead><tbody>
   ${d.templates.map(t => `<tr><td>${t.active ? '<span class="pill green">默认</span>' : `<a class="edit" onclick="admPPTTpl(${t.id})">设为默认</a>`}</td><td>${esc(t.name)}</td><td>${esc(t.filename)}</td><td class="l small" title="${esc(t.layouts.map(l => l.name).join('、'))}">${t.layouts.length} 个：${esc(t.layouts.map(l => l.name).slice(0, 6).join('、'))}</td><td class="small">${esc(t.uploaded_by)} ${esc(t.uploaded_at)}</td><td><a class="edit" onclick="admPPTDel(${t.id})">删除</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">暂无上传模板</td></tr>'}</tbody></table></div></div>`;
}
async function admPPTSave() {
  await api('/api/admin/ppt/config', { method: 'PUT', json: { model_id: $('#pc_model').value || null, temperature: $('#pc_t').value === '' ? null : +$('#pc_t').value, top_p: $('#pc_p').value === '' ? null : +$('#pc_p').value, timeout: +$('#pc_to').value, max_pages: +$('#pc_mp').value } });
  toast('已保存'); route();
}
async function admPPTPrompt(k) { const el = $(`[data-deck="${k}"]`); await api('/api/admin/ppt/prompts', { method: 'POST', json: { deck_type: k, content: $('.d_prompt', el).value, note: $('.d_note', el).value } }); toast('已保存新版本并启用'); route(); }
async function admPPTAct(id) { if (confirm('启用该版本？')) { await api(`/api/admin/ppt/prompts/${id}/activate`, { method: 'POST' }); route(); } }
async function admPPTUpload() {
  const f = $('#tp_file').files[0]; if (!f) return toast('请选择 .pptx 文件');
  const fd = new FormData(); fd.append('file', f); fd.append('name', $('#tp_name').value || f.name);
  await api('/api/admin/ppt/templates', { method: 'POST', body: fd }); toast('模板已上传'); route();
}
async function admPPTTpl(id) { await api(`/api/admin/ppt/templates/${id}/activate`, { method: 'POST' }); toast('已设置'); route(); }
async function admPPTDel(id) { if (confirm('删除该模板？')) { await api(`/api/admin/ppt/templates/${id}`, { method: 'DELETE' }); route(); } }
