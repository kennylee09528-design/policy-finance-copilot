/* 系统管理：管理员登录 + 大模型供应商/模型配置；业务页面模型选择 */
const ADM = {};
const ADM_TABS = [['llm', '大模型配置'], ['search', '联网搜索'], ['m1', 'M1 采集规则与查询模板'], ['m2', 'M2 简报规则'], ['m3', 'M3 写作 Agent'], ['ppt', 'PPT Agent'], ['users', '用户与权限'], ['mail', '邮件发送'], ['feishu', '飞书机器人'], ['wechat', '微信普惠Bot'], ['calls', '大模型调用记录'], ['demo', '演示数据与上线就绪'], ['ops', '运行状态']];
PAGES.admin = async (v, sub) => {
  const me = await api('/api/admin/me');
  if (!me.logged_in) return admLogin(v);
  if (me.must_change) return admChangePw(v, true);
  sub = sub || 'llm';
  const head = `<div class="page-head"><div><h1>系统管理</h1><p>大模型、联网搜索供应商、M1 采集规则、M2 简报规则与 M3 写作 Agent 均在此可视化配置。所有 API Key 加密存储于服务端，页面只显示掩码，永不回传浏览器。</p></div>
  <div class="page-actions"><span class="small">管理员：${esc(me.username)}</span><button class="ghost" onclick="admChangePw($('#view'),false)">修改密码</button><button class="ghost" onclick="admLogout()">退出登录</button></div></div>` + subtabs(ADM_TABS, sub, 'admin');
  if (sub === 'search') return admSearch(v, head);
  if (sub === 'm1') return admM1(v, head);
  if (sub === 'm2') return admM2(v, head);
  if (sub === 'm3') return admM3(v, head);
  if (sub === 'ppt') return admPPT(v, head);
  if (sub === 'demo') return admDemo(v, head);
  if (sub === 'users') return admUsers(v, head);
  if (sub === 'calls') return admCalls(v, head);
  if (sub === 'ops') return admOps(v, head);
  if (sub === 'mail') return admMail(v, head);
  if (sub === 'feishu') return admFeishu(v, head);
  if (sub === 'wechat') return admWechat(v, head);
  const [pv, pr] = await Promise.all([api('/api/admin/llm/presets'), api('/api/admin/llm/providers')]);
  ADM.presets = pv.presets; ADM.providers = pr;
  v.innerHTML = head + `<p class="small mb">统一 OpenAI 兼容适配器，内置国内主流厂商预设与「公司私有模型」（自有算力云，经 API 调用）。</p>
  <div class="note-box mb">敏感模块（M4 机构授信、M5 额度使用数据，需求第 10 章）只允许调用勾选了「允许处理敏感数据」的模型；建议仅对「公司私有模型」（自有算力云，经 API 调用）开启。</div>
  <div class="panel panel-b mb"><h2 class="mb">新增供应商</h2><div class="quick-grid" style="grid-template-columns:repeat(5,1fr);padding:0">
  ${pv.presets.map(p => `<button onclick="admProvForm(null,'${p.vendor}')"><b>${p.is_private ? '🔒' : '＋'}</b><span>${esc(p.name)}</span></button>`).join('')}</div></div>
  ${pr.map(p => `<div class="panel mb"><div class="panel-head"><div><h2>${esc(p.name)} ${p.is_private ? '<span class="pill red">公司私有</span>' : ''} ${p.enabled ? '<span class="pill green">已启用</span>' : '<span class="pill gray">已停用</span>'}</h2>
  <p>${esc(p.vendor_name)} · ${esc(p.base_url)} · API Key：${p.has_key ? esc(p.api_key_masked) : '<b style="color:var(--red)">未设置</b>'}</p></div>
  <div><button class="secondary mini" onclick="admProvForm(${p.id})">编辑</button> <button class="secondary mini" onclick="admModelForm(null,${p.id})">＋ 添加模型</button> <button class="ghost mini" onclick="admDelProv(${p.id})">删除</button></div></div>
  <table class="grid"><thead><tr><th>显示名称</th><th>模型 ID</th><th>默认参数</th><th>启用</th><th>允许处理敏感数据</th><th>最近测试</th><th></th></tr></thead><tbody>
  ${p.models.map(m => `<tr><td>${esc(m.display_name)}</td><td>${esc(m.model_id)}</td><td class="small">${esc(Object.entries(m.params).map(([k, x]) => k + '=' + x).join(' ') || '—')}</td><td>${m.enabled ? '是' : '否'}</td><td>${m.allow_sensitive ? '<span class="pill red">允许（M4/M5）</span>' : '<span class="pill gray">否</span>'}</td>
  <td class="small">${m.last_test ? (m.last_test.ok ? `<span class="pill green">正常 ${m.last_test.ms}ms</span>` : `<span class="pill red" title="${esc(m.last_test.error)}">失败</span> ${esc((m.last_test.error || '').slice(0, 40))}`) + ' ' + esc(m.last_test.at) : '未测试'}</td>
  <td><a class="edit" onclick="admTest(${m.id},this)">测试连接</a><a class="edit" onclick="admModelForm(${m.id},${p.id})">编辑</a><a class="edit" onclick="admDelModel(${m.id})">删除</a></td></tr>`).join('') || '<tr><td colspan="7" class="small">尚未添加模型</td></tr>'}</tbody></table></div>`).join('') || '<div class="empty">尚未配置任何供应商，请从上方选择预设添加。</div>'}`;
};
function admLogin(v) {
  v.innerHTML = `<div class="panel panel-b" style="max-width:420px;margin:40px auto"><h2 class="mb">管理员登录</h2>
  <p class="small mb">首次部署的初始密码见服务器文件 <code>data/admin_initial_password.txt</code>（仅服务器管理员可读）；忘记密码可在服务器执行 <code>python -m app.cli reset-admin</code>。</p>
  <div class="form-row"><label style="flex:1">用户名<input class="in" id="lg_u" value="admin" autocomplete="username"></label></div>
  <div class="form-row"><label style="flex:1">密码<input class="in" id="lg_p" type="password" autocomplete="current-password"></label></div>
  <button class="primary" id="lg_ok">登录</button></div>`;
  const go = async () => { const r = await api('/api/admin/login', { method: 'POST', json: { username: $('#lg_u').value, password: $('#lg_p').value } }); toast(r.must_change ? '首次登录，请修改密码' : '登录成功'); route(); };
  $('#lg_ok').onclick = go; $('#lg_u').onkeydown = $('#lg_p').onkeydown = e => { if (e.key === 'Enter' && !e.isComposing) go(); };
}
function admChangePw(v, forced) {
  v.innerHTML = `<div class="panel panel-b" style="max-width:460px;margin:40px auto"><h2 class="mb">${forced ? '首次登录：请修改初始密码' : '修改密码'}</h2>
  <div class="form-row"><label style="flex:1">原密码<input class="in" id="cp_o" type="password" autocomplete="current-password"></label></div>
  <div class="form-row"><label style="flex:1">新密码（至少 10 位，含字母与数字/符号）<input class="in" id="cp_n" type="password" autocomplete="new-password"></label></div>
  <div class="form-row"><label style="flex:1">确认新密码<input class="in" id="cp_n2" type="password" autocomplete="new-password"></label></div>
  <button class="primary" id="cp_ok">确认修改</button> ${forced ? '<button class="ghost" onclick="admLogout()">退出</button>' : `<button class="ghost" onclick="route()">取消</button>`}</div>`;
  $('#cp_ok').onclick = async () => { if ($('#cp_n').value !== $('#cp_n2').value) return toast('两次输入不一致'); await api('/api/admin/password', { method: 'POST', json: { old: $('#cp_o').value, new: $('#cp_n').value } }); toast('密码已修改'); route(); };
}
async function admLogout() { await api('/api/admin/logout', { method: 'POST' }); if (await initIdentity()) route(); }
function admProvForm(pid, vendor) {
  const p = pid ? ADM.providers.find(x => x.id === pid) : null;
  const pre = ADM.presets.find(x => x.vendor === (p ? p.vendor : vendor));
  openModal(p ? '编辑供应商：' + p.name : '新增供应商：' + pre.name, `${pre.vendor === 'minimax_token_plan' ? '<div class="alert warn mb">⚠ MiniMax 包月 Token Plan 官方定位为个人开发者交互式使用，生产环境建议按量付费 Key；受 5 小时/周额度窗口与限流约束。<b>不建议作为工作台服务端默认模型</b>，仅供个人试用。</div>' : ''}<p class="small mb">${esc(pre.hint || '')}</p>
  <div class="form-row"><label style="flex:1">名称<input class="in" id="pf_name" value="${esc(p ? p.name : pre.name)}"></label></div>
  <div class="form-row"><label style="flex:1">Base URL（OpenAI 兼容，至 /v1 一级）<input class="in" id="pf_url" value="${esc(p ? p.base_url : pre.base_url)}" placeholder="https://your-gateway.example.com/v1"></label></div>
  <div class="form-row"><label style="flex:1">API Key ${p && p.has_key ? '（已设置：' + esc(p.api_key_masked) + '；留空表示不修改）' : ''}<input class="in" id="pf_key" type="password" autocomplete="off" placeholder="${p && p.has_key ? '留空不修改' : '粘贴 API Key'}"></label></div>
  <div class="form-row"><label><span><input type="checkbox" id="pf_en" ${!p || p.enabled ? 'checked' : ''}> 启用</span></label>
  <label><span><input type="checkbox" id="pf_priv" ${(p ? p.is_private : pre.is_private) ? 'checked' : ''}> 公司私有部署</span></label>
  ${p && p.has_key ? '<label><span><input type="checkbox" id="pf_clr"> 清除已保存的 Key</span></label>' : ''}</div>
  ${!p ? `<div class="form-row"><label style="flex:1">同时添加模型（逗号分隔，可留空稍后添加）<input class="in" id="pf_models" value="${esc((pre.models || []).join(','))}"></label></div>
  <label class="small"><input type="checkbox" id="pf_sens" ${pre.allow_sensitive ? 'checked' : ''}> 这些模型允许处理敏感模块（M4/M5）数据</label><br><br>` : ''}
  <button class="primary" id="pf_ok">保存</button>`);
  $('#pf_ok').onclick = async () => {
    const body = { vendor: pre.vendor, name: $('#pf_name').value, base_url: $('#pf_url').value, api_key: $('#pf_key').value || null, enabled: $('#pf_en').checked, is_private: $('#pf_priv').checked };
    if (p) { if ($('#pf_clr') && $('#pf_clr').checked) body.clear_key = true; await api('/api/admin/llm/providers/' + p.id, { method: 'PUT', json: body }); }
    else { body.models = $('#pf_models').value.split(/[,，]/).map(s => s.trim()).filter(Boolean); body.allow_sensitive = $('#pf_sens').checked; await api('/api/admin/llm/providers', { method: 'POST', json: body }); }
    closeModal(); toast('已保存'); route();
  };
}
function admModelForm(mid, pid) {
  const p = ADM.providers.find(x => x.id === pid); const m = mid ? p.models.find(x => x.id === mid) : null; const pa = m ? m.params : {};
  openModal((m ? '编辑模型' : '添加模型') + ' · ' + p.name, `<div class="form-row"><label>模型 ID<input class="in" id="mf_id" value="${esc(m ? m.model_id : '')}"></label><label>显示名称<input class="in" id="mf_dn" value="${esc(m ? m.display_name : '')}"></label></div>
  <div class="form-row"><label>temperature<input class="in" id="mf_t" type="number" step="0.1" value="${pa.temperature ?? ''}"></label><label>top_p<input class="in" id="mf_tp" type="number" step="0.05" value="${pa.top_p ?? ''}"></label><label>max_tokens<input class="in" id="mf_mt" type="number" value="${pa.max_tokens ?? ''}"></label></div>
  <div class="form-row"><label><span><input type="checkbox" id="mf_en" ${!m || m.enabled ? 'checked' : ''}> 启用</span></label><label><span><input type="checkbox" id="mf_s" ${m ? (m.allow_sensitive ? 'checked' : '') : (p.is_private ? 'checked' : '')}> 允许处理敏感模块（M4/M5）数据</span></label></div>
  <button class="primary" id="mf_ok">保存</button>`);
  $('#mf_ok').onclick = async () => {
    const body = { provider_id: pid, model_id: $('#mf_id').value, display_name: $('#mf_dn').value, enabled: $('#mf_en').checked, allow_sensitive: $('#mf_s').checked, params: { temperature: $('#mf_t').value, top_p: $('#mf_tp').value, max_tokens: $('#mf_mt').value } };
    await api('/api/admin/llm/models' + (m ? '/' + m.id : ''), { method: m ? 'PUT' : 'POST', json: body }); closeModal(); toast('已保存'); route();
  };
}
async function admTest(mid, a) { a.textContent = '测试中…'; const r = await api(`/api/admin/llm/models/${mid}/test`, { method: 'POST' }); toast(r.ok ? `连接正常（${r.ms}ms）：${r.reply}` : '连接失败：' + r.error, 5000); route(); }
async function admDelProv(id) { if (confirm('删除该供应商及其全部模型？')) { await api('/api/admin/llm/providers/' + id, { method: 'DELETE' }); route(); } }
async function admDelModel(id) { if (confirm('删除该模型？')) { await api('/api/admin/llm/models/' + id, { method: 'DELETE' }); route(); } }

