/* 今日行业 Brief（M2） + M3 写作任务（三 Agent）+ 对应系统管理页 */
const STARS = { 3: '★★★', 2: '★★', 1: '★' };
const SEC = { 必读: '一、今日必读', 关注: '二、值得关注', 同业动态: '三、同业动态/他省做法', 浏览: '★ 浏览（折叠）' };
function mdHtml(md) {
  const out = []; const lines = (md || '').split('\n'); let i = 0, list = false;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(https?:\/\/[^\s|）)]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  const endList = () => { if (list) { out.push('</ul>'); list = false; } };
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith('|')) { endList(); const rows = []; while (i < lines.length && lines[i].startsWith('|')) { if (!/^\|[-| ]+\|$/.test(lines[i])) rows.push(lines[i].replace(/^\||\|$/g, '').split('|')); i++; }
      out.push(`<table class="grid">${rows.map((r, k) => `<tr>${r.map(c => k ? `<td class="l">${inline(c.trim())}</td>` : `<th>${inline(c.trim())}</th>`).join('')}</tr>`).join('')}</table>`); continue; }
    if (l.startsWith('# ')) { endList(); out.push(`<h1 style="font-size:20px;margin:6px 0 10px">${inline(l.slice(2))}</h1>`); }
    else if (l.startsWith('## ')) { endList(); out.push(`<h2 style="font-size:16px;margin:14px 0 6px;color:var(--red)">${inline(l.slice(3))}</h2>`); }
    else if (/^\s*- /.test(l)) { if (!list) { out.push('<ul style="margin:0 0 4px 18px">'); list = true; } out.push(`<li class="small">${inline(l.replace(/^\s*- /, ''))}</li>`); }
    else if (l.trim()) { endList(); out.push(`<p style="margin:6px 0 2px">${inline(l)}</p>`); }
    i++;
  }
  endList(); return out.join('');
}

