/* 机构授信管理（M4） */
const M4 = { scheme: null };
// 红字⑤：页签按编号调序（1 数据导入 → 2 参数配置 → 3 测算结果）
const M4_TABS = [['data', '① 数据导入与基础数据'], ['params', '② 参数配置'], ['result', '③ 测算结果'], ['spec', '口径说明'], ['versions', '方案版本'], ['qingshi', '请示生成'], ['history', '调整留痕']];
const M4_KIND = { third: '第三次调整', mintou: '民投完成率调整', cur_regular: '目前最新常规业务授信额度', cur_mintou: '目前最新民间投资授信额度' };
const m4n = v => f2(v);  // 万元，千分位，2 位小数
const STATUS_PILL = s => `<span class="pill ${s === '已批复' ? 'green' : s === '已上会' ? 'blue' : 'gray'}">${esc(s)}</span>`;

PAGES.m4 = async (v, sub) => {
  const cur = await api('/api/m4/schemes/current');
  sub = sub || (cur ? 'result' : 'data');
  M4.scheme = cur;
  const head = `<div class="page-head"><div><h1>机构授信管理（M4）</h1><p>导入附件2（9 张分表）→ 配置权重与常量 → 自动计算初步授信额度 → 人工增减目前最新授信额度（必填原因、留痕）→ 方案版本、请示。金额单位：万元。<b style="color:var(--red)">最终授信以请示批复为准。</b></p></div>
   <div class="page-actions">${cur ? `<span class="small">当前方案：v${cur.version} ${esc(cur.name)} ${STATUS_PILL(cur.status)}</span>
   <button class="secondary" onclick="download('/api/m4/schemes/${cur.id}/export.xlsx')">导出测算表 Excel</button>` : ''}</div></div>`;
  if (!cur && sub !== 'data') { v.innerHTML = head + subtabs(M4_TABS, sub, 'm4') + `<div class="panel panel-b"><div class="empty">尚未导入数据。<br><br><button class="primary" onclick="m4ImportSample()">导入附件2 样例</button> 或 <a onclick="nav('m4','data')" class="edit">上传附件2</a></div></div>`; return; }
  v.innerHTML = head + subtabs(M4_TABS, sub, 'm4') + '<div id="m4body"></div>';
  await ({ result: m4Result, data: m4Data, params: m4Params, spec: m4Spec, versions: m4Versions, qingshi: m4Qingshi, history: m4History })[sub]($('#m4body'), cur);
};

async function m4ImportSample() { const r = await api('/api/m4/import-sample', { method: 'POST' }); toast('已导入附件2 样例'); M4.lastAlerts = r.alerts; nav('m4', 'result'); route(); }
async function m4Upload(inp) {
  const fd = new FormData(); fd.append('file', inp.files[0]); fd.append('prefill', $('#m4prefill').checked ? 'true' : 'false');
  const r = await api('/api/m4/import', { method: 'POST', body: fd }); M4.lastAlerts = r.alerts; toast('导入完成'); nav('m4', 'result'); route();
}