/* ---------- 业务页面：模型下拉 ---------- */
window.renderModelPicker = async (module, slots) => {
  if (ident().role === 'institution') return '';
  let d; try { d = await api('/api/llm/models'); } catch (e) { return ''; }
  const sens = module === 'm4' || module === 'm5';
  const opts = (slot) => `<option value="">（未选择）</option>` + d.models.filter(m => !sens || m.allow_sensitive).map(m => `<option value="${m.id}" ${d.assign[slot] === m.id ? 'selected' : ''}>${esc(m.label)}${m.allow_sensitive ? ' 🔒' : ''}</option>`).join('');
  return `<div class="panel panel-b mb"><div class="form-row" style="margin:0">${slots.map(([s, n]) => `<label>${n} 使用模型<select class="in" onchange="mpAssign('${module}.${s}',this.value)">${opts(module + '.' + s)}</select></label>`).join('')}
  <label style="flex:1">试运行（发送一段提示词给第一个环节的模型）<input class="in" id="mp_prompt_${module}" placeholder="${d.models.length ? '例如：用三句话概括本周小微企业融资担保政策要点' : '尚未配置模型：请管理员在「系统管理」中添加'}"></label>
  <button class="secondary" onclick="mpRun('${module}.${slots[0][0]}','${module}')">运行</button></div><div id="mp_out_${module}" class="small"></div></div>`;
};
async function mpAssign(slot, mid) { await api('/api/llm/assign', { method: 'POST', json: { slot, model_id: mid } }); toast('已切换模型'); }
async function mpRun(slot, module) {
  const out = $('#mp_out_' + module); out.textContent = '调用中…';
  try { const r = await api('/api/llm/run', { method: 'POST', json: { slot, prompt: $('#mp_prompt_' + module).value } }); out.innerHTML = `<div class="note-box">【${esc(r.model)} · ${r.ms}ms】<br>${esc(r.content).replace(/\n/g, '<br>')}</div>`; }
  catch (e) { out.textContent = ''; }
}