/* ================= M2 ================= */
const M2 = {};
PAGES.m2 = async (v) => {
  const inst = ME.role === 'institution';
  const [list, cfg] = await Promise.all([api('/api/m2/briefs' + recQ('m2_brief')), inst ? null : api('/api/m2/config')]);
  if (M2.id && !list.some(x => x.id === M2.id)) M2.id = null;
  if (!M2.id && list.length) M2.id = list[0].id;
  const b = M2.id ? await api('/api/m2/briefs/' + M2.id).catch(() => null) : null;
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const locked = b && b.status === '已发布';
  if (inst) {
    v.innerHTML = `<div class="page-head"><div><h1>今日行业 Brief（M2）</h1><p>已发布的每日行业简报（来源均为权威发布方，关键数字可追溯原文）。</p></div></div>
    <div style="display:grid;grid-template-columns:230px 1fr;gap:16px"><div class="panel"><div class="panel-head"><div><h2>已发布简报</h2><p>${list.length} 期</p></div></div><div style="max-height:900px;overflow:auto">
    ${list.map(x => `<div class="task-row" style="cursor:pointer;${x.id === M2.id ? 'background:var(--red-bg)' : ''}" onclick="M2.id=${x.id};route()"><div><strong>${esc(x.brief_date)} · v${x.version}</strong><small>${x.stats.items ?? 0} 条</small></div></div>`).join('') || '<p class="small panel-b">暂无已发布简报</p>'}</div></div>
    <div>${b ? `<div class="panel"><div class="panel-head"><div><h2>${esc(b.brief_date)} 今日行业 Brief</h2></div><div><button class="secondary mini" onclick="download('/api/m2/briefs/${b.id}/export.docx')">导出 Word</button> <button class="secondary mini" onclick="m2Pdf()">导出 PDF</button></div></div><div class="panel-b md-view">${mdToHtml(b.markdown)}</div></div>` : '<div class="empty">暂无已发布简报</div>'}</div></div>`;
    M2.b = b; return;
  }
  const w = cfg.weights;
  v.innerHTML = `<div class="page-head"><div><h1>今日行业 Brief（M2）</h1><p>取 M1 最近 ${cfg.window_hours} 小时采集条目 → 重要度打分（来源 ${w.level * 100}% / 层级 ${w.layer * 100}% / 业务相关度 ${w.relevance * 100}% / 时效 ${w.timeliness * 100}%）→ ★★★ ≥ ${cfg.tiers.three}、★★ ≥ ${cfg.tiers.two} → 按模板生成；关键数字须能在原文找到，否则拦截。${cfg.schedule.enabled ? '每日 ' + esc(cfg.schedule.time) + '（北京时间）自动生成。' : '定时生成未启用。'}</p></div>
   <div class="page-actions"><button class="primary" onclick="m2Gen('${today}')">立即生成今日简报</button><input class="in" type="date" id="m2d" value="${esc(b ? b.brief_date : today)}" max="${today}"><button class="secondary" onclick="m2Gen($('#m2d').value)">生成/重新生成该日</button></div></div>
  ${await modelPicker('m2', [['brief', '简报要点提炼模型']])}
  <div style="display:grid;grid-template-columns:230px 1fr;gap:16px">
   <div class="panel"><div class="panel-head" style="flex-wrap:wrap;gap:6px"><div><h2>按日期归档</h2><p>${list.length} 个版本</p></div>${ME.role === 'institution' ? '' : recTabs('m2_brief')}</div><div style="max-height:900px;overflow:auto">
    ${list.map(x => `<div class="task-row" style="cursor:pointer;${x.id === M2.id ? 'background:var(--red-bg)' : ''}" onclick="M2.id=${x.id};route()">${recCb('m2_brief', x)}<div><strong>${esc(x.brief_date)} · v${x.version}</strong><small>${esc(x.stats.trigger || '')} · ${x.stats.items ?? 0} 条 · 拦截 ${x.stats.blocked ?? 0}</small>${recBtns('m2_brief', x)}</div><em class="status ${x.status === '已发布' ? 'done' : 'review'}">${esc(x.status)}</em></div>`).join('') || '<p class="small panel-b">暂无简报，点击右上角生成</p>'}</div></div>
   <div>${b ? m2Detail(b, locked) : '<div class="empty">尚无简报。M1 采集到条目后点击「立即生成今日简报」，或等待每日定时生成。</div>'}</div></div>`;
};
async function m2Pdf() {
  const b = M2.b || await api('/api/m2/briefs/' + M2.id);
  await printView('M2', b.id, `今日行业Brief_${b.brief_date}_v${b.version}.pdf`, `今日行业 Brief · ${b.brief_date}`, mdToHtml(b.markdown));
}
function m2Detail(b, locked) {
  M2.b = b;
  const s = b.stats;
  const rows = b.items.map(i => `<tr data-id="${i.m1_id}" style="${i.blocked ? 'background:#fff3f3' : ''}">
   <td><input type="checkbox" class="i_inc" ${i.include !== false ? 'checked' : ''} ${locked ? 'disabled' : ''}></td>
   <td><select class="in i_tier" ${locked ? 'disabled' : ''}>${[3, 2, 1].map(t => `<option value="${t}" ${t === i.tier ? 'selected' : ''}>${STARS[t]}</option>`).join('')}</select></td>
   <td class="n" title="${esc(Object.entries(i.parts).map(([k, x]) => k + ' ' + x).join(' / '))}">${i.score}</td><td class="small">${esc(SEC[i.section] || i.section)}</td>
   <td class="l" style="max-width:300px"><span class="pill ${i.level === 'A1' ? 'red' : i.level === 'A2' ? 'gold' : 'blue'}">${i.level}</span> 【${esc(i.category)}｜${esc(i.region || '—')}】<a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a><br><span class="small">${esc(i.publisher)} · ${esc(i.pub_date || '未标注')} · ${esc(i.layer_key)}</span></td>
   <td class="l"><textarea class="in i_pts" style="min-width:260px;min-height:54px" ${locked ? 'disabled' : ''}>${esc((i.points || []).join('\n'))}</textarea><span class="small">${esc(i.points_method || '')}</span></td>
   <td class="l small">${(i.number_check || []).map(c => `<span class="pill ${c.ok ? 'green' : 'red'}" title="${c.ok ? '原文可查' : '原文中未找到'}">${esc(c.num)}${c.ok ? ' ✓' : ' ✗'}</span>`).join(' ') || '—'}${i.blocked ? `<div style="color:var(--red)">已拦截：${esc((i.block_reason || []).join('；'))}</div>` : ''}</td></tr>`).join('');
  return `<div class="kv mb"><div><span>${esc(b.brief_date)} · v${b.version}</span><b style="font-size:15px">${esc(b.status)}</b></div><div><span>取数窗口</span><b style="font-size:12.5px">${esc((s.window || []).join(' ~ '))}</b></div>
   <div><span>候选 / 入选</span><b>${s.candidates ?? 0} / ${s.items ?? 0}</b></div><div><span>★★★ / ★★ / ★ · 拦截</span><b>${s.three} / ${s.two} / ${s.one} · <span style="color:var(--red)">${s.blocked}</span></b></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>条目与打分（可调档、排除、改要点；改动反哺 M1 标记「人工校正」）</h2><p>生成：${esc(b.generated_at)} ${esc(b.generated_by)}${b.edited_at ? ' · 编辑：' + esc(b.edited_at) + ' ' + esc(b.edited_by) : ''}${b.published_at ? ' · 发布：' + esc(b.published_at) + ' ' + esc(b.published_by) : ''}</p></div>
   ${locked ? '' : '<button class="secondary mini" onclick="m2SaveItems()">保存条目修改并重排</button>'}</div>
   <div class="tbl-wrap" style="max-height:520px"><table class="grid"><thead><tr><th>入选</th><th>档位</th><th>得分</th><th>栏目</th><th>条目</th><th>要点（每行一条）</th><th>关键数字来源校验</th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="small">窗口内没有 M1 新条目</td></tr>'}</tbody></table></div></div>
  <div class="grid2"><div class="panel"><div class="panel-head"><div><h2>简报正文（Markdown，可直接编辑）</h2></div>${locked ? '<span class="pill green">已发布 · 锁定</span>' : '<button class="secondary mini" onclick="m2SaveMd()">保存正文</button>'}</div>
    <div class="panel-b"><textarea class="in" id="m2md" style="width:100%;min-height:560px;font-family:monospace;font-size:12px" ${locked ? 'disabled' : ''}>${esc(b.markdown)}</textarea></div></div>
   <div class="panel"><div class="panel-head"><div><h2>预览</h2></div><div>${locked ? '' : '<button class="primary mini" onclick="m2Publish()">发布</button> '}${locked ? mailBtn('m2_brief', b.id) + ' ' : ''}<button class="secondary mini" onclick="download('/api/m2/briefs/${b.id}/export.docx')">导出 Word</button> <button class="secondary mini" onclick="download('/api/m2/briefs/${b.id}/export.md')">导出 Markdown</button> <button class="secondary mini" onclick="m2Pdf()">导出 PDF</button></div></div>
    <div class="panel-b" id="m2pv" style="max-height:600px;overflow:auto">${mdHtml(b.markdown)}</div></div></div>`;
}
async function m2Gen(d) { toast('生成中…'); const b = await api('/api/m2/briefs/generate', { method: 'POST', json: { date: d } }); M2.id = b.id; toast(`已生成 ${b.brief_date} v${b.version}`); route(); }
async function m2SaveItems() {
  const items = $$('tr[data-id]').map((tr, k) => ({ m1_id: +tr.dataset.id, include: $('.i_inc', tr).checked, tier: +$('.i_tier', tr).value, order: k, points: $('.i_pts', tr).value.split('\n').map(s => s.trim()).filter(Boolean) }));
  await api('/api/m2/briefs/' + M2.id, { method: 'PUT', json: { items } }); toast('已保存，正文已按条目重新生成'); route();
}
async function m2SaveMd() { await api('/api/m2/briefs/' + M2.id, { method: 'PUT', json: { markdown: $('#m2md').value } }); toast('正文已保存'); route(); }
async function m2Publish() { if (!confirm('发布后该版本锁定不可修改，确认发布？')) return; await api(`/api/m2/briefs/${M2.id}/publish`, { method: 'POST' }); toast('已发布'); route(); }