/* ---- 测算结果 ---- */
// 红字①②：去掉名单差异/口径未核备横幅、汇总卡片与「与附件2原表核对」说明；主表只显示「初步授信额度」与「目前最新授信额度」，测算步骤可展开
async function m4Result(el, s) {
  const res = s.result, t = res.totals, locked = s.status !== '草稿';
  const pool = res.rows.filter(r => !r.fixed), fixed = res.rows.filter(r => r.fixed);
  const steps = !!M4.showSteps;
  const stepCols = [['J', '规模系数J', f4], ['L', '就业系数L', f4], ['N', '支小支农N', f4], ['P', '累计代偿P', f4], ['R', '当年代偿R', f4], ['T', '评价T', f4], ['U', '总系数U', f4],
    ['H', '2025符合民投H', m4n], ['V', '注册资本调整V', m4n], ['W', '第一次W', m4n], ['X', '第二次X', m4n], ['Z', '第三次Z', m4n], ['AA', '第四次AA', m4n], ['AB', '第五次AB', m4n], ['AH', '已备案占比AH', pct]];
  const wr = t.weights_normalized ? `<div class="alert error mb">【权重合计≠1】5 项权重合计 ${t.weight_sum.toFixed(4)}，已按比例归一后计算，应调整为合计=1（到「② 参数配置」修改）</div>` : '';
  const meta = res.meta || {};
  const miss = (res.alerts || []).filter(a => a.type === '数据缺失');
  const metaLine = `<div class="small mb">口径版本 <b>${esc(meta.formula_spec_version || '尚未打戳')}</b> · 参数 v${esc(meta.param_version != null ? meta.param_version : res.param.version)} · 数据集 #${esc(meta.dataset_id != null ? meta.dataset_id : s.dataset_id)} · <a class="edit" onclick="nav('m4','spec')">口径说明</a>。缺系数时告警，且不算总系数 U、不算第二次调整 X。</div>`;
  const curCell = (r, k) => { const d = r[k + '_delta']; return `<td class="n"${d ? ` title="台账现值 ${m4n(r[k + '_base'])}，人工增减 ${sgn(d)}"` : ''}>${m4n(r[k])}${d ? ' <span class="pill gold">已调</span>' : ''}</td>`; };
  const op = r => `<td><a class="edit" onclick="m4Drill('${esc(r.name)}')">明细</a>${locked ? '' : `<a class="edit" onclick="m4CurAdjust('${esc(r.name)}')">调整</a>`}</td>`;
  const body = pool.map(r => `<tr><td>${r.seq ?? ''}</td><td class="l" title="${esc(r.name)}">${esc(r.name)}</td>
    ${steps ? stepCols.map(([k, , fm]) => `<td class="n">${fm(r[k])}</td>`).join('') : ''}
    <td class="n" style="font-weight:700"${r.bonus ? ' title="AH≥40%，备案激励 +20,000"' : ''}>${m4n(r.AC)}${r.bonus ? ' <span class="pill green">+2亿</span>' : ''}</td>
    ${steps ? `<td class="n">${m4n(r.AI)}</td>` : ''}${curCell(r, 'cur_regular')}${curCell(r, 'cur_mintou')}${op(r)}</tr>`).join('');
  const fbody = fixed.map(r => `<tr class="fixed"><td>${r.seq ?? ''}</td><td class="l">${esc(r.name)} <span class="pill gold">固定额度</span></td><td class="n" style="font-weight:700">${m4n(r.AC)}</td>${curCell(r, 'cur_regular')}${curCell(r, 'cur_mintou')}${op(r)}</tr>`).join('');
  const refBody = res.rows.map(r => `<tr${r.fixed ? ' class="fixed"' : ''}><td class="l">${esc(r.name)}</td><td class="n">${m4n(r.tech_quota1)}</td><td class="n">${m4n(r.tech_quota)}</td><td class="n">${m4n(r.E)}</td><td class="n">${m4n(r.F)}</td><td class="n">${m4n(r.G)}</td><td class="n">${r.Y == null ? '' : m4n(r.Y)}</td><td class="n">${m4n(r.AG)}</td></tr>`).join('');
  el.innerHTML = wr + alertsHtml(miss) + metaLine + `<div class="note-box mb" style="margin-top:0">「初步授信额度」= 计算表 AC 列口径（权重 + 微调公式自动计算的台阶值，参考用）；「目前最新常规业务授信额度」= 申请表 C+D，「目前最新民间投资授信额度」= 申请表 F，为业务现行值，人工调整只作用于此。两者分栏、互不覆盖。<b>最终授信以请示批复为准。</b>单位：万元。</div>
  <div class="form-row mb" style="gap:8px;align-items:center"><button class="secondary" onclick="M4.showSteps=!M4.showSteps;route()">${steps ? '收起测算步骤' : '展开测算步骤（J~U、V、W、X、Z、AA、AB、AH、AI）'}</button>
   <button class="secondary" onclick="m4CompareExcel()">与 Excel AC 列对比</button>
   <button class="ghost" onclick="download('/api/m4/schemes/${s.id}/cur-log.xlsx')">导出调整记录</button>
   <span class="small">权重 ${Object.entries(res.param.weights).map(([k, w]) => 'w' + k + '=' + w).join(' / ')}（J 权重固定 1）</span></div>
  <div id="m4cmp"></div>
  <div class="panel mb"><div class="panel-head"><div><h2>参与系数测算机构（${pool.length} 家）</h2></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>序号</th><th>机构</th>
   ${steps ? stepCols.map(c => `<th>${c[1]}</th>`).join('') : ''}<th>初步授信额度<br><span class="small">AC</span></th>${steps ? '<th>机构总额度<br><span class="small">AI=AC+D</span></th>' : ''}<th>目前最新常规业务授信额度</th><th>目前最新民间投资授信额度</th><th></th></tr></thead><tbody>${body}
   <tr class="tot"><td></td><td>合计</td>${steps ? `<td colspan="${stepCols.length}"></td>` : ''}<td class="n">${m4n(pool.reduce((a, r) => a + (r.AC || 0), 0))}</td>${steps ? `<td class="n">${m4n(pool.reduce((a, r) => a + (r.AI || 0), 0))}</td>` : ''}<td class="n">${m4n(pool.reduce((a, r) => a + r.cur_regular, 0))}</td><td class="n">${m4n(pool.reduce((a, r) => a + r.cur_mintou, 0))}</td><td></td></tr></tbody></table></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>固定额度机构（${fixed.length} 家，不参与系数测算）</h2></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>序号</th><th>机构</th><th>初步授信额度（给定）</th><th>目前最新常规业务授信额度</th><th>目前最新民间投资授信额度</th><th></th></tr></thead><tbody>${fbody || '<tr><td colspan="6">无</td></tr>'}</tbody></table></div></div>
  <details class="panel mb"><summary class="panel-head" style="cursor:pointer"><h2 style="display:inline">参考信息（不参与初步授信额度计算）：科技专项 AD/AE、工行 E/F/G/Y、互联网落地 AG</h2></summary><div class="tbl-wrap"><table class="grid"><thead><tr><th>机构</th><th>科技创新额度（第一次）AD</th><th>科技创新额度（第二次）AE</th><th>2026 工行预计规模 E</th><th>2025 工行实际 F</th><th>2026 预计工行发生额 G</th><th>是否满足工行 Y=X−G</th><th>2025 互联网落地 AG</th></tr></thead><tbody>${refBody}</tbody></table></div></details>
  <div class="panel"><div class="panel-head"><div><h2>授信额度调整记录</h2><p>时间、机构、调整前后、调整量、原因、操作人；追加式不可删改。</p></div><button class="ghost mini" onclick="download('/api/m4/schemes/${s.id}/cur-log.xlsx')">导出 Excel</button></div><div id="m4curlog" class="tbl-wrap"></div></div>
  ${locked ? `<div class="note-box">本方案已${esc(s.status)}，调整已锁定；如需修改请在「方案版本」中复制新版本。</div>` : ''}`;
  m4LoadCurLog(s.id);
}
async function m4LoadCurLog(sid) {
  const log = await api(`/api/m4/schemes/${sid}/cur-log`);
  $('#m4curlog').innerHTML = `<table class="grid"><thead><tr><th>时间</th><th>机构</th><th>调整项</th><th>调整前</th><th>调整后</th><th>调整量</th><th>原因</th><th>操作人</th></tr></thead><tbody>
  ${log.map(x => `<tr><td>${esc(x.time)}</td><td class="l">${esc(x.institution)}</td><td>${esc(x.field)}</td><td class="n">${m4n(x.before)}</td><td class="n">${m4n(x.after)}</td><td class="n ${x.delta < 0 ? 'bad' : 'ok'}">${sgn(x.delta)}</td><td class="l">${esc(x.reason)}</td><td>${esc(x.operator)}</td></tr>`).join('') || '<tr><td colspan="8" class="small">暂无调整</td></tr>'}</tbody></table>`;
}
function m4CompareExcel() {
  const rows = M4.scheme.result.rows.filter(r => r.excel_AC != null && typeof r.excel_AC === 'number');
  const diff = rows.filter(r => Math.abs((r.AC || 0) - r.excel_AC) >= 0.005);
  $('#m4cmp').innerHTML = !rows.length ? '<div class="alert warn mb">当前数据集没有 Excel 台账 AC 列（导入文件无「计算表」），无法对比</div>' :
  `<div class="panel mb"><div class="panel-head"><div><h2>与 Excel AC 列对比：${rows.length - diff.length}/${rows.length} 家一致，${diff.length} 家不同（红色高亮）</h2><p>计算值 = 公式（Z=X、AA=Z）；差异多为台账中第三/四次调整（Z/AA）被手工改值，属历史手工差异。</p></div><a class="edit" onclick="$('#m4cmp').innerHTML=''">关闭</a></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>机构</th><th>第二次X</th><th>计算 AB</th><th>台账 AB</th><th>已备案占比AH</th><th>计算 AC（初步授信额度）</th><th>台账 AC</th><th>差异</th><th>台账 Z / AA 是否手工改</th></tr></thead><tbody>
  ${rows.map(r => { const d = (r.AC || 0) - r.excel_AC, bad = Math.abs(d) >= 0.005; const manual = !r.fixed && ((r.excel_Z != null && Math.abs(r.excel_Z - r.X) > 0.5) || (r.excel_AA != null && r.excel_Z != null && Math.abs(r.excel_AA - r.excel_Z) > 0.5));
    return `<tr style="${bad ? 'background:#fdecec' : ''}"><td class="l">${esc(r.name)}${r.fixed ? ' <span class="pill gold">固定额度</span>' : ''}</td><td class="n">${m4n(r.X)}</td><td class="n">${m4n(r.AB)}</td><td class="n">${m4n(r.excel_AB)}</td><td class="n">${pct(r.AH)}</td><td class="n">${m4n(r.AC)}</td><td class="n">${m4n(r.excel_AC)}</td><td class="n ${bad ? 'bad' : 'ok'}">${bad ? sgn(d) : '一致'}</td><td class="small">${manual ? `Z=${m4n(r.excel_Z)}，AA=${m4n(r.excel_AA)}` : ''}</td></tr>`; }).join('')}</tbody></table></div></div>`;
}
function m4CurAdjust(name) {
  const r = m4Row(name);
  openModal('调整授信额度：' + name, `<p class="small mb">初步授信额度（AC，参考）= <b>${m4n(r.AC)}</b> 万元。调整只作用于「目前最新」额度，不改变 AC。</p>
  <div class="form-row"><label>调整项<select class="in" id="ca_k"><option value="cur_regular">目前最新常规业务授信额度（现 ${m4n(r.cur_regular)}）</option><option value="cur_mintou">目前最新民间投资授信额度（现 ${m4n(r.cur_mintou)}）</option></select></label>
  <label>方向<select class="in" id="ca_d"><option value="1">上调 ＋</option><option value="-1">下调 －</option></select></label>
  <label>调整量（万元）<input class="in" id="ca_v" type="number" min="0" step="any"></label></div>
  <div class="form-row"><label style="flex:1">调整原因（必填）<input class="in" id="ca_r" list="ca_rl" placeholder="如：上会确认 / 补充注册资本 / 备案激励 / 按请示调减"><datalist id="ca_rl"><option>上会确认</option><option>补充注册资本</option><option>备案激励</option><option>按请示调减</option></datalist></label></div>
  <p class="small mb" id="ca_prev"></p><button class="primary" id="ca_ok">确认调整</button>`);
  const upd = () => { const k = $('#ca_k').value, v = Number($('#ca_v').value || 0) * Number($('#ca_d').value); $('#ca_prev').innerHTML = `调整前 ${m4n(r[k])} → 调整后 <b>${m4n(r[k] + v)}</b>（${sgn(v)}）`; $('#ca_ok').disabled = !$('#ca_r').value.trim() || !v; };
  ['#ca_k', '#ca_d', '#ca_v', '#ca_r'].forEach(i => $(i).addEventListener('input', upd)); upd();
  $('#ca_ok').onclick = async () => {
    const reason = $('#ca_r').value.trim(); if (!reason) return toast('请填写调整原因');
    const delta = Number($('#ca_v').value || 0) * Number($('#ca_d').value); if (!delta) return toast('请填写调整量');
    await api(`/api/m4/schemes/${M4.scheme.id}/cur-adjust`, { method: 'POST', json: { institution: name, kind: $('#ca_k').value, delta, reason } });
    closeModal(); toast('已调整并留痕'); route();
  };
}
function m4Row(name) { return M4.scheme.result.rows.find(r => r.name === name); }
function m4Drill(name) {
  const r = m4Row(name), c = M4.scheme.result.param.constants;
  const line = (k, label, fmt, how) => `<tr><td>${k}</td><td>${label}</td><td class="n">${fmt(r[k])}</td><td class="small">${how}</td></tr>`;
  openModal('测算明细：' + name, `<table class="grid"><thead><tr><th>列</th><th>指标</th><th>值</th><th>计算口径</th></tr></thead><tbody>
  ${line('I', '2025年规模', f2, '分表「2025年规模」')}
  ${line('J', '规模系数', f4, '规模 ÷ 10000')}
  ${line('K', '就业贡献指标', f2, '就业人数 ÷ 规模 × 10000（含基期常数）')}
  ${line('L', '就业系数', f4, 'K ÷ 全省均值 ' + f4(c.emp_avg) + '（' + esc(c.emp_avg_ref || '') + '）')}
  ${line('M', '支小支农比例', pct, '分表「支小支农业务统计表」')}
  ${line('N', '支小支农系数', f4, 'M ≥ ' + pct(c.zxzn_threshold) + ' 取 1，否则 M ÷ 阈值')}
  ${line('O', '累计担保代偿率', pct, '分表「近3年累计代偿率」')}
  ${line('P', '累计代偿系数', f4, 'max(1 − (O − 均值' + pct(c.lj_avg) + ') ÷ 均值, ' + c.floor + ')')}
  ${line('Q', '2025年代偿率', pct, '分表「2025年代偿率」')}
  ${line('R', '当年代偿系数', f4, 'max(1 − (Q − 均值' + pct(c.dn_avg) + ') ÷ 均值, ' + c.floor + ')')}
  ${line('S', '机构评价分', f2, '分表「2025年机构评价」')}
  ${line('T', '评价系数', f4, '评价分 ÷ 100')}
  ${line('U', '总系数', f4, 'J × Σ(系数×权重)')}
  ${line('H', '2025年符合民投', f2, '分表「2025年民投」H 列（扣工行/邮储/展期、银行分险≤20%）')}
  ${line('V', '注册资本调整', f2, 'ROUND(增资总额 × 2 ÷ 1000, 0) × 1000（申请表 I 列）')}
  ${line('W', '第一次调整', f2, 'W = I + V − H')}
  ${line('X', '第二次调整', f0, r.fixed ? '固定额度' : 'ROUND(ΣW × U ÷ ΣU, 0)')}
  ${line('Z', '第三次调整', f2, r.fixed ? '固定额度' : 'Z = X')}
  ${line('AA', '第四次调整', f2, r.fixed ? '固定额度' : 'AA = Z')}
  ${line('AB', '第五次调整', f2, r.fixed ? '固定额度' : 'AA 按 1000 取整后落到 1 万档；取整后为 0 给 10000')}
  ${line('AF', '截止备案金额', f2, '计算表 AF 列')}
  ${line('AH', '已备案占比', pct, 'AH = AF ÷ AB')}
  ${line('AC', '初步授信额度', f2, r.fixed ? '固定额度（给定）' : 'AC = AB + IF(AH ≥ 40%, 20000, 0)')}
  ${line('D', '民间投资专项（申请表 F）', f2, '')}
  ${line('AI', '机构总额度', f2, 'AI = AC + D')}
  ${line('cur_regular', '目前最新常规业务授信额度', f2, '申请表 C+D ' + m4n(r.cur_regular_base) + (r.cur_regular_delta ? '，人工增减 ' + sgn(r.cur_regular_delta) : ''))}
  ${line('cur_mintou', '目前最新民间投资授信额度', f2, '申请表 F ' + m4n(r.cur_mintou_base) + (r.cur_mintou_delta ? '，人工增减 ' + sgn(r.cur_mintou_delta) : ''))}
  ${r.excel_AC != null ? `<tr><td>台账</td><td>Excel X / AB / AC / AI</td><td class="n" colspan="2">${f0(r.excel_X)} / ${f0(r.excel_AB)} / ${f0(r.excel_AC)} / ${f0(r.excel_AI)}</td></tr>` : ''}
  </tbody></table>${M4.scheme.status === '草稿' ? `<p class="small" style="margin-top:10px">请示口径（第三次调整 ${sgn(r.third)} / 民投完成率调整 ${sgn(r.mintou_adj)}，用于请示与方案版本）：<a class="edit" onclick="closeModal();m4Adjust('${esc(name)}')">第三次调整</a><a class="edit" onclick="closeModal();m4Mintou('${esc(name)}')">民投完成率调整</a></p>` : ''}`);
}
function m4Adjust(name) {
  const r = m4Row(name);
  openModal('第三次调整（人工）：' + name, `<p class="small mb">第二次调整后 X = <b>${f0(r.X)}</b>；当前第三次调整 ${sgn(r.third)}。填写调整值（正数调增，负数调减，万元），原因为必填，系统记录操作人与时间。</p>
  <div class="form-row"><label>调整值（万元）<input class="in" id="adj_v" type="number" value="${r.third || ''}"></label>
  <label style="flex:1">调整原因（必填）<input class="in" id="adj_r" placeholder="如：结合三季度业务需求增补"></label></div>
  <button class="primary" id="adj_ok">保存调整</button>`);
  $('#adj_ok').onclick = async () => {
    const reason = $('#adj_r').value.trim(); if (!reason) return toast('请填写调整原因');
    await api(`/api/m4/schemes/${M4.scheme.id}/adjust`, { method: 'POST', json: { institution: name, kind: 'third', value: $('#adj_v').value, reason } });
    closeModal(); toast('已保存并重新测算'); route();
  };
}
function m4Mintou(name) {
  const r = m4Row(name), mi = r.mintou_inputs || {}, tiers = M4.scheme.result.param.constants.mintou_tiers || {};
  openModal('民投完成率调整：' + name, `<p class="small mb">规则（取自请示调整系数表）：可调整额度 = 常规授信余额 − 三季度基本额度；民投完成率 ≥ ${tiers.hi}% / ${tiers.lo}%~${tiers.hi}% / &lt;${tiers.lo}% 分档：可调整额度≥0 时分别不调减 / 调减 ${tiers.cut_mid * 100}% / 调减 ${tiers.cut_low * 100}%；&lt;0 时缺口分别增补 ${tiers.add_hi * 100}% / ${tiers.add_mid * 100}% / ${tiers.add_low * 100}%。<br>⚠ 输入数据不在附件2中，需人工填报；也可直接填人工值覆盖（需填原因）。</p>
  <div class="form-row"><label>三季度基本额度（万元）<input class="in" id="mt_q" type="number" value="${mi.q3_base ?? ''}"></label>
  <label>常规业务授信余额（万元）<input class="in" id="mt_b" type="number" value="${mi.balance ?? ''}"></label>
  <label>民投完成率（%）<input class="in" id="mt_r" type="number" value="${mi.rate ?? ''}"></label></div>
  <button class="primary" id="mt_ok">按规则测算</button>
  <hr style="margin:16px 0;border:none;border-top:1px solid var(--line)">
  <div class="form-row"><label>人工覆盖值（万元）<input class="in" id="mt_v" type="number"></label><label style="flex:1">原因（必填）<input class="in" id="mt_rs"></label></div>
  <button class="secondary" id="mt_ov">保存人工值</button> <button class="ghost" id="mt_clr">清除人工值（恢复规则）</button>`);
  $('#mt_ok').onclick = async () => { await api(`/api/m4/schemes/${M4.scheme.id}/mintou`, { method: 'POST', json: { institution: name, q3_base: $('#mt_q').value, balance: $('#mt_b').value, rate: $('#mt_r').value } }); closeModal(); toast('已测算'); route(); };
  $('#mt_ov').onclick = async () => { const reason = $('#mt_rs').value.trim(); if (!reason) return toast('请填写原因'); await api(`/api/m4/schemes/${M4.scheme.id}/adjust`, { method: 'POST', json: { institution: name, kind: 'mintou', value: $('#mt_v').value, reason } }); closeModal(); route(); };
  $('#mt_clr').onclick = async () => { const reason = $('#mt_rs').value.trim() || '恢复按规则测算'; await api(`/api/m4/schemes/${M4.scheme.id}/adjust`, { method: 'POST', json: { institution: name, kind: 'mintou', value: '', reason } }); closeModal(); route(); };
}