/* ---------- 联网搜索供应商 ---------- */
async function admSearch(v, head) {
  const d = await api('/api/admin/search/providers'); ADM.sp = d;
  v.innerHTML = head + `<p class="small mb">供 M1 搜索驱动采集、M3 公开资料联网检索使用；可配置多个，标记一个为默认（启用中的默认供应商优先）。</p>
  <div class="panel panel-b mb"><h2 class="mb">新增搜索供应商</h2><div class="quick-grid" style="grid-template-columns:repeat(4,1fr);padding:0">
  ${d.presets.map(p => `<button onclick="admSpForm(null,'${p.vendor}')"><b>＋</b><span>${esc(p.name)}</span></button>`).join('')}</div></div>
  <div class="panel"><table class="grid"><thead><tr><th>名称</th><th>类型</th><th>接口地址</th><th>API Key</th><th>参数</th><th>状态</th><th>默认</th><th>最近测试</th><th></th></tr></thead><tbody>
  ${d.providers.map(p => `<tr><td>${esc(p.name)}</td><td>${esc(p.vendor_name)}</td><td class="small">${esc(p.endpoint)}</td><td>${p.has_key ? esc(p.api_key_masked) : '<b style="color:var(--red)">未设置</b>'}</td>
  <td class="small">${esc(Object.entries(p.params).map(([k, x]) => k + '=' + x).join(' '))}</td><td>${p.enabled ? '<span class="pill green">启用</span>' : '<span class="pill gray">停用</span>'}</td>
  <td>${p.is_default ? '<span class="pill red">默认</span>' : `<a class="edit" onclick="admSpDefault(${p.id})">设为默认</a>`}</td>
  <td class="small">${p.last_test ? (p.last_test.ok ? `<span class="pill green">正常 ${p.last_test.n} 条</span>` : `<span class="pill red" title="${esc(p.last_test.error)}">失败</span> ${esc((p.last_test.error || '').slice(0, 40))}`) + ' ' + esc(p.last_test.at) : '未测试'}</td>
  <td><a class="edit" onclick="admSpTest(${p.id},this)">测试</a><a class="edit" onclick="admSpForm(${p.id})">编辑</a><a class="edit" onclick="admSpDel(${p.id})">删除</a></td></tr>`).join('') || '<tr><td colspan="9" class="small">尚未配置</td></tr>'}</tbody></table></div>`;
}
function admSpForm(pid, vendor) {
  const p = pid ? ADM.sp.providers.find(x => x.id === pid) : null; const pre = ADM.sp.presets.find(x => x.vendor === (p ? p.vendor : vendor));
  const params = p ? p.params : pre.params;
  openModal((p ? '编辑' : '新增') + '搜索供应商：' + pre.name, `<p class="small mb">${esc(pre.hint)}</p>
  <div class="form-row"><label style="flex:1">名称<input class="in" id="sp_name" value="${esc(p ? p.name : pre.name)}"></label></div>
  <div class="form-row"><label style="flex:1">接口地址<input class="in" id="sp_ep" value="${esc(p ? p.endpoint : pre.endpoint)}"></label></div>
  <div class="form-row"><label style="flex:1">API Key ${p && p.has_key ? '（已设置：' + esc(p.api_key_masked) + '；留空不修改）' : ''}<input class="in" id="sp_key" type="password" autocomplete="off"></label></div>
  <div class="form-row">${Object.entries(params).map(([k, x]) => `<label>${k}<input class="in sp_p" data-k="${k}" value="${esc(x)}"></label>`).join('')}</div>
  <div class="form-row"><label><span><input type="checkbox" id="sp_en" ${!p || p.enabled ? 'checked' : ''}> 启用</span></label><label><span><input type="checkbox" id="sp_def" ${p && p.is_default ? 'checked' : ''}> 设为默认</span></label>
  ${p && p.has_key ? '<label><span><input type="checkbox" id="sp_clr"> 清除已保存的 Key</span></label>' : ''}</div><button class="primary" id="sp_ok">保存</button>`);
  $('#sp_ok').onclick = async () => {
    const prm = {}; $$('.sp_p').forEach(i => prm[i.dataset.k] = i.value);
    const body = { vendor: pre.vendor, name: $('#sp_name').value, endpoint: $('#sp_ep').value, api_key: $('#sp_key').value || null, enabled: $('#sp_en').checked, is_default: $('#sp_def').checked, params: prm };
    if ($('#sp_clr') && $('#sp_clr').checked) body.clear_key = true;
    await api('/api/admin/search/providers' + (p ? '/' + p.id : ''), { method: p ? 'PUT' : 'POST', json: body }); closeModal(); toast('已保存'); route();
  };
}
async function admSpTest(id, a) { a.textContent = '测试中…'; const r = await api(`/api/admin/search/providers/${id}/test`, { method: 'POST' }); toast(r.ok ? `正常：返回 ${r.n} 条，例：${r.sample}` : '失败：' + r.error, 5000); route(); }
async function admSpDefault(id) { await api(`/api/admin/search/providers/${id}/default`, { method: 'POST' }); route(); }
async function admSpDel(id) { if (confirm('删除该搜索供应商？')) { await api('/api/admin/search/providers/' + id, { method: 'DELETE' }); route(); } }

