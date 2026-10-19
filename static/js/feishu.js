/* 飞书机器人：用户绑定弹窗 + 系统管理 · 飞书机器人 */
async function feishuBindDialog() {
  const m = await api('/api/feishu/me');
  if (!m.enabled) return openModal('绑定飞书', '<div class="alert warn">管理员尚未启用飞书机器人（系统管理 → 飞书机器人）。</div><button class="secondary" onclick="closeModal()">知道了</button>');
  if (m.bound) return openModal('绑定飞书', `<p class="mb">当前账号已绑定飞书（绑定于 ${esc(m.bound_at)}${m.last_seen ? '，最近使用 ' + esc(m.last_seen) : ''}）。在飞书里私聊「${esc(m.bot_name || '机器人')}」发送「帮助」即可使用。</p>
    <button class="ghost" onclick="feishuUnbind()">解除绑定</button> <button class="secondary" onclick="feishuNewCode()">换绑到另一个飞书账号</button>`);
  feishuNewCode();
}
async function feishuNewCode() {
  const r = await api('/api/feishu/bind-code', { method: 'POST' });
  openModal('绑定飞书', `<p class="mb">在飞书里<b>私聊</b>机器人「${esc(r.bot_name || '普惠业务工作台机器人')}」，发送下面这行字：</p>
   <div class="note-box mb" style="font-size:22px;letter-spacing:2px;text-align:center"><b>绑定 ${esc(r.code)}</b></div>
   <p class="small mb">一次性绑定码，${r.ttl_min} 分钟内有效。绑定后，机器人能给您看的内容与您在网页端的权限完全一致（合作机构账号只能看到本机构数据）。请勿把绑定码发到群里。</p>
   <button class="secondary" onclick="closeModal()">我已发送</button>`);
}
async function feishuUnbind() { if (!confirm('解除飞书绑定？')) return; await api('/api/feishu/bind', { method: 'DELETE' }); closeModal(); toast('已解除绑定'); }