const M4_POL = { null_and_alert: '告警且记空（不算 U/X）', zero: '缺省按 0', skip: '跳过，不告警' };
async function m4Spec(el, s) {
  const spec = await api('/api/m4/formula-spec');
  const res = s.result || {}, meta = res.meta || {};
  const miss = (res.alerts || []).filter(a => a.type === '数据缺失');
  const hash = meta.calc_module_hash || '';
  const drift = hash && spec.calc_module_hash && hash !== spec.calc_module_hash;
  el.innerHTML = `<div class="note-box mb">${esc(spec.missing_coefficient_rule || '')}</div>
  ${drift ? '<div class="alert warn mb">结果中的 calc.py 哈希与当前代码不一致，请重新测算后再以结果打戳为准。</div>' : ''}
  <div class="kv mb"><div><span>公式口径版本</span><b>${esc(meta.formula_spec_version || '尚未打戳')}</b></div>
   <div><span>参数版本</span><b>v${esc(meta.param_version != null ? meta.param_version : (res.param || {}).version)}</b></div>
   <div><span>数据集</span><b>#${esc(meta.dataset_id != null ? meta.dataset_id : s.dataset_id)}</b></div>
   <div><span>calc.py</span><b style="font-size:13px" title="${esc(hash)}">${esc(hash ? hash.slice(0, 12) : '—')}</b></div></div>
  <div class="page-actions mb" style="margin-top:0"><button class="secondary" onclick="download('/api/m4/schemes/${s.id}/formula-spec.xlsx')">导出口径说明</button>
   <span class="small">测算表 Excel 中同样有「口径说明」工作表。当前公式文件版本 ${esc(spec.version)}。</span></div>
  <div class="panel mb"><div class="panel-head"><div><h2>本次系数缺失告警</h2><p>参与分配的机构缺系数时：告警，且不算总系数 U、不算第二次调整 X。固定额度机构不参与系数测算。</p></div></div>
   ${miss.length ? alertsHtml(miss) : '<div class="panel-b small">当前方案没有「数据缺失」告警。</div>'}</div>
  <div class="panel"><div class="panel-head"><div><h2>列级口径</h2><p>${esc(spec.scope || '')} ${esc(spec.weight_rule || '')}</p></div></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>列</th><th>指标</th><th>白话公式</th><th>缺失时</th><th>来源</th></tr></thead><tbody>
  ${(spec.columns || []).map(c => `<tr><td>${esc(c.id)}</td><td>${esc(c.name || '')}</td><td class="l small">${esc(c.expr_human)}</td><td class="small">${esc(M4_POL[c.missing_policy] || c.missing_policy)}</td><td class="l small">${esc(c.source)}</td></tr>`).join('')}
  </tbody></table></div></div>`;
}