/* ---------- M1 采集规则与查询模板 ---------- */
const LV_OPTS = ['官方(A1/A2)', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2'];
async function admM1(v, head) {
  const d = await api('/api/m1/config'); const c = d.config; ADM.m1 = c;
  const ruleRow = (r, i) => `<tr><td><input class="in r_d" value="${esc(r.domain)}" style="width:170px"></td><td><input class="in r_p" value="${esc(r.publisher)}" style="width:200px"></td>
   <td><select class="in r_l">${LV_OPTS.map(o => `<option ${o === r.level ? 'selected' : ''}>${o}</option>`).join('')}</select></td>
   <td><input class="in r_y" value="${esc(r.layer || '')}" style="width:110px" placeholder="按查询地域"></td><td><input class="in r_x" value="${esc(r.path_regex || '')}" style="width:130px"></td>
   <td><a class="edit" onclick="this.closest('tr').remove()">删除</a></td></tr>`;
  v.innerHTML = head + `<div class="note-box mb">M1 不依赖固定网站清单：按「查询模板 × 主题 × 地域」定时调用联网搜索，只保留命中「权威发布方规则」且等级在保留范围内的结果，再抓取正文、AI 提炼要点。规则自上而下匹配，<b>首条命中生效</b>（具体站点放在通配规则之前）；域名自动包含子域。等级「官方(A1/A2)」= URL 路径命中正式文件路径正则判为 A1，否则 A2。</div>
  <div class="grid2 mb"><div class="panel panel-b"><h2 class="mb">查询与调度</h2>
   <div class="form-row"><label style="flex:1">查询模板（可用 {region} {topic}）<input class="in" id="m1_tpl" value="${esc(c.template)}"></label></div>
   <div class="form-row"><label style="flex:1">主题词（每行一个）<textarea class="in" id="m1_topics" style="min-height:150px">${esc(c.topics.join('\n'))}</textarea></label></div>
   <div class="form-row"><label>手动每轮最多检索次数<input class="in" id="m1_maxq" type="number" value="${c.max_queries_per_run}"></label>
   <label title="仅约束定时采集（如 07:00）；与手动采集分开">定时每日检索上限<input class="in" id="m1_sched_maxq" type="number" value="${c.max_queries_scheduled_per_day ?? 5}"></label>
   <label>每次返回条数<input class="in" id="m1_rpq" type="number" value="${c.results_per_query}"></label>
   <label>时间范围<select class="in" id="m1_tr">${['day', 'week', 'month', 'year', 'none'].map(o => `<option ${o === c.time_range ? 'selected' : ''}>${o}</option>`).join('')}</select></label></div>
   <div class="form-row"><label>保留等级${['A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map(l => `<span><input type="checkbox" class="m1_keep" value="${l}" ${c.keep_levels.includes(l) ? 'checked' : ''}> ${l}</span>`).join(' ')}</label></div>
   <div class="form-row"><label><span><input type="checkbox" id="m1_sch" ${c.schedule.enabled ? 'checked' : ''}> 启用定时采集</span></label><label>每日执行时间（逗号分隔）<input class="in" id="m1_times" value="${esc(c.schedule.times.join(','))}"></label>
   <label><span><input type="checkbox" id="m1_fetch" ${c.fetch_content ? 'checked' : ''}> 抓取正文</span></label><label>每轮 AI 摘要上限<input class="in" id="m1_ai" type="number" value="${c.ai_summary_per_run}"></label></div>
   <div class="form-row"><label style="flex:1">正式文件路径正则（判 A1）<input class="in" id="m1_a1" value="${esc(c.a1_path_regex)}"></label></div>
   <p class="small">手动下一轮将执行 ${d.plan_total} 次检索：每轮必扫 ${d.plan_info.fixed} 次（国家 + 广东本省 × 主题），其余 ${d.plan_info.rotating} 个「地域×主题」组合轮转${d.plan_info.cycle_runs ? `，约 ${d.plan_info.cycle_runs} 轮覆盖一遍` : ''}。定时采集每日硬上限 <b>${c.max_queries_scheduled_per_day ?? 5}</b> 次（今日已用 ${d.scheduled_plan_info?.used_today ?? 0}，本批 ${d.scheduled_plan_total} 次；优先国家/广东的融资担保·再担保主题，其余主题与地域按日轮转${d.scheduled_plan_info?.cycle_days ? `，约 ${d.scheduled_plan_info.cycle_days} 天覆盖一轮` : ''}）。手动采集不受该上限约束。</p></div>
  <div class="panel panel-b"><h2 class="mb">地域层级（每行一个地域）</h2>${c.tiers.map((t, i) => `<div class="mb"><label class="small"><b>${esc(t.name)}</b>（政策层级：${esc(t.layer)}） <span><input type="checkbox" class="t_every" data-i="${i}" ${t.every_run ? 'checked' : ''}> 每轮必扫</span></label>
   <textarea class="in t_regions" data-i="${i}" style="min-height:${t.regions.length > 3 ? 70 : 36}px">${esc(t.regions.join(' '))}</textarea></div>`).join('')}<p class="small">地域以空格或换行分隔；「全国」表示不加地域前缀。</p></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>权威发布方规则（${c.rules.length} 条）</h2><p>不在规则内的站点判为 C2（仅线索，默认不保留）。</p></div><button class="secondary mini" id="r_add">＋ 新增规则</button></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>域名（含子域）</th><th>发布方名称</th><th>来源等级</th><th>政策层级</th><th>路径正则（可选）</th><th></th></tr></thead><tbody id="r_tb">${c.rules.map(ruleRow).join('')}</tbody></table></div></div>
  <button class="primary" onclick="admM1Save()">保存采集配置</button> <button class="ghost" onclick="admM1Reset()">恢复默认</button>
  <div class="panel panel-b" style="margin-top:16px"><h2 class="mb">手动下一轮查询预览（前 ${Math.min(d.next_plan.length, 200)} 条）</h2><div class="small" style="max-height:200px;overflow:auto">${d.next_plan.map(q => `<span class="pill gray" style="margin:2px">${esc(q.query)}</span>`).join('')}</div></div>
  <div class="panel panel-b" style="margin-top:16px"><h2 class="mb">定时采集下一批预览（${d.scheduled_plan_total} 条，每日上限 ${c.max_queries_scheduled_per_day ?? 5}）</h2><div class="small" style="max-height:120px;overflow:auto">${(d.scheduled_next_plan || []).map(q => `<span class="pill gray" style="margin:2px">${esc(q.query)}</span>`).join('') || '今日额度已用完'}</div></div>`;
  $('#r_add').onclick = () => { $('#r_tb').insertAdjacentHTML('afterbegin', ruleRow({ domain: '', publisher: '', level: 'A2', layer: '', path_regex: '' })); };
}
async function admM1Save() {
  const c = ADM.m1;
  const rules = $$('#r_tb tr').map(tr => ({ domain: $('.r_d', tr).value.trim(), publisher: $('.r_p', tr).value.trim(), level: $('.r_l', tr).value, layer: $('.r_y', tr).value.trim(), path_regex: $('.r_x', tr).value.trim() })).filter(r => r.domain);
  const tiers = c.tiers.map((t, i) => Object.assign({}, t, { every_run: $(`.t_every[data-i="${i}"]`).checked, regions: $(`.t_regions[data-i="${i}"]`).value.split(/[\s,，]+/).filter(Boolean) }));
  const body = { template: $('#m1_tpl').value, topics: $('#m1_topics').value.split('\n').map(s => s.trim()).filter(Boolean), max_queries_per_run: +$('#m1_maxq').value, max_queries_scheduled_per_day: +$('#m1_sched_maxq').value, results_per_query: +$('#m1_rpq').value,
    time_range: $('#m1_tr').value, keep_levels: $$('.m1_keep').filter(i => i.checked).map(i => i.value), schedule: { enabled: $('#m1_sch').checked, times: $('#m1_times').value.split(/[,，\s]+/).filter(Boolean) },
    fetch_content: $('#m1_fetch').checked, ai_summary_per_run: +$('#m1_ai').value, a1_path_regex: $('#m1_a1').value, rules, tiers };
  await api('/api/admin/m1/config', { method: 'PUT', json: body }); toast('采集配置已保存'); route();
}
async function admM1Reset() { if (confirm('恢复默认规则与查询模板？')) { await api('/api/admin/m1/config/reset', { method: 'POST' }); route(); } }

/* ---------- 演示数据与上线就绪 ---------- */
async function admDemo(v, head) {
  const d = await api('/api/admin/demo');
  v.innerHTML = head + `<div class="grid2 mb"><div class="panel"><div class="panel-head"><div><h2>上线就绪检查</h2><p>演示前逐项打勾；点击「去配置」直达</p></div></div><div class="panel-b">
   ${d.checks.map(c => `<div class="task-row"><span class="pill ${c.ok ? 'green' : 'red'}">${c.ok ? '✓ 就绪' : '✗ 待处理'}</span><div style="flex:1">${esc(c.text)}</div>${c.ok ? '' : `<a class="edit" href="${c.fix}">去配置</a>`}</div>`).join('')}
   ${d.warnings.map(w => `<div class="alert warn" style="margin-top:10px">${esc(w)}</div>`).join('')}</div></div>
  <div class="panel"><div class="panel-head"><div><h2>一键演示数据</h2><p>${d.demo.loaded ? '已加载于 ' + esc(d.demo.loaded_at) : '未加载'}</p></div></div><div class="panel-b">
   <p class="small mb">加载：M1 演示政策条目（含转载归并、低等级来源样例）、近 7 天 M2 简报（较早的已发布）、1 篇已定稿 M3 研究（含引用来源登记表与写作规范）、四类 PPT 样例；M4/M5 无数据时同时导入样表。不调用任何大模型。<br>清除：只删除演示包写入的记录与文件，不影响真实业务数据（机构主数据保留）。</p>
   ${d.demo.loaded ? `<div class="small mb">${Object.entries(d.demo.counts).filter(([, n]) => n).map(([k, n]) => `${esc(k)} ${n}`).join(' · ')}</div>` : ''}
   <button class="primary" ${d.demo.loaded ? 'disabled' : ''} onclick="admDemoAct('load')">加载演示数据</button> <button class="ghost" ${d.demo.loaded ? '' : 'disabled'} onclick="admDemoAct('clear')">清除演示数据</button></div></div></div>
  <div class="panel"><div class="panel-head"><div><h2>模型配置建议（Key 由管理员自行填写）</h2></div></div><div class="panel-b small" style="line-height:1.9">
   1. 公有云模型 1 个（如 DeepSeek / 通义千问 / 智谱 / MiniMax 按量 API Key）：用于 M1 摘要、M2 简报要点、M3 写作（不含 M5 数据）、政策简报类 PPT。<br>
   2. 「允许处理敏感数据」模型 1 个（公司私有模型，或经授权的模型）：用于勾选 M5 数据的 M3 写作、额度汇报/授信上会材料 PPT（需求第 10 章：混合部署策略）。<br>
   3. 在「大模型配置」页底部把各环节分配到对应模型，并点「测试连接」确认可用；在「联网搜索」页填写 Tavily 或阿里云 IQS Key。<br>
   4. <b style="color:var(--red)">不要把 MiniMax 包月 Token Plan（sk-cp- 订阅 Key）设为服务端默认模型</b>：官方定位个人交互使用，且有 5 小时/周额度窗口与限流，演示中途可能返回 429。</div></div>`;
}
async function admDemoAct(k) {
  if (!confirm(k === 'load' ? '加载演示数据？' : '清除全部演示数据？（真实数据不受影响）')) return;
  toast(k === 'load' ? '正在加载演示数据…' : '正在清除…', 15000);
  const r = await api('/api/admin/demo/' + k, { method: 'POST' });
  toast((r.warnings || []).length ? '完成（' + r.warnings.join('；') + '）' : '完成', 4000); route();
}

/* ---------- 运行状态 ---------- */
async function admOps(v, head) {
  const [d, bk] = await Promise.all([api('/api/admin/ops'), api('/api/admin/backups')]);
  v.innerHTML = head + `<div class="kv mb"><div><span>最近启动</span><b style="font-size:14px">${esc(d.boot.at || '—')}</b></div><div><span>启动时恢复的中断任务</span><b>${(d.boot.recovered_m3 || 0) + (d.boot.recovered_m1 || 0)}</b></div>
   <div><span>调度器</span><b style="font-size:14px">${d.scheduler_disabled ? '已禁用（环境变量）' : d.lock_held ? '本进程持有调度锁' : '未持有（其他进程运行）'}</b></div><div><span>HTTPS 证书</span><b style="font-size:13px;color:${d.cert && d.cert.days_left < 2 ? 'var(--red)' : 'inherit'}">${d.cert ? '剩余 ' + d.cert.days_left + ' 天（到期 ' + esc(d.cert.not_after) + ' 北京时间）' : '未知'}</b></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>定时任务</h2><p>心跳 3 分钟内为「运行中」；失败会记录原因并写入操作留痕</p></div><button class="ghost mini" onclick="route()">刷新</button></div><table class="grid"><thead><tr><th>任务</th><th>启用</th><th>计划</th><th>调度线程</th><th>最近开始</th><th>最近结束</th><th>结果</th><th>耗时</th></tr></thead><tbody>
   ${d.schedulers.map(s => `<tr><td>${esc(s.name)}</td><td>${s.enabled ? '是' : '否'}</td><td>${esc(s.plan || '')}</td><td>${s.alive ? '<span class="pill green">运行中</span>' : '<span class="pill gray">无心跳</span>'} <span class="small">${esc(s.tick || '')}</span></td>
     <td class="small">${esc(s.last_start || '—')}</td><td class="small">${esc(s.last_end || '—')}</td><td>${s.running ? '<span class="pill blue">执行中</span>' : s.last_ok === false ? `<span class="pill red" title="${esc(s.last_error || '')}">失败</span> <span class="small">${esc((s.last_error || '').slice(0, 60))}</span>` : s.last_ok ? '<span class="pill green">成功</span>' : '—'}</td><td>${s.last_ms != null ? (s.last_ms / 1000).toFixed(1) + 's' : ''}</td></tr>`).join('')}</tbody></table></div>
  <div class="grid2 mb"><div class="panel"><div class="panel-head"><div><h2>中断 / 失败的写作任务</h2></div></div><div class="panel-b small">
   ${d.interrupted.map(t => `<div class="task-row"><span class="pill ${t.status === '失败' ? 'red' : 'gold'}">${esc(t.status)}</span><div style="flex:1"><b>#${t.id} ${esc(t.title)}</b><br>${esc((t.error || '').slice(0, 120))}</div><a class="edit" onclick="M3T.id=${t.id};nav('m3','tasks')">打开</a><a class="edit" onclick="m3Rerun(${t.id})">重新运行</a></div>`).join('') || '无'}</div></div>
   <div class="panel"><div class="panel-head"><div><h2>最近重试记录（大模型 / 搜索）</h2><p>429 / 5xx / 网络超时自动指数退避重试</p></div></div><div class="panel-b small">${d.retries.map(r => `<div>${esc(r.at)} ${esc(r.msg)}</div>`).join('') || '无'}</div></div></div>
  <div class="panel mb"><div class="panel-head"><div><h2>数据库备份（${bk.files.length} 份）</h2><p>目录 ${esc(bk.dir)}（独立于数据卷）；每日 ${esc(bk.config.time)} 自动备份，保留最近 ${bk.config.keep_daily} 天 + ${bk.config.keep_weekly} 周；每份含完整性校验。恢复步骤见 docs/backup_restore.md</p></div>
    <div class="form-row" style="margin:0"><label>时间<input class="in" id="bk_t" value="${esc(bk.config.time)}" style="width:70px"></label><label>保留天<input class="in" id="bk_d" type="number" value="${bk.config.keep_daily}" style="width:60px"></label><label>保留周<input class="in" id="bk_w" type="number" value="${bk.config.keep_weekly}" style="width:60px"></label>
    <button class="ghost mini" onclick="admBkCfg()">保存设置</button><button class="primary mini" onclick="admBkNow()">立即备份</button></div></div>
   ${bk.last ? `<div class="panel-b small">最近一次：${esc(bk.last.at)} ${esc(bk.last.name)}（${(bk.last.size / 1024).toFixed(0)} KB，校验 ${esc(bk.last.integrity)}，${esc(bk.last.trigger)}）</div>` : ''}
   <div class="tbl-wrap" style="max-height:260px"><table class="grid"><thead><tr><th>文件</th><th>时间</th><th>大小</th></tr></thead><tbody>${bk.files.map(f => `<tr><td>${esc(f.name)}</td><td>${esc(f.at)}</td><td class="n">${(f.size / 1024).toFixed(0)} KB</td></tr>`).join('') || '<tr><td colspan="3" class="small">暂无备份</td></tr>'}</tbody></table></div></div>
  <div class="panel"><div class="panel-head"><div><h2>最近 M1 采集</h2></div></div><table class="grid"><thead><tr><th>#</th><th>触发</th><th>开始</th><th>结束</th><th>状态</th></tr></thead><tbody>${d.m1_runs.map(r => `<tr><td>${r.id}</td><td>${esc(r.trigger)}</td><td>${esc(r.started_at)}</td><td>${esc(r.finished_at || '')}</td><td>${esc(r.status)}</td></tr>`).join('') || '<tr><td colspan="5" class="small">无</td></tr>'}</tbody></table></div>`;
}

async function admBkNow() { toast('正在备份…', 8000); const r = await api('/api/admin/backups', { method: 'POST' }); toast('已备份：' + r.name, 4000); route(); }
async function admBkCfg() { await api('/api/admin/backups/config', { method: 'PUT', json: { time: $('#bk_t').value, keep_daily: +$('#bk_d').value, keep_weekly: +$('#bk_w').value } }); toast('已保存'); route(); }

/* ---------- 用户与权限 ---------- */
async function admUsers(v, head) {
  const d = await api('/api/admin/users'); ADM.users = d;
  v.innerHTML = head + `<div class="note-box mb">角色权限：<b>普惠部（内部）</b>可使用 M1~M5、PPT、机构主数据与操作留痕；<b>合作机构用户</b>只能看到本机构的 M5 看板、已发布的 M2 简报与单机构自测，M3/M4/PPT 不可见。系统管理员使用独立管理员账号。
  新建或重置后系统只显示一次临时密码，用户首次登录须修改。连续 5 次密码错误锁定 5 分钟。</div>
  <div class="panel"><div class="panel-head"><div><h2>业务账号</h2></div><button class="primary mini" onclick="admUserForm()">＋ 新建账号</button></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>所属机构</th><th>状态</th><th>最近登录</th><th>创建</th><th></th></tr></thead><tbody>
  ${d.users.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${esc(u.role_name)}</td><td class="l">${esc(u.org || '—')}</td>
   <td>${u.enabled ? '<span class="pill green">启用</span>' : '<span class="pill gray">停用</span>'} ${u.must_change ? '<span class="pill gold">待改初始密码</span>' : ''}</td>
   <td class="small">${esc(u.last_login || '—')}</td><td class="small">${esc(u.created_at || '')} ${esc(u.created_by || '')}</td>
   <td><a class="edit" onclick="admUserForm('${esc(u.username)}')">编辑</a><a class="edit" onclick="admUserReset('${esc(u.username)}')">重置密码</a><a class="edit" onclick="admUserToggle('${esc(u.username)}',${u.enabled ? 0 : 1})">${u.enabled ? '停用' : '启用'}</a></td></tr>`).join('') || '<tr><td colspan="8" class="small">暂无账号</td></tr>'}
  </tbody></table></div></div>`;
}
function admUserForm(un) {
  const u = un ? ADM.users.users.find(x => x.username === un) : { role: 'internal' };
  const d = ADM.users;
  openModal(un ? '编辑账号' : '新建账号', `<div class="form-row"><label style="flex:1">用户名<input class="in" id="uf_u" value="${esc(u.username || '')}" ${un ? 'disabled' : ''} placeholder="3~32 位字母/数字/下划线"></label>
   <label style="flex:1">显示名<input class="in" id="uf_d" value="${esc(u.display_name || '')}"></label></div>
   <div class="form-row"><label style="flex:1">角色<select class="in" id="uf_r">${['internal', 'institution'].map(k => `<option value="${k}" ${u.role === k ? 'selected' : ''}>${esc(d.roles[k])}</option>`).join('')}</select></label>
   <label style="flex:2">所属机构（合作机构用户必选）<select class="in" id="uf_o"><option value="">—</option>${d.institutions.map(n => `<option ${n === u.org ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label></div>
   <button class="primary" id="uf_ok">保存</button>`);
  $('#uf_ok').onclick = async () => {
    const body = { username: $('#uf_u').value.trim(), display_name: $('#uf_d').value.trim(), role: $('#uf_r').value, org: $('#uf_o').value || null };
    const r = await api('/api/admin/users' + (un ? '/' + encodeURIComponent(un) : ''), { method: un ? 'PUT' : 'POST', json: body });
    closeModal(); if (r.initial_password) admShowPw(body.username, r.initial_password); route();
  };
}
function admShowPw(un, pw) {
  setTimeout(() => openModal('临时密码（只显示这一次）', `<p class="mb">账号 <b>${esc(un)}</b> 的临时密码：</p><p><code style="font-size:18px;user-select:all">${esc(pw)}</code></p><p class="small">请通过安全渠道告知本人；首次登录须修改。关闭后无法再次查看，只能重置。</p>`), 300);
}
async function admUserReset(un) { if (!confirm(`重置 ${un} 的密码？其现有登录会话将失效。`)) return; const r = await api(`/api/admin/users/${encodeURIComponent(un)}/reset`, { method: 'POST' }); admShowPw(un, r.initial_password); route(); }
async function admUserToggle(un, en) { await api(`/api/admin/users/${encodeURIComponent(un)}`, { method: 'PUT', json: { enabled: en } }); toast(en ? '已启用' : '已停用（会话已失效）'); route(); }

