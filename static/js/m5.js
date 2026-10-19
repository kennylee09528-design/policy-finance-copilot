/* 机构看板（M5） */
const M5 = { sid: null, d: null, charts: [] };
const PORT_NAMES = { regular: '常规业务', tech: '科技创新专项', private: '民间投资专项', t2t: '总对总' };
const M5_TABS = [['summary', '额度使用汇总'], ['inst', '分机构使用情况'], ['charts', '图表分析'], ['rules', '预警规则']];  // 「数据导入」页签按 PRD 1018 红线划掉已下线（后端接口与 m5Import 保留）

PAGES.m5 = async (v, sub) => {
  const isInst = ident().role === 'institution';
  if (sub === 'limits' || sub === 'import') sub = 'summary'; // 授信额度表页签已下线（后端与数据保留，看板计算仍依赖）
  sub = isInst ? 'inst' : (sub || 'summary');
  const snaps = await api('/api/m5/snapshots');
  if (!M5.sid || !snaps.find(s => s.id === M5.sid)) M5.sid = snaps[0] && snaps[0].id;
  M5.charts.forEach(c => c.dispose()); M5.charts = [];
  const head = `<div class="page-head"><div><h1>机构看板（M5）</h1><p>国担系统台账（常规/科创/民投/总对总 四端口）→ 自动汇总直保/再保使用情况 → 预警、环比说明、图表 → 导出。金额单位：万元，保留 2 位小数。</p></div>
  <div class="page-actions">${snaps.length ? `<label class="small">统计时点快照：<select class="in" onchange="M5.sid=+this.value;route()">${snaps.map(s => `<option value="${s.id}" ${s.id === M5.sid ? 'selected' : ''}>${esc(s.stat_date)} · #${s.id} ${esc(s.label || '')}</option>`).join('')}</select></label>` : ''}
  ${M5.sid && !isInst ? `<button class="secondary" onclick="download('/api/m5/snapshots/${M5.sid}/export.xlsx')">导出看板 Excel</button>` : ''}
  ${M5.sid && !['import', 'limits', 'rules'].includes(sub) ? `<button class="secondary" onclick="m5Pdf()">导出 PDF 快照</button>` : ''}</div></div>`;
  const tabs = isInst ? [['inst', '本机构额度使用情况']] : M5_TABS;
  if (!M5.sid && !['import', 'limits', 'rules'].includes(sub)) {
    v.innerHTML = head + subtabs(tabs, sub, 'm5') + `<div class="panel panel-b"><div class="empty">尚无看板快照。${isInst ? '' : `<br><br><button class="primary" onclick="m5Sample()">一键导入样例（9月19日额度表 + 四端口台账）</button>`}</div></div>`; return;
  }
  const d = M5.sid && !['import', 'limits', 'rules'].includes(sub) ? await api(`/api/m5/snapshots/${M5.sid}/dashboard`) : null;
  M5.d = d;
  v.innerHTML = head + subtabs(tabs, sub, 'm5') + '<div id="m5body"></div>';
  await ({ summary: m5Summary, inst: m5Inst, charts: m5Charts, import: m5Import, limits: m5Limits, rules: m5Rules })[sub]($('#m5body'), d);
};
async function m5Sample() { const r = await api('/api/m5/snapshots/sample', { method: 'POST', json: {} }); M5.sid = r.snapshot_id; toast('已导入样例'); nav('m5', 'summary'); route(); }