/* ---- 数据导入与基础数据 ---- */
async function m4Data(el, s) {
  const ds = await api('/api/m4/datasets' + recQ('m4_dataset'));
  const d = s ? await api('/api/m4/datasets/' + s.dataset_id) : null;
  const F = [['scale', '2025年规模'], ['emp', '就业人数'], ['zxzn_raw', '支小支农占比'], ['lj_raw', '累计代偿率'], ['dn_raw', '2025代偿率'], ['pj', '评价分'], ['zc_total', '注册资本(合计)'], ['mintou_prev', '2025民投'], ['mintou_special', '民间专项额度'], ['tech_quota', '科技创新额度']];
  el.innerHTML = `<div class="grid2 mb">
   <div class="panel panel-b"><h2 class="mb">导入附件2（.xlsx，9 张分表）</h2>
     <p class="small mb">按工作表名关键词定位：申请表、2025年民投、2025年规模、就业人数、支小支农、近3年累计代偿率、2025年代偿率、2025年机构评价（以上 8 张为核心表，缺一不可）、2025年互联网落地（参考）。以「2025年规模」C 列为基准名单按机构名匹配，未匹配行忽略并在下方提示；百分比统一 ÷100 转小数。含「计算表」时同时读取台账现值（AC、固定额度、截止备案金额 AF、工行列）用于对比。</p>
     <div class="drop mb"><b>选择 .xlsx 文件</b><br><input type="file" accept=".xlsx" onchange="m4Upload(this)"></div>
     <label class="small"><input type="checkbox" id="m4prefill" checked> 同时生成「附件2口径方案」（复现原表第三~六次调整）</label><br><br>
     <button class="secondary" onclick="m4ImportSample()">导入内置样例（附件2：2026年各合作担保机构授信额度计算表）</button></div>
   <div class="panel panel-b"><div class="panel-head" style="padding:0 0 8px;border:0;flex-wrap:wrap;gap:6px"><h2>数据集版本</h2>${recTabs('m4_dataset')}</div><div class="tbl-wrap" style="max-height:240px"><table class="grid"><thead><tr><th></th><th>#</th><th>名称</th><th>导入时间</th><th>导入人</th><th>口径已核备</th><th></th></tr></thead>
   <tbody>${ds.map(x => `<tr><td>${recCb('m4_dataset', x)}</td><td>${x.id}</td><td class="l">${esc(x.name)}</td><td>${esc(x.imported_at)}</td><td>${esc(x.imported_by)}</td><td><label><input type="checkbox" ${x.verified ? 'checked' : ''} onchange="m4Verify(${x.id},this.checked)"> ${x.verified ? '已核备' : '未核备'}</label></td><td>${recBtns('m4_dataset', x)} ${recBadge(x)}</td></tr>`).join('') || '<tr><td colspan="7" class="small">无记录</td></tr>'}</tbody></table></div>
   <p class="small">「口径未核备」为人工标记：请与国担系统核对后勾选。</p></div></div>
   ${d ? `<div class="small mb">数据来源：${esc(d.source_file)}（${d.payload.mode === 'direct' ? '按 PRD 列映射，无计算表' : '计算表公式 + 分表'}）；分表定位：${Object.entries(d.payload.sheet_map || {}).map(([k, v]) => esc(k) + '→' + (v ? esc(v) : '<b style="color:var(--red)">缺</b>')).join('，')}</div>` + alertsHtml(d.payload.alerts) + `<div class="panel"><div class="panel-head"><div><h2>基础数据（数据集 #${d.id}）</h2><p>点「修改」逐一表单填报，将生成新数据集版本并基于其复制当前方案；原数据保留可追溯。</p></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>序号</th><th>机构</th>${F.map(f => `<th>${f[1]}</th>`).join('')}<th></th></tr></thead><tbody>
   ${d.payload.rows.map(r => `<tr class="${r.fixed ? 'fixed' : ''}"><td>${r.seq ?? ''}</td><td class="l">${esc(r.name)}</td>${F.map(([k]) => `<td class="n" title="${esc((r.sources || {})[k] || '')}">${['zxzn_raw', 'lj_raw', 'dn_raw'].includes(k) ? (r[k] == null ? '—' : f2(r[k]) + '%') : f2(r[k])}</td>`).join('')}<td><a class="edit" onclick="m4EditRow(${d.id},'${esc(r.name)}')">修改</a></td></tr>`).join('')}
   </tbody></table></div><div class="panel-b"><a class="edit" onclick="m4EditRow(${d.id},'')">＋ 表单新增机构</a></div></div>` : ''}`;
  M4.dataset = d; M4.F = F;
}
async function m4Verify(id, v) { await api(`/api/m4/datasets/${id}/verify`, { method: 'POST', json: { verified: v } }); toast(v ? '已标记核备' : '已取消核备'); }
function m4EditRow(did, name) {
  const r = name ? M4.dataset.payload.rows.find(x => x.name === name) : {};
  openModal(name ? '修改基础数据：' + name : '表单新增机构', `${name ? '' : '<div class="form-row"><label style="flex:1">机构全称<input class="in" id="er_name"></label></div>'}
  <div class="form-row">${M4.F.map(([k, l]) => `<label>${l}${['zxzn_raw', 'lj_raw', 'dn_raw'].includes(k) ? '（%，如 98.71）' : ''}<input class="in" data-k="${k}" type="number" step="any" value="${r[k] ?? ''}"></label>`).join('')}</div>
  <div class="form-row"><label style="flex:1">修改原因（必填）<input class="in" id="er_reason"></label></div><button class="primary" id="er_ok">保存并生成新版本</button>`);
  $('#er_ok').onclick = async () => {
    const reason = $('#er_reason').value.trim(); if (!reason) return toast('请填写原因');
    const fields = {}; $$('#modalB input[data-k]').forEach(i => { const old = r[i.dataset.k]; const nv = i.value === '' ? null : Number(i.value); if (nv !== (old ?? null)) fields[i.dataset.k] = nv; });
    const nm = name || $('#er_name').value.trim(); if (!nm) return toast('请填写机构全称');
    const out = await api(`/api/m4/datasets/${did}/rows`, { method: 'POST', json: { name: nm, fields, reason, scheme_id: M4.scheme && M4.scheme.id } });
    if (out.scheme_id) await api(`/api/m4/schemes/${out.scheme_id}/current`, { method: 'POST' });
    closeModal(); toast('已生成新数据集与方案'); route();
  };
}