/* ---------- 大模型调用记录（快照，可复现） ---------- */
ADM.callF = {};
async function admCalls(v, head) {
  const f = ADM.callF;
  const d = await api('/api/admin/llm/calls?' + new URLSearchParams({ slot: f.slot || '', ok: f.ok || '', q: f.q || '', ref: f.ref || '' }));
  const st = d.stats || {};
  v.innerHTML = head + `<div class="note-box mb">每次业务调用大模型都保存快照：环节、模型与供应商、参数、提示词版本、<b>完整输入</b>、<b>原始输出</b>、tokens、耗时、关联任务（如 m3_task:12）。用于复现与追责；保留 180 天。仅系统管理员可见。</div>
  <div class="kv mb"><div><span>累计调用</span><b>${f0(st.n)}</b></div><div><span>累计 tokens</span><b>${f0(st.t)}</b></div><div><span>失败次数</span><b>${f0(st.f)}</b></div><div><span>平均耗时</span><b>${st.ms ? f0(st.ms) + ' ms' : '—'}</b></div></div>
  <div class="panel"><div class="panel-head"><div><h2>调用记录（最近 ${d.calls.length} 条）</h2></div><div class="form-row" style="margin:0">
   <select class="in" id="cf_s"><option value="">全部环节</option>${Object.entries(d.slots).map(([k, n]) => `<option value="${k}" ${f.slot === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>
   <select class="in" id="cf_o"><option value="">全部结果</option><option value="1" ${f.ok === '1' ? 'selected' : ''}>成功</option><option value="0" ${f.ok === '0' ? 'selected' : ''}>失败</option></select>
   <input class="in" id="cf_r" placeholder="关联任务，如 m3_task:12" value="${esc(f.ref || '')}" style="width:170px"><input class="in" id="cf_q" placeholder="输入/输出关键词" value="${esc(f.q || '')}">
   <button class="secondary mini" onclick="ADM.callF={slot:$('#cf_s').value,ok:$('#cf_o').value,ref:$('#cf_r').value.trim(),q:$('#cf_q').value.trim()};route()">筛选</button></div></div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th>#</th><th>时间</th><th>环节</th><th>模型</th><th>提示词版本</th><th>关联</th><th>tokens（入/出）</th><th>耗时</th><th>结果</th><th>操作人</th><th></th></tr></thead><tbody>
  ${d.calls.map(c => `<tr><td>${c.id}</td><td class="small">${esc(c.ts)}</td><td class="small">${esc(d.slots[c.slot] || c.slot)}</td><td class="small">${esc(c.model)}<br><span class="small">${esc(c.provider || '')}</span></td><td class="small">${esc(c.prompt_version || '—')}</td>
   <td class="small">${c.ref ? `<a class="edit" onclick="ADM.callF={ref:'${esc(c.ref)}'};route()">${esc(c.ref)}</a>` : '—'}</td><td class="n">${f0(c.total_tokens)}<br><span class="small">${c.prompt_tokens ?? '—'} / ${c.completion_tokens ?? '—'}</span></td><td class="n">${c.ms != null ? f0(c.ms) + ' ms' : '—'}</td>
   <td>${c.ok ? '<span class="pill green">成功</span>' : `<span class="pill red" title="${esc(c.error || '')}">失败</span>`}</td><td class="small">${esc(c.user || '')}</td><td><a class="edit" onclick="admCall(${c.id})">查看</a></td></tr>`).join('') || '<tr><td colspan="11" class="small">暂无调用记录</td></tr>'}</tbody></table></div></div>`;
}
async function admCall(id) {
  const c = await api('/api/admin/llm/calls/' + id); ADM.call = c;
  const msgs = Array.isArray(c.input) ? c.input : [{ role: '?', content: String(c.input) }];
  const pre = t => `<pre class="call-pre">${esc(t || '')}</pre>`;
  openModal(`调用 #${c.id} · ${c.slot}`, `<div class="kv mb"><div><span>时间</span><b style="font-size:13px">${esc(c.ts)}</b></div><div><span>模型</span><b style="font-size:13px">${esc(c.model)} · ${esc(c.provider || '')}</b></div><div><span>提示词版本</span><b style="font-size:13px">${esc(c.prompt_version || '—')}</b></div><div><span>关联</span><b style="font-size:13px">${esc(c.ref || '—')}</b></div></div>
   <p class="small mb">参数：<code>${esc(JSON.stringify(c.params))}</code> · tokens ${c.prompt_tokens ?? '—'} / ${c.completion_tokens ?? '—'} / ${c.total_tokens ?? '—'} · ${c.ms ?? '—'} ms · 操作人 ${esc(c.user || '')}</p>
   ${c.error ? `<div class="alert error mb">${esc(c.error)}</div>` : ''}
   <h3 class="small">完整输入（${msgs.length} 条消息）</h3>${msgs.map(m => `<div class="small"><b>${esc(m.role)}</b></div>${pre(m.content)}`).join('')}
   <h3 class="small">输出（业务使用）</h3>${pre(c.output)}
   ${c.raw_output && c.raw_output !== c.output ? `<h3 class="small">原始输出（含思考内容）</h3>${pre(c.raw_output)}` : ''}
   <button class="secondary mini" onclick="admCallJson()">下载复现用 JSON</button>`);
}
function admCallJson() {
  const c = ADM.call;
  const body = { model: c.model, messages: c.input, ...c.params, _meta: { id: c.id, ts: c.ts, slot: c.slot, provider: c.provider, prompt_version: c.prompt_version, ref: c.ref } };
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' })); a.download = `llm_call_${c.id}.json`; a.click();
}