/* ---- 汇总页（版式同「1.业务额度使用情况」汇总页） ---- */
function m5Summary(el, d) {
  setTimeout(m5FillAi, 0);
  const S = d.summary, rate = (x) => x === undefined ? '' : pct(x);
  const cell = (o, k, fmt = f2) => `<td class="n">${o && o[k] !== undefined ? fmt(o[k]) : ''}</td>`;
  const rowsHtml = ['regular', 'tech', 'private', 't2t'].map(p => { const s = S[p]; if (!s) return '';
    return `<tr><td class="lbl">${PORT_NAMES[p]}</td><td class="n">${f2(s.guodan)}</td>
    ${cell(s.direct, 'alloc')}${cell(s.direct, 'amount')}${cell(s.direct, 'delta')}${cell(s.direct, 'remain')}${cell(s.direct, 'rate', rate)}
    ${cell(s.reguar, 'alloc')}${cell(s.reguar, 'amount')}${cell(s.reguar, 'delta')}${cell(s.reguar, 'remain')}${cell(s.reguar, 'rate', rate)}
    ${cell(s.total, 'alloc')}${cell(s.total, 'amount')}${cell(s.total, 'delta')}${cell(s.total, 'remain')}${cell(s.total, 'rate', rate)}
    <td class="n">${s.unalloc !== undefined ? f2(s.unalloc) : ''}</td><td class="small">${esc(s.need_adjust || '')}</td>
    <td class="small">${esc(s.period_end || '')}${s.period_end && s.period_end !== d.snapshot.stat_date ? ' <span class="pill gold">与统计时点不一致</span>' : ''}<br>${s.direct_source === '缺失' ? '<span class="pill red">直保缺失</span>' : esc(s.direct_source || '')}</td></tr>`; }).join('');
  const reg = S.regular;
  el.innerHTML = alertsHtml(d.alerts.concat((d.limit_warnings || []).map(m => ({ level: 'warn', type: '额度表', msg: m })))) + `
  <div class="kv mb"><div><span>统计时点 / 时间进度</span><b>${esc(d.snapshot.stat_date)} / ${pct(d.time_progress)}</b></div>
  <div><span>常规业务累计备案（直保+再保）</span><b>${f2(reg.total.amount)}</b></div>
  <div><span>常规使用率（÷国担额度 ${f2(reg.guodan)}）</span><b>${pct(reg.total.rate)}</b></div>
  <div><span>常规剩余额度</span><b>${f2(reg.total.remain)}</b></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>业务额度使用情况汇总（截至 ${esc(d.snapshot.stat_date)}）</h2><p>使用率口径（Q3）：使用率 = 累计备案金额 ÷ 国担额度；常规直保/再保另提供「÷分配额度」口径，见悬浮提示。额度表：${esc(d.limit_set ? d.limit_set.name : '未设置')}</p></div></div>
  <div class="tbl-wrap"><table class="grid sum-table"><thead>
  <tr><th rowspan="2">业务类型</th><th rowspan="2">国担额度</th><th colspan="5">直保</th><th colspan="5">再保</th><th colspan="5">合计</th><th rowspan="2">剩余未分配</th><th rowspan="2">需调整</th><th rowspan="2">台账截止 / 直保来源</th></tr>
  <tr>${'<th>分配额度</th><th>累计备案</th><th>较上期新增</th><th>剩余额度</th><th>使用率</th>'.repeat(3)}</tr></thead><tbody>${rowsHtml}</tbody></table></div>
  <div class="panel-b small">常规业务按分配额度口径：直保 ${pct(reg.direct.rate_alloc)}，再保 ${pct(reg.reguar.rate_alloc)}，合计 ${pct(reg.total.rate_alloc)}。科技、民间汇总不计使用率（Q4）。</div></div>
  <div class="grid2"><div class="panel panel-b"><h2 class="mb">环比说明（自动生成，可编辑）</h2>
  ${['regular', 'tech', 'private', 't2t'].map(p => `<label class="small">${PORT_NAMES[p]} ${d.notes_edited[p] ? '<span class="pill blue">已人工修改</span>' : ''}</label><textarea class="in m5note mb" data-p="${p}">${esc(d.notes[p] || '')}</textarea>`).join('')}
  <button class="primary" onclick="m5SaveNotes()">保存说明</button> <button class="ghost" onclick="m5ResetNotes()">恢复自动生成</button>
  <div class="form-row" style="margin-top:12px"><label>AI 润色（仅可选已授权处理敏感数据的模型 🔒）<select class="in" id="m5ai_m"></select></label><button class="secondary" onclick="m5AiNotes()">AI 润色</button></div><div id="m5ai_out"></div></div>
  <div class="panel panel-b"><h2 class="mb">直保数据人工补录</h2><p class="small mb">科创、民投台账若无直保主体行，可在此按国担系统数据人工补录直保累计备案金额（需填原因，留痕）。</p>
  <div class="form-row"><label>业务类型<select class="in" id="md_p">${Object.entries(PORT_NAMES).map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}</select></label>
  <label>直保累计备案（万元，留空=清除）<input class="in" id="md_v" type="number" step="any"></label></div>
  <div class="form-row"><label style="flex:1">原因（必填）<input class="in" id="md_r"></label></div><button class="secondary" onclick="m5ManualDirect()">保存补录</button>
  <h2 style="margin:18px 0 8px">台账端口</h2><table class="grid"><thead><tr><th>端口</th><th>文件</th><th>备案截止</th><th>合计</th><th>直保</th><th>再保</th></tr></thead><tbody>
  ${Object.entries(PORT_NAMES).map(([k, n]) => { const p = d.ports[k]; return `<tr><td>${n}</td><td class="l">${p ? esc(p.file) : '<span class="pill red">未导入</span>'}</td><td>${p ? esc(p.period_end || '') : ''}</td><td class="n">${p ? f2(p.total) : ''}</td><td class="n">${p ? f2(p.direct) : ''}</td><td class="n">${p ? f2(p.reguar) : ''}</td></tr>`; }).join('')}</tbody></table></div></div>`;
}
async function m5FillAi() {
  const sel = $('#m5ai_m'); if (!sel) return;
  try { const d = await api('/api/llm/models'); const ms = d.models.filter(m => m.allow_sensitive);
    sel.innerHTML = ms.length ? ms.map(m => `<option value="${m.id}" ${d.assign['m5.notes'] === m.id ? 'selected' : ''}>${esc(m.label)} 🔒</option>`).join('') : '<option value="">（无已授权模型，请管理员配置公司私有模型）</option>';
    sel.onchange = () => api('/api/llm/assign', { method: 'POST', json: { slot: 'm5.notes', model_id: sel.value } });
  } catch (e) {}
}
async function m5AiNotes() {
  const mid = $('#m5ai_m').value; if (!mid) return toast('没有已授权处理敏感数据的模型');
  $('#m5ai_out').innerHTML = '<p class="small">生成中…</p>';
  try { const r = await api(`/api/m5/snapshots/${M5.sid}/notes/ai`, { method: 'POST', json: { model_id: +mid } });
    $('#m5ai_out').innerHTML = `<div class="note-box">【${esc(r.model)} · ${r.ms}ms，请核对数字后手工采用】<br>${esc(r.content).replace(/\n/g, '<br>')}</div>`;
  } catch (e) { $('#m5ai_out').innerHTML = ''; }
}
async function m5SaveNotes() { const notes = {}; $$(".m5note").forEach(t => { if (t.value !== M5.d.notes_auto[t.dataset.p]) notes[t.dataset.p] = t.value; }); await api(`/api/m5/snapshots/${M5.sid}/notes`, { method: 'POST', json: { notes } }); toast('已保存'); route(); }
async function m5ResetNotes() { const notes = {}; await api(`/api/m5/snapshots/${M5.sid}/notes`, { method: 'POST', json: { notes } }); toast('已恢复'); route(); }
async function m5ManualDirect() { const reason = $('#md_r').value.trim(); if (!reason) return toast('请填写原因'); await api(`/api/m5/snapshots/${M5.sid}/manual-direct`, { method: 'POST', json: { port: $('#md_p').value, value: $('#md_v').value, reason } }); toast('已补录'); route(); }