/* ---- 参数配置 ---- */
async function m4Params(el, s) {
  const ps = await api('/api/m4/params'); const p = s.result.param; const c = p.constants;
  const W = [['L', '就业贡献'], ['N', '支小支农'], ['P', '累计代偿'], ['R', '当年代偿'], ['T', '机构评价']];
  const bcs = c.base_consts || {};
  el.innerHTML = `<div class="grid2"><div class="panel panel-b"><h2 class="mb">权重（当前方案使用参数 v${p.version}）</h2>
  <div class="form-row"><label>规模权重(J)<input class="in" value="1" readonly disabled title="规模 J 为外置乘数，权重固定为 1，不参与权重和"></label>
  ${W.map(([k, l]) => `<label>${l}权重(w${k})<input class="in m4w" data-k="${k}" type="number" step="0.01" value="${p.weights[k]}" oninput="m4WSum();m4Preview()"></label>`).join('')}</div>
  <p id="m4wsum" class="small mb"></p>
  <h2 class="mb" style="margin-top:12px">常量（默认取自分表，口径变更时调整）</h2>
  <div class="form-row"><label>就业全省平均户均（${esc(c.emp_avg_ref || '就业人数!F3')}）<input class="in m4c" id="c_emp" data-k="emp_avg" type="number" step="any" value="${c.emp_avg}" oninput="m4Preview()"></label>
  <label>近3年累计代偿全省均值（${esc(c.lj_avg_ref || '')}）<input class="in m4c" id="c_lj" data-k="lj_avg" type="number" step="any" value="${c.lj_avg}" oninput="m4Preview()"></label>
  <label>2025年代偿全省均值（${esc(c.dn_avg_ref || '')}）<input class="in m4c" id="c_dn" data-k="dn_avg" type="number" step="any" value="${c.dn_avg}" oninput="m4Preview()"></label>
  <label>支小支农阈值<input class="in m4c" id="c_zx" data-k="zxzn_threshold" type="number" step="any" value="${c.zxzn_threshold}" oninput="m4Preview()"></label></div>
  <p class="small">规模基期常数（K = 就业人数 ÷ (I + 基期常数) × 10000）：附件2 中仅下列机构的 K 列含此项（${esc(c.base_const_ref || '')}）</p>
  <div class="form-row">${Object.entries(bcs).map(([n, v]) => `<label>${esc(n)}<input class="in m4bc" data-n="${esc(n)}" type="number" step="any" value="${v}" oninput="m4Preview()"></label>`).join('') || '<span class="small">无</span>'}</div>
  <div class="form-row"><label style="flex:1">调整说明<input class="in" id="c_note" placeholder="如：提高机构评价权重"></label></div>
  <button class="primary" onclick="m4SaveParams(${p.id})">保存为新参数版本并重新测算（生成新方案）</button></div>
  <div class="panel panel-b"><h2 class="mb">即时重算预览（未保存）</h2><div id="m4prev" class="tbl-wrap" style="max-height:520px"></div></div></div>
  <div class="panel panel-b" style="margin-top:16px"><h2 class="mb">参数版本</h2><table class="grid"><thead><tr><th>版本</th><th>说明</th><th>权重</th><th>创建</th></tr></thead><tbody>
  ${ps.map(x => `<tr><td>v${x.version}</td><td class="l" title="${esc(x.note)}">${esc(x.label)}</td><td class="small">${Object.entries(x.weights).map(([k, w]) => k + ':' + w).join(' ')}</td><td class="small">${esc(x.created_by)} ${esc(x.created_at)}</td></tr>`).join('')}</tbody></table></div>`;
  m4WSum(); m4Preview();
}
function m4Inputs() {
  const weights = {}; $$('.m4w').forEach(i => weights[i.dataset.k] = Number(i.value || 0));
  const constants = {}; $$('.m4c').forEach(i => { if (i.value !== '') constants[i.dataset.k] = Number(i.value); });
  const bc = {}; $$('.m4bc').forEach(i => { if (i.value !== '') bc[i.dataset.n] = Number(i.value); });
  return { weights, constants, base_consts: bc };
}
function m4WSum() {
  const s = $$('.m4w').reduce((a, i) => a + Number(i.value || 0), 0); const exact = Math.abs(s - 1) < 1e-9, ok = Math.abs(s - 1) <= 0.02 + 1e-12;
  $$('.m4w').forEach(i => i.style.outline = ok ? '' : '2px solid var(--red)');
  $('#m4wsum').innerHTML = `5 项权重合计：<b style="color:${exact ? 'var(--green)' : ok ? 'var(--gold)' : 'var(--red)'}">${s.toFixed(4)}</b> ${exact ? '✓' : ok ? '（在 1±0.02 容差内，按原值计算）' : `<span style="background:#fdecec;color:var(--red);padding:2px 6px;border-radius:4px">⚠ 应调整为合计=1；当前按比例归一后计算（${$$('.m4w').map(i => 'w' + i.dataset.k + '=' + (s ? (Number(i.value || 0) / s).toFixed(4) : '0')).join(' / ')}）</span>`}`;
  return ok;
}
let m4PrevT = null;
function m4Preview() {
  clearTimeout(m4PrevT);
  m4PrevT = setTimeout(async () => {
    const inp = m4Inputs(); const body = { weights: inp.weights, constants: inp.constants };
    const r = await api(`/api/m4/schemes/${M4.scheme.id}/preview`, { method: 'POST', json: { ...body, base_consts: inp.base_consts } });
    const cur = Object.fromEntries(M4.scheme.result.rows.map(x => [x.name, x]));
    $('#m4prev').innerHTML = `<table class="grid"><thead><tr><th>机构</th><th>总系数U</th><th>第二次X</th><th>初步授信额度AC</th><th>较当前方案</th></tr></thead><tbody>
    ${r.rows.filter(x => !x.fixed).map(x => { const d = (x.AC || 0) - ((cur[x.name] || {}).AC || 0); return `<tr><td class="l">${esc(x.name)}</td><td class="n">${f4(x.U)}</td><td class="n">${m4n(x.X)}</td><td class="n">${m4n(x.AC)}</td><td class="n ${d ? (d < 0 ? 'bad' : 'ok') : ''}">${d ? sgn(d) : '—'}</td></tr>`; }).join('')}
    <tr class="tot"><td>合计</td><td class="n">${f4(r.totals.sumU)}</td><td class="n">${m4n(r.totals.sumX)}</td><td class="n">${m4n(r.totals.sumAC)}</td><td></td></tr></tbody></table>`;
  }, 150);
}
async function m4SaveParams(base) {
  if (!m4WSum()) return toast('权重合计应调整为 1（容差 ±0.02）后再保存');
  const inp = m4Inputs();
  const out = await api('/api/m4/params', { method: 'POST', json: { base_id: base, weights: inp.weights, constants: { ...inp.constants, base_consts: inp.base_consts }, note: $('#c_note').value, scheme_id: M4.scheme.id } });
  await api(`/api/m4/schemes/${out.scheme_id}/current`, { method: 'POST' }); toast('已生成新参数版本与方案'); nav('m4', 'result');
}

