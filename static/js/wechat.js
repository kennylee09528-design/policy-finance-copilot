/* 微信「普惠Bot」：用户扫码绑定 + 系统管理 */
let WX_QR_TIMER = null;
function wxStopPoll() { if (WX_QR_TIMER) { clearInterval(WX_QR_TIMER); WX_QR_TIMER = null; } }

async function wechatBindDialog() {
  const m = await api('/api/wechat/me');
  if (!m.enabled) return openModal('绑定微信 · 普惠Bot', '<div class="alert warn">管理员尚未启用微信「普惠Bot」（系统管理 → 微信普惠Bot）。</div><button class="secondary" onclick="closeModal()">知道了</button>');
  if (m.bound) {
    const b = m.binding;
    return openModal('绑定微信 · ' + esc(m.bot_name), `<p class="mb">当前账号已绑定微信（${esc(b.ilink_user_id_masked)}）。状态：<b>${esc(b.status)}</b>${b.last_error ? ' · ' + esc(b.last_error) : ''}<br>绑定于 ${esc(b.bound_at)}${b.last_seen ? '，最近使用 ' + esc(b.last_seen) : ''}。</p>
      <p class="small mb">在微信里与「${esc(m.bot_name)}」对话即可（需手机已启用微信 ClawBot 插件）。发送「帮助」查看功能。</p>
      <button class="ghost" onclick="wechatUnbind()">解除绑定</button> <button class="secondary" onclick="wechatStartQr()">重新扫码换绑</button>`);
  }
  wechatStartQr();
}

async function wechatStartQr() {
  wxStopPoll();
  const s = await api('/api/wechat/qr', { method: 'POST' });
  wechatShowQr(s, false);
}

function wechatShowQr(s, isAdmin) {
  const pollUrl = isAdmin ? `/api/admin/wechat/qr/${s.id}` : `/api/wechat/qr/${s.id}`;
  const verifyUrl = isAdmin ? `/api/admin/wechat/qr/${s.id}/verify` : `/api/wechat/qr/${s.id}/verify`;
  openModal((isAdmin ? '管理员扫码绑定' : '绑定微信') + ' · 普惠Bot', `
    <div class="note-box mb">请用<strong>要绑定的微信</strong>扫描下方二维码（约 5 分钟有效）。一人一码：扫码的微信号 = 本工作台账号的专属「普惠Bot」通道。需手机微信已开启「微信ClawBot」插件。</div>
    <div id="wx_qr_box" style="text-align:center">${s.qr_png ? `<img src="${s.qr_png}" alt="QR" style="width:220px;height:220px;border:1px solid #ddd;border-radius:8px">` : '<p class="small">二维码加载中…</p>'}
      <p class="small mt" id="wx_qr_msg">${esc(s.message || s.status)}</p></div>
    <div id="wx_pair" style="display:${s.verify_needed ? 'block' : 'none'}" class="mb">
      <label>手机显示的配对码<input class="in" id="wx_code" placeholder="4~8 位数字" inputmode="numeric"></label>
      <button class="primary mini" id="wx_code_ok">提交配对码</button>
    </div>
    <button class="ghost" onclick="wxStopPoll();closeModal()">关闭</button>`);
  if ($('#wx_code_ok')) $('#wx_code_ok').onclick = async () => {
    const r = await api(verifyUrl, { method: 'POST', json: { code: $('#wx_code').value } });
    wechatShowQr(r, isAdmin);
  };
  wxStopPoll();
  WX_QR_TIMER = setInterval(async () => {
    try {
      const r = await api(pollUrl, { quiet: true });
      const box = $('#wx_qr_box');
      if (!box) { wxStopPoll(); return; }
      if (r.qr_png && r.status !== 'confirmed') {
        const img = box.querySelector('img');
        if (img && img.src !== r.qr_png) img.src = r.qr_png;
      }
      const msg = $('#wx_qr_msg'); if (msg) msg.textContent = r.message || r.status;
      const pair = $('#wx_pair'); if (pair) pair.style.display = r.verify_needed ? 'block' : 'none';
      if (r.status === 'confirmed') {
        wxStopPoll();
        openModal('绑定成功', `<div class="alert ok mb">微信已绑定到账号 <b>${esc(r.username)}</b>（${esc(r.result_user_id_masked || '')}）。</div>
          <p>打开微信，与「普惠Bot」对话，发送「帮助」或「额度」试一下。</p>
          <button class="primary" onclick="closeModal();route()">完成</button>`);
      } else if (['failed', 'expired', 'binded_elsewhere'].includes(r.status)) {
        wxStopPoll();
        const msg2 = $('#wx_qr_msg'); if (msg2) msg2.innerHTML = `<span style="color:var(--red)">${esc(r.message || r.status)}</span>`;
      }
    } catch (e) { /* ignore transient */ }
  }, 2000);
}

async function wechatUnbind() {
  if (!confirm('解除微信绑定？解绑后需重新扫码才能在微信使用。')) return;
  wxStopPoll();
  await api('/api/wechat/bind', { method: 'DELETE' });
  closeModal(); toast('已解除微信绑定');
}