/* ---- 分机构 ---- */
const WARN_PILL = { over: 'red', red: 'red', yellow: 'gold', check: 'blue' };
function m5Inst(el, d) {
  const t = d.totals || {};
  el.innerHTML = (ident().role === 'institution' ? `<div class="alert info mb">机构用户视图：仅显示本机构数据（行级权限）。</div>` : alertsHtml(d.alerts.filter(a => /名单/.test(a.msg)))) + `
  <div class="panel"><div class="panel-head"><div><h2>分机构额度使用情况（截至 ${esc(d.snapshot.stat_date)}，时间进度 ${pct(d.time_progress)}）</h2><p>红色：使用率 ≥ ${pct(d.rules.red)} 或超额；黄色：时间进度 ≥ ${pct(d.rules.lag_time)} 但使用率 &lt; ${pct(d.rules.lag_rate)}（进度滞后）。</p></div>
  <input class="in" placeholder="筛选机构…" oninput="$$('#m5tb tr').forEach(r=>r.style.display=r.textContent.includes(this.value)?'':'none')"></div>
  <div class="tbl-wrap"><table class="grid inst-grid" id="m5inst"><thead><tr><th>序号</th><th>机构</th><th>常规授信额度</th><th>常规累计备案</th><th>常规使用率</th><th>常规剩余</th><th>常规占比</th><th>科创备案</th><th>民间额度</th><th>民间备案</th><th>民间使用率</th><th>总对总备案</th><th>合计备案</th><th>常规较上期</th><th>预警</th></tr></thead><tbody id="m5tb">
  ${d.rows.map(r => { const lv = r.warn.map(w => w.level); const rc = lv.includes('over') || lv.includes('red') ? 'bad' : '';
    return `<tr><td>${r.seq ?? ''}</td><td class="l" title="${esc(r.name)}">${esc(r.name)}${r.in_limits ? '' : ' <span class="pill red">不在额度表</span>'}</td><td class="n">${f2(r.regular_limit)}</td><td class="n">${f2(r.regular_amt)}</td>
    <td class="n ${rc}" style="${lv.includes('yellow') ? 'background:#fff6dc' : ''}">${pct(r.regular_rate)}</td><td class="n">${f2(r.regular_remain)}</td><td class="n">${pct(r.regular_share)}</td><td class="n">${f2(r.tech_amt)}</td>
    <td class="n" title="${esc(r.private_note || '')}">${f2(r.private_limit)}</td><td class="n">${f2(r.private_amt)}</td><td class="n">${pct(r.private_rate)}</td><td class="n">${f2(r.t2t_amt)}</td><td class="n">${f2(r.total_amt)}</td><td class="n">${r.delta.regular == null ? '—' : sgn(r.delta.regular)}</td>
    <td class="warn-cell" title="${esc(r.warn.map(w => w.msg).join('\n'))}">${r.warn.map(w => `<span class="pill ${WARN_PILL[w.level] || 'gray'}" title="${esc(w.msg)}">${esc(w.msg)}</span>`).join(' ')}</td></tr>`; }).join('')}
  ${t.regular_limit !== undefined ? `<tr class="tot"><td></td><td>合计（${d.rows.length} 家）</td><td class="n">${f2(t.regular_limit)}</td><td class="n">${f2(t.regular_amt)}</td><td class="n">${pct(t.regular_amt / t.regular_limit)}</td><td></td><td></td><td class="n">${f2(t.tech_amt)}</td><td class="n">${f2(t.private_limit)}</td><td class="n">${f2(t.private_amt)}</td><td></td><td class="n">${f2(t.t2t_amt)}</td><td class="n">${f2(t.total_amt)}</td><td></td><td></td></tr>` : ''}
  </tbody></table></div></div>`;
  colResize($('#m5inst'));
}