/* ---- 方案版本 ---- */
async function m4Versions(el, s) {
  const list = await api('/api/m4/schemes' + recQ('m4_scheme'));
  el.innerHTML = `<div class="panel"><div class="panel-head"><div><h2>方案版本</h2><p>每次调整均可另存版本；草稿 → 已上会 → 已批复，已上会/已批复后锁定调整。回滚 = 以旧版本内容新建一个当前草稿。当前生效版本不能删除。</p>${recTabs('m4_scheme')}</div>
  <div class="form-row" style="margin:0">对比：<select class="in" id="cmpA">${list.map(x => `<option value="${x.id}">v${x.version}</option>`).join('')}</select> vs <select class="in" id="cmpB">${list.map((x, i) => `<option value="${x.id}" ${i === 1 ? 'selected' : ''}>v${x.version}</option>`).join('')}</select><button class="secondary mini" onclick="m4Compare()">对比</button></div></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>版本</th><th>名称</th><th>状态</th><th>当前</th><th>常规授信合计</th><th>最终授信合计</th><th>创建</th><th>说明</th><th>操作</th></tr></thead><tbody>
  ${list.map(x => `<tr><td>${recCb('m4_scheme', x)}</td><td>v${x.version}</td><td class="l">${esc(x.name)}</td><td>${STATUS_PILL(x.status)}</td><td>${x.is_current ? '<span class="pill red">当前</span>' : ''}</td><td class="n">${f0(x.totals && x.totals.sumRegular)}</td><td class="n">${f0(x.totals && x.totals.sumFinal)}</td><td class="small">${esc(x.created_by)} ${esc(x.created_at)}</td><td class="l small" title="${esc(x.note)}">${esc(x.note)}</td>
  <td>${x.is_current ? '' : `<a class="edit" onclick="m4Act(${x.id},'current')">设为当前</a>`}<a class="edit" onclick="m4Act(${x.id},'copy')">复制</a><a class="edit" onclick="m4Act(${x.id},'rollback')">回滚到此</a>
  ${x.status === '草稿' ? `<a class="edit" onclick="m4Status(${x.id},'已上会')">标记已上会</a>` : ''}${x.status === '已上会' ? `<a class="edit" onclick="m4Status(${x.id},'已批复')">标记已批复</a><a class="edit" onclick="m4Status(${x.id},'草稿')">退回草稿</a>` : ''}${recBtns('m4_scheme', x)} ${recBadge(x)}</td></tr>
  ${(x.status_log || []).length ? `<tr><td></td><td></td><td colspan="8" class="small">状态记录：${x.status_log.map(l => `${esc(l.at)} ${esc(l.by)} → ${esc(l.to)} ${esc(l.remark || '')}`).join('；')}</td></tr>` : ''}`).join('')}
  </tbody></table></div></div><div id="cmpOut" class="mb"></div>`;
}
async function m4Act(id, act) {
  if (act === 'current') await api(`/api/m4/schemes/${id}/current`, { method: 'POST' });
  if (act === 'copy') { const name = prompt('新方案名称', '复制方案'); if (name === null) return; const o = await api(`/api/m4/schemes/${id}/copy`, { method: 'POST', json: { name } }); await api(`/api/m4/schemes/${o.scheme_id}/current`, { method: 'POST' }); }
  if (act === 'rollback') { if (!confirm('以该版本内容新建一个当前草稿？')) return; await api(`/api/m4/schemes/${id}/rollback`, { method: 'POST' }); }
  toast('完成'); route();
}
async function m4Status(id, st) { const remark = prompt(`标记为「${st}」，备注（如会议名称/批复文号）：`, ''); if (remark === null) return; await api(`/api/m4/schemes/${id}/status`, { method: 'POST', json: { status: st, remark } }); toast('状态已更新'); route(); }
async function m4Compare() {
  const c = await api(`/api/m4/compare?a=${$('#cmpA').value}&b=${$('#cmpB').value}`);
  const ch = c.rows.filter(r => r.changed);
  $('#cmpOut').innerHTML = `<div class="panel" style="margin-top:16px"><div class="panel-head"><div><h2>v${c.a.version} → v${c.b.version} 差异（${ch.length} 家变化）</h2></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>机构</th><th>X(a)</th><th>X(b)</th><th>第三次调整 a/b</th><th>民投调整 a/b</th><th>常规授信 a</th><th>常规授信 b</th><th>差额</th><th>最终授信 a</th><th>最终授信 b</th><th>差额</th></tr></thead><tbody>
  ${ch.map(r => `<tr><td class="l">${esc(r.name)}</td><td class="n">${f0(r.a && r.a.X)}</td><td class="n">${f0(r.b && r.b.X)}</td><td class="n">${sgn(r.a && r.a.third)} / ${sgn(r.b && r.b.third)}</td><td class="n">${sgn(r.a && r.a.mintou_adj)} / ${sgn(r.b && r.b.mintou_adj)}</td><td class="n">${f0(r.a && r.a.regular_final)}</td><td class="n">${f0(r.b && r.b.regular_final)}</td><td class="n ${r.diff.regular_final < 0 ? 'bad' : 'ok'}">${sgn(r.diff.regular_final)}</td><td class="n">${f0(r.a && r.a.final)}</td><td class="n">${f0(r.b && r.b.final)}</td><td class="n">${sgn(r.diff.final)}</td></tr>`).join('') || '<tr><td colspan="11">无差异</td></tr>'}</tbody></table></div></div>`;
}