/* ================= M3 写作任务 ================= */
const M3T = {};
const M3_RUNNING = ['排队', '检索资料', '写作中', '核对中'];
async function m3Page(v, sub, tabs, picker) {
  clearTimeout(M3T.timer);
  const head = `<div class="page-head"><div><h1>行业研究院（M3）</h1><p>研究及写作 Agent（知识库 FTS5 + 联网检索 + M5 数据库取数）→ 核对 Agent（金额/比例/排名/案例/机构/文件名称 逐句核出处，标红拦截）→ 人工修改终稿 → 总结 Agent（初稿/终稿对比，沉淀写作规范，下次自动注入）。</p></div></div>
  ${picker}${subtabs(tabs.map(x => [x[0], x[1]]), sub, 'm3')}`;
  if (sub === 'style') return m3Style(v, head);
  const [ag, tasks] = await Promise.all([api('/api/m3/agents'), api('/api/m3/tasks' + recQ('m3_task'))]);
  if (M3T.id && !tasks.some(x => x.id === M3T.id)) M3T.id = null;
  if (!M3T.id && tasks.length) M3T.id = tasks[0].id;
  const t = M3T.id ? await api('/api/m3/tasks/' + M3T.id).catch(() => null) : null;
  const agLine = Object.entries(ag.names).map(([k, n]) => `<span class="pill ${ag.effective_model[k] ? 'blue' : 'gray'}">${n}：${ag.effective_model[k] ? '模型#' + ag.effective_model[k] : '未配置'} · T=${ag.agents[k].temperature} · 模板 v${ag.prompt_version[k]}</span>`).join(' ');
  v.innerHTML = head + `<div class="grid2 mb" style="grid-template-columns:1.1fr .9fr"><div class="panel panel-b"><h2 class="mb">新建写作任务</h2>
   <div class="form-row"><label style="flex:1">题目<input class="in" id="t_title" placeholder="例如：广东省政府性融资担保体系建设情况及下一步建议"></label></div>
   <div class="form-row"><label style="flex:1">写作要求<textarea class="in" id="t_req" style="min-height:60px" placeholder="重点、口径、读者对象、需要回答的问题…"></textarea></label></div>
   <div class="form-row"><label>文体<select class="in" id="t_genre">${['研究报告', '日报研究报告', '工作报告', '调研报告', '请示', '信息简报', '讲话稿'].map(x => `<option>${x}</option>`).join('')}</select></label><label>字数<input class="in" id="t_words" type="number" value="3000" style="width:90px"></label>
    <label>文风<input class="in" id="t_tone" value="正式、简洁" style="width:120px"></label><label>M5 数据日期<input class="in" id="t_dd" type="date"></label></div>
   <div class="form-row"><label><span><input type="checkbox" id="t_kb" checked> 知识库（M1）</span></label><label><span><input type="checkbox" id="t_web" checked> 联网检索</span></label><label><span><input type="checkbox" id="t_m5"> 插入 M5 数据（数值由系统从库中填入；须私有/授权模型）</span></label>
    <button class="primary" onclick="m3Create()">开始写作</button></div><div class="small">${agLine}</div></div>
   <div class="panel"><div class="panel-head" style="flex-wrap:wrap;gap:6px"><div><h2>写作任务</h2></div>${recTabs('m3_task')}</div><div style="max-height:300px;overflow:auto">${tasks.map(x => `<div class="task-row" style="cursor:pointer;${x.id === M3T.id ? 'background:var(--red-bg)' : ''}" onclick="M3T.id=${x.id};route()">${recCb('m3_task', x)}<div><strong>#${x.id} ${esc(x.title)}</strong><small>${esc(x.created_by)} · ${esc(x.created_at)}</small>${recBtns('m3_task', x)}</div><em class="status ${['已定稿', '已总结'].includes(x.status) ? 'done' : x.status === '失败' ? 'risk' : 'review'}">${esc(x.status)}</em></div>`).join('') || '<p class="small panel-b">暂无任务</p>'}</div></div></div>
   <div id="m3task">${t ? m3TaskHtml(t) : ''}</div>`;
  if (t && M3_RUNNING.includes(t.status)) m3Poll();
}
function m3Poll() {
  M3T.timer = setTimeout(async () => {
    if (!location.hash.startsWith('#m3') || !M3T.id) return;
    const t = await api('/api/m3/tasks/' + M3T.id).catch(() => null);
    if (!t) return;
    $('#m3task') && ($('#m3task').innerHTML = m3TaskHtml(t));
    if (M3_RUNNING.includes(t.status)) m3Poll(); else route();
  }, 1000);
}
function m3Marked(text, chk) {
  const items = (chk && chk.items) || [];
  return (text || '').split('\n').filter(p => p.trim()).map((para, pi) => {
    if (/^[一二三四五六七八九十]+、/.test(para) && para.length < 40) return `<h3 style="margin:12px 0 4px">${esc(para)}</h3>`;
    const ss = para.match(/[^。！？；!?;\n]+[。！？；!?;]?/g) || [];
    return '<p style="line-height:1.9;margin:4px 0">' + ss.map((s, si) => {
      const it = items.find(i => i.para === pi + 1 && i.sent === si + 1);
      if (!it) return esc(s);
      const tip = `${it.status}｜${it.kinds.join('、')}${it.missing.length ? '｜' + it.missing.join('；') : ''}${it.confirmed ? '｜人工确认：' + it.confirmed.reason : ''}`;
      const st = it.red ? 'color:#c00000;background:#fdeaea;font-weight:600' : it.confirmed ? 'background:#fff6dd' : 'border-bottom:2px solid #3a9b5c';
      return `<span style="${st}" title="${esc(tip)}">${esc(s)}</span>`;
    }).join('') + '</p>';
  }).join('');
}
function m3TaskHtml(t) {
  const chk = t.final_check || t.check_result;
  const running = M3_RUNNING.includes(t.status), done = ['已定稿', '已总结'].includes(t.status);
  const tok = Object.entries(t.tokens || {}).map(([k, n]) => `${{ writer: '写作', checker: '核对', summarizer: '总结' }[k] || k} ${n}`).join(' · ') || '0';
  const last = t.events[t.events.length - 1] || {};
  const reds = chk ? chk.items.filter(i => i.red) : [];
  return `<div class="kv mb"><div><span>状态</span><b style="font-size:15px">${esc(t.status)}</b></div><div><span>当前阶段</span><b style="font-size:13px">${esc(t.stage)}${last.segment ? ' · 段 ' + last.segment : ''}</b></div>
   <div><span>已用时</span><b>${(t.elapsed_ms / 1000).toFixed(1)} s</b></div><div><span>Tokens（${t.tokens_total}）</span><b style="font-size:12.5px">${esc(tok)}</b></div></div>
  ${t.error ? `<div class="alert error mb">${t.status === '已中断' ? '已中断' : '失败'}：${esc(t.error)} ${['已中断', '失败'].includes(t.status) ? `<button class="primary mini" onclick="m3Rerun(${t.id})">重新运行</button>` : ''}</div>` : ''}
  <div class="grid2 mb" style="grid-template-columns:1.3fr .7fr"><div class="panel"><div class="panel-head"><div><h2>${done ? '终稿' : 'AI 初稿（核对标注）'}：${esc(t.title)}</h2><p>红色 = 核对未通过（无出处 / 数字或名称在所引来源中找不到），阻止定稿；绿色下划线 = 已核实；黄色 = 人工确认。鼠标悬停查看原因。</p></div>
    <div>${done ? mailBtn('m3_report', t.id) + ' ' : ''}${t.draft ? `<button class="secondary mini" onclick="download('/api/m3/tasks/${t.id}/export.docx')">导出 Word（含登记表）</button> <button class="secondary mini" onclick="download('/api/m3/tasks/${t.id}/export.md')">导出 Markdown</button>` : ''}</div></div>
    <div class="panel-b" style="max-height:520px;overflow:auto">${t.draft ? m3Marked(done || t.final_check ? t.final : t.draft, chk) : '<p class="small">写作中…</p>'}</div></div>
   <div class="panel"><div class="panel-head"><div><h2>实时进度</h2><p>${running ? '每秒刷新' : ''}</p></div></div><div class="panel-b small" style="max-height:520px;overflow:auto">
    ${t.events.map(e => `<div style="margin-bottom:6px"><span class="pill ${e.agent === 'checker' ? 'gold' : e.agent === 'summarizer' ? 'green' : e.agent === 'system' ? 'red' : 'blue'}">${esc({ writer: '写作', checker: '核对', summarizer: '总结', system: '系统' }[e.agent] || e.agent)}</span> ${(e.elapsed_ms / 1000).toFixed(1)}s ${esc(e.stage)}${e.segment ? ' · 段' + e.segment : ''}：${esc(e.message)}${e.tokens ? ' · ' + e.tokens + ' tokens' : ''}${e.snippet ? `<div style="color:var(--sub)">${esc(e.snippet)}</div>` : ''}</div>`).join('')}</div></div></div>
  ${typeof codeLegendHtml === 'function' ? codeLegendHtml('cite level') : ''}
  ${chk ? `<div class="panel mb"><div class="panel-head"><div><h2>引用来源登记表（核对 Agent 生成）</h2><p>风险句 ${chk.risky}，已核实 ${chk.verified}，标红 <b style="color:var(--red)">${chk.red}</b>${chk.llm_warnings.length ? '；大模型核对提示 ' + chk.llm_warnings.length + ' 条（仅提示）' : ''}</p></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>编号</th><th>来源名称</th><th>类型</th><th>出处位置</th><th>原文摘录</th><th>链接</th><th>发布日期</th><th>核验状态</th></tr></thead><tbody>
   ${chk.register.map(r => `<tr><td>${esc(r.no)}</td><td class="l">${esc(r.source_name)}</td><td>${esc(r.level)}</td><td>${esc(r.location)}</td><td class="l small" style="max-width:320px">${esc((r.excerpt || '').slice(0, 160))}</td><td class="l small">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">链接</a>` : ''}</td><td>${esc(r.pub_date || '')}</td><td><span class="pill ${r.status === '已核实' ? 'green' : r.status === '人工确认' ? 'gold' : 'red'}">${esc(r.status)}</span></td></tr>`).join('')}</tbody></table></div>
   ${chk.llm_warnings.length ? `<div class="panel-b small">${chk.llm_warnings.map(w => `⚠ 「${esc(w.text)}」${esc(w.problem)}（${esc(w.severity || '')}）`).join('<br>')}</div>` : ''}</div>` : ''}
  ${t.draft && !running ? `<div class="grid2 mb"><div class="panel"><div class="panel-head"><div><h2>人工修改终稿</h2><p>保存后重新执行规则核对；所有标红句须改正或人工确认（须填理由）后方可定稿。</p></div>
    ${done ? '<span class="pill green">已定稿</span>' : '<div><button class="secondary mini" onclick="m3SaveFinal()">保存并复核</button> <button class="primary mini" onclick="m3Finalize()">定稿</button></div>'}</div>
    <div class="panel-b"><textarea class="in" id="m3final" style="width:100%;min-height:340px" ${done ? 'disabled' : ''}>${esc(t.final || t.draft)}</textarea></div></div>
   <div class="panel"><div class="panel-head"><div><h2>${done ? '总结 Agent' : '标红句处理（' + reds.length + '）'}</h2></div>${done ? `<button class="primary mini" onclick="m3Summarize()" ${t.status === '已总结' ? 'disabled' : ''}>${t.status === '已总结' ? '已总结' : '对比初稿/终稿并沉淀规范'}</button>` : ''}</div><div class="panel-b small" style="max-height:380px;overflow:auto">
    ${done ? (t.summary_result ? `<p class="mb">初稿 → 终稿 ${t.summary_result.n_changes} 处修改（${esc(t.summary_result.method)}），沉淀规范 ${t.summary_result.entries.length} 条（下次写作自动注入）：</p>${t.summary_result.entries.map(e => `<div>• [${esc(e.category)}] ${esc(e.content)}</div>`).join('')}<hr>${t.summary_result.diff.slice(0, 20).map(o => `<div style="margin:4px 0"><b>${esc(o.op)}</b>：<del style="color:#c00">${esc(o.draft.slice(0, 120))}</del> → <ins style="color:#2a7">${esc(o.final.slice(0, 120))}</ins></div>`).join('')}` : '定稿后点击右上角，由总结 Agent 对比初稿与终稿。')
      : reds.map(i => `<div class="mb" style="border-left:3px solid #c00;padding-left:8px"><div style="color:#c00">${esc(i.text)}</div><div>${esc(i.status)}：${esc(i.missing.join('；') || '无出处标注')}</div>
       <div class="form-row" style="margin:4px 0"><input class="in" style="flex:1" id="cf_${i.key}" placeholder="人工确认理由（如：已与原始文件核对）"><button class="secondary mini" onclick="m3Confirm('${i.key}')">人工确认</button></div></div>`).join('') || '<p>无标红句，可定稿。</p>'}</div></div></div>` : ''}
  ${t.sources.length ? `<div class="panel"><div class="panel-head"><div><h2>资料清单（${t.sources.length}）${t.facts.length ? ' · M5 数据 ' + t.facts.length + ' 项' : ''}</h2></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>编号</th><th>类型</th><th>等级</th><th>标题</th><th>发布方</th><th>日期</th></tr></thead><tbody>
   ${t.sources.map(s => `<tr><td>${s.id}</td><td>${esc(s.type)}</td><td>${esc(s.level)}</td><td class="l"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></td><td class="l">${esc(s.publisher)}</td><td>${esc(s.pub_date || '')}</td></tr>`).join('')}
   ${t.facts.map(f => `<tr><td>${f.id}</td><td>M5 数据库</td><td>内部台账</td><td class="l">${esc(f.name)}：${esc(f.value)}</td><td class="l">${esc(f.source)}</td><td></td></tr>`).join('')}</tbody></table></div></div>` : ''}`;
}
async function m3Create() {
  const body = { title: $('#t_title').value, requirements: $('#t_req').value, genre: $('#t_genre').value, words: +$('#t_words').value, tone: $('#t_tone').value, data_date: $('#t_dd').value || null,
    use_kb: $('#t_kb').checked, use_web: $('#t_web').checked, use_m5: $('#t_m5').checked };
  const r = await api('/api/m3/tasks', { method: 'POST', json: body }); M3T.id = r.id; toast('任务已开始'); route();
}
async function m3SaveFinal() { const c = await api(`/api/m3/tasks/${M3T.id}/final`, { method: 'PUT', json: { final: $('#m3final').value } }); toast(c.red ? `仍有 ${c.red} 句标红` : '复核通过，可定稿'); route(); }
async function m3Confirm(key) { await api(`/api/m3/tasks/${M3T.id}/final`, { method: 'PUT', json: { final: $('#m3final').value } }); await api(`/api/m3/tasks/${M3T.id}/confirm`, { method: 'POST', json: { key, reason: $('#cf_' + key).value } }); toast('已人工确认（留痕）'); route(); }
async function m3Finalize() { await api(`/api/m3/tasks/${M3T.id}/final`, { method: 'PUT', json: { final: $('#m3final').value } }); await api(`/api/m3/tasks/${M3T.id}/finalize`, { method: 'POST' }); toast('已定稿'); route(); }
async function m3Summarize() { toast('总结 Agent 运行中…'); await api(`/api/m3/tasks/${M3T.id}/summarize`, { method: 'POST' }); route(); }
async function m3Style(v, head) {
  const rows = await api('/api/m3/style');
  v.innerHTML = head + `<div class="panel panel-b mb"><div class="form-row" style="margin:0"><label>类别<select class="in" id="sg_c">${['心得', '措辞', '结构', '口径'].map(x => `<option>${x}</option>`).join('')}</select></label><label style="flex:1">规范内容<input class="in" id="sg_t" placeholder="例如：涉及本公司数据须注明统计时点"></label><button class="primary" onclick="m3StyleAdd()">新增</button></div></div>
  <div class="panel"><div class="panel-head"><div><h2>写作规范库（${rows.length}）</h2><p>启用的条目会注入研究及写作 Agent 的系统提示词（最近 N 条，N 由管理员设置）。</p></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>启用</th><th>类别</th><th>内容</th><th>来源</th><th>时间</th><th></th></tr></thead><tbody>
  ${rows.map(r => `<tr><td><input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="api('/api/m3/style/${r.id}',{method:'PUT',json:{enabled:this.checked}}).then(()=>toast('已更新'))"></td><td>${esc(r.category)}</td><td class="l">${esc(r.content)}</td><td class="small">${r.source_task_id ? '任务 #' + r.source_task_id + '（总结 Agent）' : esc(r.created_by)}</td><td class="small">${esc(r.created_at)}</td><td><a class="edit" onclick="m3StyleDel(${r.id})">删除</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">暂无</td></tr>'}</tbody></table></div></div>`;
}
async function m3StyleAdd() { await api('/api/m3/style', { method: 'POST', json: { category: $('#sg_c').value, content: $('#sg_t').value } }); route(); }
async function m3StyleDel(id) { if (confirm('删除该条规范？')) { await api('/api/m3/style/' + id, { method: 'DELETE' }); route(); } }

/* ================= 系统管理：M2 规则 / M3 Agent ================= */
async function admM2(v, head) {
  const c = await api('/api/m2/config');
  const num = (id, val, step = 'any') => `<input class="in" id="${id}" type="number" step="${step}" value="${val}" style="width:90px">`;
  v.innerHTML = head + `<div class="grid2 mb"><div class="panel panel-b"><h2 class="mb">重要度权重（四项之和 = 1）</h2>
   <div class="form-row"><label>来源等级${num('w_level', c.weights.level)}</label><label>政策层级${num('w_layer', c.weights.layer)}</label><label>业务相关度${num('w_rel', c.weights.relevance)}</label><label>时效性${num('w_tm', c.weights.timeliness)}</label></div>
   <div class="form-row"><label>★★★ 阈值${num('t3', c.tiers.three)}</label><label>★★ 阈值${num('t2', c.tiers.two)}</label><label>取数窗口（小时）${num('wh', c.window_hours, 1)}</label><label>最多条目${num('mx', c.max_items, 1)}</label></div>
   <div class="form-row"><label><span><input type="checkbox" id="m2sch" ${c.schedule.enabled ? 'checked' : ''}> 每日定时生成</span></label><label>时间（北京时间）<input class="in" id="m2time" value="${esc(c.schedule.time)}" style="width:80px"></label>
    <label><span><input type="checkbox" id="m2m5" ${c.include_m5 ? 'checked' : ''}> 数据速览取 M5</span></label><label><span><input type="checkbox" id="m2llm" ${c.use_llm ? 'checked' : ''}> 用模型提炼要点</span></label></div></div>
  <div class="panel panel-b"><h2 class="mb">分项得分</h2>
   <div class="form-row">${Object.entries(c.level_scores).map(([k, x]) => `<label>${k}${num('ls_' + k, x, 1)}</label>`).join('')}</div>
   <div class="form-row">${Object.entries(c.layer_scores).map(([k, x]) => `<label>${k}${num('ly_' + k, x, 1)}</label>`).join('')}</div>
   <div class="form-row">${c.timeliness.map((t, i) => `<label>${t.days} 天内${num('tm_' + i, t.score, 1)}</label>`).join('')}<label>更早${num('tm_old', c.timeliness_older, 1)}</label></div>
   <div class="form-row"><label style="flex:1">业务关键词及权重（每行「关键词 权重」，命中累加，上限 100）<textarea class="in" id="kw" style="min-height:140px">${esc(Object.entries(c.keywords).map(([k, x]) => k + ' ' + x).join('\n'))}</textarea></label></div></div></div>
  <button class="primary" onclick="admM2Save()">保存简报规则</button> <button class="ghost" onclick="admM2Reset()">恢复默认</button>`;
  ADM.m2 = c;
}
async function admM2Save() {
  const c = ADM.m2, n = id => +$('#' + id).value;
  const kw = {}; $('#kw').value.split('\n').forEach(l => { const m = l.trim().match(/^(.+?)\s+(\d+)$/); if (m) kw[m[1]] = +m[2]; });
  const body = { weights: { level: n('w_level'), layer: n('w_layer'), relevance: n('w_rel'), timeliness: n('w_tm') }, tiers: { three: n('t3'), two: n('t2') }, window_hours: n('wh'), max_items: n('mx'),
    schedule: { enabled: $('#m2sch').checked, time: $('#m2time').value.trim() }, include_m5: $('#m2m5').checked, use_llm: $('#m2llm').checked,
    level_scores: Object.fromEntries(Object.keys(c.level_scores).map(k => [k, n('ls_' + k)])), layer_scores: Object.fromEntries(Object.keys(c.layer_scores).map(k => [k, n('ly_' + k)])),
    timeliness: c.timeliness.map((t, i) => ({ days: t.days, score: n('tm_' + i) })), timeliness_older: n('tm_old'), keywords: kw };
  await api('/api/admin/m2/config', { method: 'PUT', json: body }); toast('简报规则已保存'); route();
}
async function admM2Reset() { if (confirm('恢复默认简报规则？')) { await api('/api/admin/m2/config/reset', { method: 'POST' }); route(); } }
async function admM3(v, head) {
  const [ag, models, prompts] = await Promise.all([api('/api/m3/agents'), api('/api/llm/models'), api('/api/admin/m3/prompts')]);
  const LV = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
  v.innerHTML = head + `<div class="note-box mb">每个 Agent 可单独指定模型、温度与版本化提示词模板；「知识范围」限定研究及写作 Agent 可检索的来源等级/政策层级。勾选「插入 M5 数据」的任务要求所有 Agent 使用允许处理敏感数据的模型。</div>
  ${Object.entries(ag.names).map(([k, n]) => { const a = ag.agents[k]; const ps = prompts.filter(p => p.agent === k); const act = ps.find(p => p.active) || ps[0] || {};
    return `<div class="panel mb" data-agent="${k}"><div class="panel-head"><div><h2>${n}</h2><p>技能：${esc((a.skills || []).join('、'))}</p></div></div><div class="panel-b">
    <div class="form-row"><label>模型<select class="in a_model"><option value="">（沿用页面选择）</option>${models.models.map(m => `<option value="${m.id}" ${a.model_id === m.id ? 'selected' : ''}>${esc(m.label)}${m.allow_sensitive ? ' 🔒' : ''}</option>`).join('')}</select></label>
     <label>temperature<input class="in a_t" type="number" step="0.1" value="${a.temperature ?? ''}" style="width:80px"></label><label>top_p<input class="in a_p" type="number" step="0.05" value="${a.top_p ?? ''}" style="width:80px"></label>
     <label>超时(秒)<input class="in a_to" type="number" value="${a.timeout}" style="width:80px"></label><label><span><input type="checkbox" class="a_en" ${a.enabled ? 'checked' : ''}> 启用</span></label></div>
    ${k === 'writer' ? `<div class="form-row"><label>知识范围 · 来源等级 ${LV.map(l => `<span><input type="checkbox" class="a_lv" value="${l}" ${a.scope.levels.includes(l) ? 'checked' : ''}> ${l}</span>`).join(' ')}</label>
      <label>政策层级（空=全部）<input class="in a_ly" value="${esc((a.scope.layers || []).join(' '))}" placeholder="国家 省级 …"></label><label>知识库条数<input class="in a_kb" type="number" value="${a.scope.kb_max}" style="width:70px"></label><label>联网条数<input class="in a_web" type="number" value="${a.scope.web_max}" style="width:70px"></label></div>` : ''}
    ${k === 'summarizer' ? `<div class="form-row"><label>注入写作规范条数<input class="in a_me" type="number" value="${a.scope.max_entries}" style="width:80px"></label></div>` : ''}
    <div class="form-row"><label style="flex:1">提示词模板（当前启用 v${act.version || 0}；可用 {tone} {genre} {style_guide}）<textarea class="in a_prompt" style="min-height:150px">${esc(act.content || '')}</textarea></label></div>
    <div class="form-row"><label style="flex:1">版本说明<input class="in a_note" placeholder="本次修改说明"></label><button class="secondary mini" onclick="admM3Prompt('${k}')">保存为新版本并启用</button></div>
    <div class="small">历史版本：${ps.map(p => `<span class="pill ${p.active ? 'green' : 'gray'}" style="cursor:pointer" title="${esc(p.note || '')} ${esc(p.created_by)} ${esc(p.created_at)}" onclick="admM3Act(${p.id})">v${p.version}${p.active ? ' 启用中' : ''}</span>`).join(' ')}</div></div></div>`; }).join('')}
  <button class="primary" onclick="admM3Save()">保存 Agent 配置</button>`;
}
async function admM3Save() {
  const body = {};
  $$('[data-agent]').forEach(el => { const k = el.dataset.agent; const f = s => $(s, el); const sc = {};
    if (k === 'writer') Object.assign(sc, { levels: $$('.a_lv', el).filter(i => i.checked).map(i => i.value), layers: f('.a_ly').value.split(/\s+/).filter(Boolean), kb_max: +f('.a_kb').value, web_max: +f('.a_web').value });
    if (k === 'summarizer') sc.max_entries = +f('.a_me').value;
    body[k] = { model_id: f('.a_model').value || null, temperature: f('.a_t').value === '' ? null : +f('.a_t').value, top_p: f('.a_p').value === '' ? null : +f('.a_p').value, timeout: +f('.a_to').value, enabled: f('.a_en').checked, scope: sc }; });
  await api('/api/admin/m3/agents', { method: 'PUT', json: body }); toast('Agent 配置已保存'); route();
}
async function admM3Prompt(k) { const el = $(`[data-agent="${k}"]`); await api('/api/admin/m3/prompts', { method: 'POST', json: { agent: k, content: $('.a_prompt', el).value, note: $('.a_note', el).value } }); toast('已保存新版本并启用'); route(); }
async function admM3Act(id) { if (confirm('启用该版本？')) { await api(`/api/admin/m3/prompts/${id}/activate`, { method: 'POST' }); route(); } }

async function m3Rerun(id) { if (!confirm('重新运行该任务？（中间结果将重置）')) return; await api(`/api/m3/tasks/${id}/rerun`, { method: 'POST' }); toast('已重新开始'); route(); }