/* 轻量列宽拖拽：拖动表头右边缘调整列宽（首次拖动时冻结当前各列宽并切换为 fixed 布局） */
function colResize(tbl) {
  if (!tbl) return; const ths = [...tbl.querySelectorAll('thead th')];
  ths.forEach((th, i) => { const h = document.createElement('span'); h.className = 'col-rz'; h.title = '拖动调整列宽'; th.appendChild(h);
    h.onmousedown = e => { e.preventDefault(); e.stopPropagation();
      if (!tbl.classList.contains('rz-fixed')) { const ws = ths.map(x => x.getBoundingClientRect().width); ths.forEach((x, j) => x.style.width = ws[j] + 'px'); tbl.style.width = ws.reduce((a, b) => a + b, 0) + 'px'; tbl.classList.add('rz-fixed'); }
      const x0 = e.clientX, w0 = th.getBoundingClientRect().width, t0 = tbl.getBoundingClientRect().width; document.body.style.cursor = 'col-resize';
      const mv = ev => { const w = Math.max(40, w0 + ev.clientX - x0); th.style.width = w + 'px'; tbl.style.width = (t0 + w - w0) + 'px'; };
      const up = () => { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); document.body.style.cursor = ''; };
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up); }; });
}

/* ---- 图表 ---- */
function m5Chart(id, opt) { const c = echarts.init(document.getElementById(id)); c.setOption(opt); M5.charts.push(c); return c; }
function shortName(n) { return n.replace(/融资再担保|融资担保|投资|股份|有限责任公司|有限公司|集团|普惠金融/g, '').replace(/[（）()]/g, '').slice(0, 8); }
function m5Charts(el, d) {
  el.innerHTML = `<div class="panel panel-b mb"><h2>各机构常规额度使用率（降序）</h2><p class="small">红色 &gt; 100%（超额）；黄色 &lt; 50%；虚线为时间进度 ${pct(d.time_progress)}</p><div id="ch1" class="chart" style="height:460px"></div></div>
  <div class="grid2 mb"><div class="panel panel-b"><h2>时间进度 vs 使用率（散点）</h2><p class="small">横轴常规授信额度，纵轴使用率；低于时间进度线即为进度落后</p><div id="ch2" class="chart"></div></div>
  <div class="panel panel-b"><h2>直保 / 再保累计备案对比（按业务类型）</h2><p class="small">科创、民投台账无直保行时显示为 0（数据缺失）</p><div id="ch3" class="chart"></div></div></div>
  <div class="panel panel-b"><h2>各机构累计备案构成（按业务类型堆叠）</h2><div id="ch4" class="chart" style="height:460px"></div></div>`;
  const rows = d.rows.filter(r => r.regular_rate != null).sort((a, b) => b.regular_rate - a.regular_rate);
  const tp = d.time_progress;
  m5Chart('ch1', { tooltip: { trigger: 'axis', valueFormatter: v => v + '%' }, grid: { left: 50, right: 90, bottom: 110, top: 20 },
    xAxis: { type: 'category', data: rows.map(r => shortName(r.name)), axisLabel: { rotate: 50, fontSize: 11 } }, yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'bar', data: rows.map(r => ({ value: +(r.regular_rate * 100).toFixed(2), itemStyle: { color: r.regular_rate > 1 ? '#b0242e' : r.regular_rate < 0.5 ? '#e0a53a' : '#2f6fb0' } })),
      markLine: { symbol: 'none', data: [{ yAxis: +(tp * 100).toFixed(2), name: '时间进度', lineStyle: { type: 'dashed', color: '#555' }, label: { formatter: '时间进度 {c}%' } }, { yAxis: 100, lineStyle: { color: '#b0242e' }, label: { formatter: '100%' } }] } }] });
  m5Chart('ch2', { tooltip: { formatter: p => `${p.data[2]}<br>额度 ${f2(p.data[0])}<br>使用率 ${p.data[1]}%` }, grid: { left: 60, right: 90, top: 20, bottom: 40 },
    xAxis: { type: 'value', name: '常规额度', axisLabel: { formatter: v => (v / 10000) + '亿' } }, yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'scatter', symbolSize: 11, data: rows.map(r => [r.regular_limit, +(r.regular_rate * 100).toFixed(2), r.name]), itemStyle: { color: p => p.data[1] < tp * 100 ? '#e0a53a' : '#2f6fb0' },
      markLine: { symbol: 'none', data: [{ yAxis: +(tp * 100).toFixed(2) }], lineStyle: { type: 'dashed' }, label: { formatter: '时间进度 {c}%' } } }] });
  const ports = ['regular', 'tech', 'private', 't2t'];
  m5Chart('ch3', { tooltip: { trigger: 'axis', valueFormatter: v => f2(v) + ' 万元' }, legend: { data: ['直保', '再保'] }, grid: { left: 80, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: ports.map(p => PORT_NAMES[p]) }, yAxis: { type: 'value', axisLabel: { formatter: v => (v / 10000) + '亿' } },
    series: [{ name: '直保', type: 'bar', data: ports.map(p => (d.summary[p].direct || {}).amount || 0), itemStyle: { color: '#b0242e' } }, { name: '再保', type: 'bar', data: ports.map(p => (d.summary[p].reguar || {}).amount || 0), itemStyle: { color: '#2f6fb0' } }] });
  const r4 = d.rows.slice().sort((a, b) => (b.total_amt || 0) - (a.total_amt || 0));
  m5Chart('ch4', { tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: v => f2(v) }, legend: { data: ['常规', '科创', '民间', '总对总'] }, grid: { left: 70, right: 20, top: 40, bottom: 110 },
    xAxis: { type: 'category', data: r4.map(r => shortName(r.name)), axisLabel: { rotate: 50, fontSize: 11 } }, yAxis: { type: 'value', axisLabel: { formatter: v => (v / 10000) + '亿' } },
    series: [['常规', 'regular_amt', '#b0242e'], ['科创', 'tech_amt', '#2f6fb0'], ['民间', 'private_amt', '#e0a53a'], ['总对总', 't2t_amt', '#2c8a7a']].map(([n, k, c]) => ({ name: n, type: 'bar', stack: 'a', data: r4.map(r => r[k] || 0), itemStyle: { color: c } })) });
  window.onresize = () => M5.charts.forEach(c => c.resize());
}