async function admFeishu(v, head) {
  const [c, b, ev] = await Promise.all([api('/api/admin/feishu/config'), api('/api/admin/feishu/bindings'), api('/api/admin/feishu/events?limit=100')]);
  const ws = c.ws_status || {}, t = c.last_test;
  const models = ((await api('/api/llm/models', { quiet: true }).catch(() => null)) || {}).models || [];
  const cb = location.origin + c.callback_path;
  v.innerHTML = head + `<div class="note-box mb">让用户<b>不登录网页</b>就能在飞书里查额度、预警、简报、研究报告、发起 PPT、收文件、发邮箱。<b>权限随绑定账号的角色</b>；大模型只做意图识别（只看到提问文字），数字全部来自数据库。创建应用与审批的完整步骤见 <code>docs/feishu_setup.md</code>。</div>
  <div class="panel panel-b"><h2 class="mb">应用凭据（飞书开放平台 → 您的应用 → 凭证与基础信息）</h2>
  <div class="form-row"><label style="flex:1">App ID<input class="in" id="fs_id" value="${esc(c.app_id)}" placeholder="cli_xxxxxxxxxxxxxxxx" autocomplete="off"></label>
   <label style="flex:1">App Secret ${c.has_app_secret ? '（已设置，留空不改）' : ''}<input class="in" id="fs_sec" type="password" autocomplete="new-password" placeholder="${c.has_app_secret ? '留空不修改' : '粘贴 App Secret'}"></label>
   <label>飞书 / Lark<select class="in" id="fs_dom"><option value="feishu" ${c.domain === 'feishu' ? 'selected' : ''}>飞书（open.feishu.cn）</option><option value="lark" ${c.domain === 'lark' ? 'selected' : ''}>Lark 国际版</option></select></label></div>
  <div class="form-row"><label>事件接收方式<select class="in" id="fs_mode"><option value="ws" ${c.mode === 'ws' ? 'selected' : ''}>长连接（推荐：无需公网回调地址）</option><option value="http" ${c.mode === 'http' ? 'selected' : ''}>HTTP 回调（需放行 Basic Auth）</option></select></label>
   <label style="flex:1">Verification Token ${c.has_verification_token ? '（已设置）' : ''}<input class="in" id="fs_vt" type="password" autocomplete="new-password" placeholder="HTTP 回调必填；长连接可留空"></label>
   <label style="flex:1">Encrypt Key ${c.has_encrypt_key ? '（已设置）' : ''}<input class="in" id="fs_ek" type="password" autocomplete="new-password" placeholder="可选；启用加密推送时填"></label></div>
  <div class="form-row"><label>每人每分钟最多消息数<input class="in" id="fs_rate" type="number" value="${c.rate_per_min}"></label><label>绑定码有效分钟<input class="in" id="fs_ttl" type="number" value="${c.bind_ttl_min}"></label>
   <label style="flex:1">意图识别模型（可选；不选则只识别固定指令）<select class="in" id="fs_model"><option value="">（不使用大模型）</option>${(Array.isArray(models) ? models : []).map(m => `<option value="${m.id}" ${c.router_model_id == m.id ? 'selected' : ''}>${esc(m.label)}</option>`).join('')}</select></label></div>
  <div class="form-row"><label><span><input type="checkbox" id="fs_en" ${c.enabled ? 'checked' : ''}> 启用飞书机器人</span></label>
   <label><span><input type="checkbox" id="fs_grp" ${c.group_data ? 'checked' : ''}> 允许在群聊中回答内部数据（默认关闭：群聊只回答简报/政策，额度等请私聊）</span></label></div>
  <button class="primary" onclick="admFeishuSave()">保存（长连接模式保存后自动重连）</button> <button class="secondary" onclick="admFeishuTest()">测试连接</button>
  <p class="small" style="margin-top:8px">连接状态：<b>${esc(ws.state || '—')}</b> ${ws.msg ? '· ' + esc(ws.msg) : ''}　${t ? `最近测试 ${esc(t.at)}：${t.ok ? `<span class="pill green">成功</span> 机器人「${esc(t.bot_name || '')}」` : `<span class="pill red">失败</span> ${esc(t.error || '')}`}` : '尚未测试'}</p>
  <p class="small">HTTP 回调地址（仅「HTTP 回调」模式使用）：<code>${esc(cb)}</code></p></div>
  <div class="panel mt"><div class="panel-head"><div><h2>已绑定账号（${b.bindings.length}）</h2><p>用户在网页「绑定飞书」获取绑定码后私聊机器人完成绑定；也可在此按 open_id 手工映射（open_id 见下方事件日志中未绑定用户发来的消息）。</p></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>工作台账号</th><th>姓名</th><th>角色/机构</th><th>飞书 open_id</th><th>绑定时间/方式</th><th>最近使用</th><th></th></tr></thead><tbody>
   ${b.bindings.map(x => `<tr><td>${esc(x.username)}</td><td>${esc(x.display_name || '')}</td><td>${esc(x.role || '')} ${esc(x.org || '')}</td><td class="small">${esc(x.open_id)}</td><td class="small">${esc(x.bound_at)} · ${esc(x.bound_by || '')}</td><td class="small">${esc(x.last_seen || '')}</td><td><a class="edit danger" onclick="admFeishuUnbind('${esc(x.open_id)}')">解绑</a></td></tr>`).join('') || '<tr><td colspan="7" class="small">暂无绑定</td></tr>'}</tbody></table></div>
   <div class="panel-b"><div class="form-row"><label style="flex:1">手工映射：飞书 open_id<input class="in" id="fs_map_oid" placeholder="ou_xxxxxxxxxxxxxxxx"></label><label>映射到账号<select class="in" id="fs_map_u">${b.users.map(u => `<option value="${esc(u.username)}">${esc(u.username)}（${esc(u.display_name || '')}）</option>`).join('')}</select></label><button class="secondary" onclick="admFeishuMap()">映射</button></div></div></div>
  <div class="panel mt"><div class="panel-head"><div><h2>事件日志（最近 ${ev.length} 条）</h2><p>每条机器人收到的消息：时间、飞书用户、绑定账号、识别意图、处理结果与回复摘要（保留 90 天；绑定码已打码）。</p></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>时间</th><th>来源</th><th>类型</th><th>open_id</th><th>账号</th><th>消息</th><th>意图</th><th>结果</th><th>回复摘要</th></tr></thead><tbody>
   ${ev.map(e => `<tr><td class="small">${esc(e.ts)}</td><td class="small">${esc(e.source || '')}</td><td class="small">${e.chat_type === 'group' ? '群聊' : '单聊'}</td><td class="small">${esc(e.open_id || '')}</td><td>${esc(e.username || '—')}</td><td class="l">${esc((e.text || '').slice(0, 60))}</td><td class="small">${esc(e.intent || '')}</td>
   <td><span class="pill ${e.status === '已处理' ? 'green' : ['未绑定', '限流', '拒绝'].includes(e.status) ? 'gold' : 'red'}" title="${esc(e.error || '')}">${esc(e.status)}</span></td><td class="l small" title="${esc(e.reply || '')}">${esc((e.reply || '').replace(/\n/g, ' ').slice(0, 70))}</td></tr>`).join('') || '<tr><td colspan="9" class="small">暂无事件</td></tr>'}</tbody></table></div></div>`;
}
async function admFeishuSave() {
  const body = { app_id: $('#fs_id').value, app_secret: $('#fs_sec').value || null, domain: $('#fs_dom').value, mode: $('#fs_mode').value, verification_token: $('#fs_vt').value || null, encrypt_key: $('#fs_ek').value || null,
    rate_per_min: $('#fs_rate').value, bind_ttl_min: $('#fs_ttl').value, enabled: $('#fs_en').checked, group_data: $('#fs_grp').checked, router_model_id: $('#fs_model').value || null };
  await api('/api/admin/feishu/config', { method: 'PUT', json: body }); toast('已保存'); route();
}
async function admFeishuTest() {
  toast('正在连接飞书…', 15000);
  const r = await api('/api/admin/feishu/test', { method: 'POST' });
  toast(r.ok ? '连接成功：机器人「' + r.bot_name + '」' : '⚠ 失败：' + r.error, 6000); route();
}
async function admFeishuUnbind(oid) { if (!confirm('解除该飞书账号的绑定？')) return; await api('/api/admin/feishu/bindings/' + encodeURIComponent(oid), { method: 'DELETE' }); route(); }
async function admFeishuMap() { await api('/api/admin/feishu/bindings', { method: 'POST', json: { open_id: $('#fs_map_oid').value, username: $('#fs_map_u').value } }); toast('已映射'); route(); }