/* ---------- 系统管理 ---------- */
async function admWechat(v, head) {
  const [c, b, ev] = await Promise.all([api('/api/admin/wechat/config'), api('/api/admin/wechat/bindings'), api('/api/admin/wechat/events?limit=80')]);
  const p = c.poller || {};
  const users = (await api('/api/admin/users').catch(() => ({ users: [] }))).users || [];
  v.innerHTML = head + `<div class="note-box mb">微信「<b>${esc(c.bot_name)}</b>」：每位用户在网页扫码，把<strong>自己的微信</strong>绑到<strong>自己的工作台账号</strong>（一人一通道，不能入群）。权限与飞书一致；数字来自数据库。已知限制（spike 实测）：每条提问最多回 <b>10</b> 条；须带 context_token（用户先发消息）；文件 ≤${c.max_file_mb}MB；会话失效（-14）需重新扫码。完整步骤见 <code>docs/wechat_setup.md</code>。</div>
  <div class="panel panel-b"><h2 class="mb">开关与限额</h2>
  <div class="form-row"><label>显示名称<input class="in" id="wx_name" value="${esc(c.bot_name)}"></label>
   <label>每人每分钟最多消息<input class="in" id="wx_rate" type="number" value="${c.rate_per_min}"></label>
   <label>每条提问最多回复<input class="in" id="wx_max" type="number" value="${c.max_replies}" max="10"></label>
   <label>文件上限 MB<input class="in" id="wx_mb" type="number" value="${c.max_file_mb}"></label></div>
  <div class="form-row"><label><span><input type="checkbox" id="wx_en" ${c.enabled ? 'checked' : ''}> 启用微信普惠Bot</span></label>
   <span class="small">轮询状态：${p.enabled ? (p.polling + ' 路运行中 / 正常绑定 ' + p.bindings_ok + (p.need_rebind ? ' · 需重绑 ' + p.need_rebind : '')) : '未启用'}</span></div>
  <button class="primary" onclick="admWechatSave()">保存</button></div>
  <div class="panel mt"><div class="panel-head"><div><h2>已绑定（${b.bindings.length}）</h2><p>用户自行扫码，或下方由管理员代为发起（扫码微信 → 指定账号）。</p></div>
    <div class="form-row" style="margin:0"><label>管理员代绑到账号<select class="in" id="wx_adm_u">${users.map(u => `<option value="${esc(u.username)}">${esc(u.username)}（${esc(u.display_name || '')}）</option>`).join('')}</select></label>
    <button class="secondary mini" onclick="admWechatQr()">生成二维码</button></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>账号</th><th>姓名/角色</th><th>微信用户</th><th>状态</th><th>绑定/最近</th><th></th></tr></thead><tbody>
   ${b.bindings.map(x => `<tr><td>${esc(x.username)}</td><td>${esc(x.display_name || '')}<br><small>${esc(x.role || '')} ${esc(x.org || '')}</small></td>
    <td class="small">${esc(x.ilink_user_id_masked)}</td><td><span class="pill ${x.status === '正常' ? 'green' : 'red'}">${esc(x.status)}</span>${x.last_error ? '<br><small>' + esc(x.last_error).slice(0, 40) + '</small>' : ''}</td>
    <td class="small">${esc(x.bound_at || '')}<br>${esc(x.last_seen || '')}</td>
    <td><a class="edit danger" onclick="admWechatUnbind(${x.id})">解绑</a></td></tr>`).join('') || '<tr><td colspan="6" class="small">暂无绑定</td></tr>'}</tbody></table></div></div>
  <div class="panel mt"><div class="panel-head"><div><h2>事件日志（最近 ${ev.length} 条）</h2></div></div>
   <div class="tbl-wrap"><table class="grid"><thead><tr><th>时间</th><th>账号</th><th>消息</th><th>意图</th><th>结果</th><th>回复摘要</th></tr></thead><tbody>
   ${ev.map(e => `<tr><td class="small">${esc(e.ts)}</td><td>${esc(e.username || '—')}</td><td class="l">${esc((e.text || '').slice(0, 50))}</td><td class="small">${esc(e.intent || '')}</td>
    <td><span class="pill ${e.status === '已处理' ? 'green' : ['未绑定','限流','拒绝'].includes(e.status) ? 'gold' : 'red'}">${esc(e.status)}</span></td>
    <td class="l small">${esc((e.reply || '').replace(/\\n/g,' ').slice(0, 70))}</td></tr>`).join('') || '<tr><td colspan="6" class="small">暂无事件</td></tr>'}</tbody></table></div></div>`;
}
async function admWechatSave() {
  await api('/api/admin/wechat/config', { method: 'PUT', json: { bot_name: $('#wx_name').value, rate_per_min: $('#wx_rate').value, max_replies: $('#wx_max').value, max_file_mb: $('#wx_mb').value, enabled: $('#wx_en').checked } });
  toast('已保存'); route();
}
async function admWechatUnbind(id) { if (!confirm('强制解除该微信绑定？')) return; await api('/api/admin/wechat/bindings/' + id, { method: 'DELETE' }); route(); }
async function admWechatQr() {
  const s = await api('/api/admin/wechat/qr', { method: 'POST', json: { username: $('#wx_adm_u').value } });
  wechatShowQr(s, true);
}