/* ---- 数据导入 ---- */
async function m5Import(el) {
  const [ls, snaps] = await Promise.all([api('/api/m5/limit-sets'), api('/api/m5/snapshots' + recQ('m5_snapshot'))]);
  el.innerHTML = `<div class="panel panel-b mb"><h2 class="mb">新建统计时点快照：上传国担系统导出台账（四端口）</h2>
  <div class="form-row"><label>统计时点<input class="in" type="date" id="sn_d" value="${new Date().toISOString().slice(0, 10)}"></label><label>标签<input class="in" id="sn_l" placeholder="如：9月第3周"></label>
  <label>授信额度表<select class="in" id="sn_ls">${ls.map(x => `<option value="${x.id}">#${x.id} ${esc(x.name)}</option>`).join('')}</select></label></div>
  <div class="ports mb">${Object.entries(PORT_NAMES).map(([k, n]) => `<div class="drop"><b>${n}</b><br><input type="file" accept=".xlsx,.xls" id="pf_${k}"></div>`).join('')}</div>
  <button class="primary" onclick="m5Create()">生成快照</button> <button class="secondary" onclick="m5Sample()">导入内置样例（9月19日）</button>
  <p class="small" style="margin-top:8px">支持「机构业务规模分析」汇总格式与逐笔明细格式（直保/再保 + 备案金额）。直保主体默认为「示例省级融资再担保有限责任公司」，可在预警规则中配置。国担系统 API 自动拉取已预留接口（Q6）。</p></div>
  ${ls.length ? '' : '<div class="alert warn">尚无授信额度数据，可点击「导入内置样例」。</div>'}
  <div class="panel"><div class="panel-head"><div><h2>快照管理</h2><p>归档后不出现在看板的快照下拉中（可在「已归档」恢复）；删除移入回收站。</p></div>${recTabs('m5_snapshot')}</div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>#</th><th>统计时点</th><th>标签</th><th>已导入端口</th><th>额度表</th><th>创建</th><th></th></tr></thead><tbody>
  ${snaps.map(s => `<tr><td>${recCb('m5_snapshot', s)}</td><td>${s.id}</td><td>${esc(s.stat_date)}</td><td class="l">${esc(s.label || '')}</td><td class="small">${(s.ports || []).map(p => esc(PORT_NAMES[p] || p)).join('、')}</td><td>#${s.limit_set_id ?? '—'}</td><td class="small">${esc(s.created_by || '')} ${esc(s.created_at || '')}</td><td>${recBtns('m5_snapshot', s)} ${recBadge(s)}</td></tr>`).join('') || '<tr><td colspan="8" class="small">无记录</td></tr>'}</tbody></table></div></div>`;
}
async function m5Create() {
  const fd = new FormData(); fd.append('stat_date', $('#sn_d').value); fd.append('label', $('#sn_l').value); if ($('#sn_ls').value) fd.append('limit_set_id', $('#sn_ls').value);
  Object.keys(PORT_NAMES).forEach(k => { const f = $('#pf_' + k).files[0]; if (f) fd.append(k, f); });
  const r = await api('/api/m5/snapshots', { method: 'POST', body: fd }); M5.sid = r.snapshot_id; toast('快照已生成'); nav('m5', 'summary');
}

/* ---- 授信额度表 ---- */
async function m5Limits(el) {
  const ls = await api('/api/m5/limit-sets' + recQ('m5_limit_set')); const cur = (M5.lid && ls.some(x => x.id === M5.lid)) ? M5.lid : (ls[0] && ls[0].id);
  const d = cur ? await api('/api/m5/limit-sets/' + cur) : null; M5.ld = d;
  let schemes = []; try { schemes = await api('/api/m4/schemes'); } catch (e) {}
  el.innerHTML = `<div class="grid2 mb"><div class="panel panel-b"><h2 class="mb">额度表来源</h2>
  <div class="form-row"><div class="drop" style="flex:1"><b>导入额度表（1.业务额度使用情况 格式）</b><br><input type="file" accept=".xlsx" onchange="m5ImportLimits(this)"></div></div>
  <button class="secondary mb" onclick="m5LimitsSample()">导入内置样例额度表（截止9月19日 v1）</button>
  <div class="form-row"><label>从 M4 方案生成（M4 → M5 数据主线）<select class="in" id="fm4">${schemes.map(s => `<option value="${s.id}" ${s.is_current ? 'selected' : ''}>v${s.version} ${esc(s.name)}（${esc(s.status)}）</option>`).join('')}</select></label><button class="secondary" onclick="m5FromM4()">生成</button></div>
  <p class="small">注：M4 年初测算额度与 9 月实际使用的额度表（年中已多次调整）不同，看板验收以导入额度表为准。</p></div>
  <div class="panel panel-b"><div class="panel-head" style="padding:0 0 8px;border:0;flex-wrap:wrap;gap:6px"><h2>额度表版本</h2>${recTabs('m5_limit_set')}</div><table class="grid"><thead><tr><th></th><th>#</th><th>名称</th><th>创建</th><th></th></tr></thead><tbody>${ls.map(x => `<tr><td>${recCb('m5_limit_set', x)}</td><td>${x.id}</td><td class="l">${esc(x.name)}</td><td class="small">${esc(x.created_by)} ${esc(x.created_at)}</td><td><a class="edit" onclick="M5.lid=${x.id};route()">${x.id === cur ? '查看中' : '查看'}</a>${M5.sid ? `<a class="edit" onclick="m5UseLimit(${x.id})">用于当前快照</a>` : ''}${recBtns('m5_limit_set', x)} ${recBadge(x)}</td></tr>`).join('') || '<tr><td colspan="5" class="small">无记录</td></tr>'}</tbody></table></div></div>
  ${d ? `<div class="panel"><div class="panel-head"><div><h2>#${d.id} ${esc(d.name)}</h2><p>修改额度将生成新版本（需填原因）。</p></div><button class="primary mini" onclick="m5SaveLimits()">保存为新版本</button></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>机构</th><th>常规授信额度</th><th>民间专项额度</th><th>备注</th></tr></thead><tbody>
  ${d.data.institutions.map((r, i) => `<tr><td class="l">${esc(r.name)}</td><td><input class="in lim" data-i="${i}" data-k="regular" value="${r.regular ?? ''}" style="width:130px"></td><td><input class="in lim" data-i="${i}" data-k="private" value="${r.private ?? ''}" style="width:130px"></td><td class="small">${esc(r.private_note || '')}</td></tr>`).join('')}</tbody></table></div></div>` : ''}`;
}
async function m5ImportLimits(inp) { const fd = new FormData(); fd.append('file', inp.files[0]); const r = await api('/api/m5/limit-sets/import', { method: 'POST', body: fd }); M5.lid = r.limit_set_id; toast('已导入'); route(); }
async function m5LimitsSample() { const r = await api('/api/m5/limit-sets/import-sample', { method: 'POST' }); M5.lid = r.limit_set_id; toast('已导入'); route(); }
async function m5FromM4() { const r = await api('/api/m5/limit-sets/from-m4', { method: 'POST', json: { scheme_id: +$('#fm4').value } }); M5.lid = r.limit_set_id; toast('已从 M4 方案生成额度表'); route(); }
async function m5UseLimit(id) { await api(`/api/m5/snapshots/${M5.sid}/limit-set`, { method: 'POST', json: { limit_set_id: id } }); toast('当前快照已改用该额度表'); }
async function m5SaveLimits() {
  const reason = prompt('修改原因（必填）'); if (!reason) return;
  const data = JSON.parse(JSON.stringify(M5.ld.data)); $$('.lim').forEach(i => { data.institutions[+i.dataset.i][i.dataset.k] = i.value === '' ? null : Number(i.value); });
  const r = await api(`/api/m5/limit-sets/${M5.ld.id}`, { method: 'PUT', json: { data, reason } }); M5.lid = r.limit_set_id; toast('已保存新版本'); route();
}

/* ---- 预警规则 ---- */
async function m5Rules(el) {
  const r = await api('/api/m5/rules');
  const F = [['red', '红色预警：使用率 ≥'], ['over', '超额：使用率 >'], ['lag_time', '进度滞后：时间进度 ≥'], ['lag_rate', '且使用率 <'], ['swing', '环比波动核查阈值 ±'], ['low_hint', '图表黄色：使用率 <']];
  el.innerHTML = `<div class="panel panel-b" style="max-width:760px"><h2 class="mb">预警规则（可配置，比例填小数）</h2>
  <div class="form-row">${F.map(([k, l]) => `<label>${l}<input class="in rl" data-k="${k}" type="number" step="0.01" value="${r[k]}"></label>`).join('')}</div>
  <div class="form-row"><label style="flex:1">直保主体名称（台账中这些行计为直保，每行一个）<textarea class="in" id="rl_de">${esc((r.direct_entities || []).join('\n'))}</textarea></label></div>
  <p class="small mb">环比波动需至少 2 个历史快照才能判断。</p><button class="primary" onclick="m5SaveRules()">保存规则</button></div>`;
}
async function m5SaveRules() { const b = {}; $$('.rl').forEach(i => b[i.dataset.k] = +i.value); b.direct_entities = $('#rl_de').value.split('\n'); await api('/api/m5/rules', { method: 'PUT', json: b }); toast('已保存'); }

async function m5Pdf() {
  const d = M5.d; if (!d) return;
  const sub = (location.hash.split('/')[1] || (ident().role === 'institution' ? 'inst' : 'summary'));
  const name = { summary: '汇总页', inst: '分机构页', charts: '图表' }[sub] || sub;
  await printView('M5', d.snapshot.id, `机构看板_${d.snapshot.stat_date}_${name}.pdf`, `机构看板（M5） · ${name} · 统计时点 ${d.snapshot.stat_date}`, cloneWithCharts($('#m5body')));
}