/* ---- 请示生成 ---- */
async function m4Qingshi(el, s) {
  const list = await api('/api/m4/schemes');
  const base = M4.qsBase || '';
  const q = await api(`/api/m4/schemes/${s.id}/qingshi${base ? '?base=' + base : ''}`);
  M4.qs = q;
  el.innerHTML = `<div class="panel panel-b mb"><div class="form-row"><label>对比基准方案（调整前）<select class="in" id="qsBase" onchange="M4.qsBase=this.value;route()"><option value="">（无：以第三次调整+民投调整为调整额）</option>${list.filter(x => x.id !== s.id).map(x => `<option value="${x.id}" ${String(x.id) === String(base) ? 'selected' : ''}>v${x.version} ${esc(x.name)}</option>`).join('')}</select></label>
  <button class="primary" onclick="m4QsDownload()">生成并下载请示 Word</button></div>
  <p class="small">基于请示模板生成；下方段落可直接编辑，「综上…」段已按方案自动生成（涉及 ${q.decrease.length + q.increase.length} 家：调减 ${q.decrease.length} 家，调增 ${q.increase.length} 家），附件1 表格按方案差额自动重建。日期、调研数字等请人工核对后修改。</p></div>
  <div class="grid2"><div class="panel panel-b"><h2 class="mb">正文（可编辑）</h2>${q.paragraphs.map((p, i) => `<textarea class="in qsp" data-i="${i}" style="min-height:${p.length > 80 ? 80 : 36}px;margin-bottom:6px;${i === q.summary_index ? 'border-color:var(--gold)' : ''}">${esc(p)}</textarea>`).join('')}</div>
  <div class="panel panel-b"><h2 class="mb">附件1 预览：额度调整</h2><table class="grid"><thead><tr><th>类型</th><th>机构</th><th>调整额（万元）</th></tr></thead><tbody>
  ${q.decrease.map(r => `<tr><td>调减</td><td class="l">${esc(r.name)}</td><td class="n bad">-${f2(r.value)}</td></tr>`).join('')}${q.increase.map(r => `<tr><td>调增</td><td class="l">${esc(r.name)}</td><td class="n ok">+${f2(r.value)}</td></tr>`).join('')}</tbody></table></div></div>`;
}
async function m4QsDownload() { const paragraphs = $$('.qsp').map(t => t.value); await download(`/api/m4/schemes/${M4.scheme.id}/qingshi.docx`, { method: 'POST', json: { paragraphs, base: M4.qsBase ? Number(M4.qsBase) : null } }); toast('已生成'); }

/* ---- 调整留痕 ---- */
async function m4History(el, s) {
  const h = s.history || [];
  el.innerHTML = `<div class="panel"><div class="panel-head"><div><h2>当前方案 v${s.version} 人工调整记录（追加式，不可删改）</h2></div></div><div class="tbl-wrap"><table class="grid"><thead><tr><th>时间</th><th>操作人</th><th>角色</th><th>机构</th><th>类型</th><th>调整值</th><th>原因</th></tr></thead><tbody>
  ${h.map(x => `<tr><td>${esc(x.created_at)}</td><td>${esc(x.operator)}</td><td>${esc(x.role)}</td><td class="l">${esc(x.institution)}</td><td>${M4_KIND[x.kind] || x.kind}</td><td class="n">${x.value === null ? '清除' : sgn(x.value)}</td><td class="l" title="${esc(x.reason)}">${esc(x.reason)}</td></tr>`).join('') || '<tr><td colspan="7">暂无</td></tr>'}</tbody></table></div></div>`;
}
