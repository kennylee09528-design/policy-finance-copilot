/* 发送到邮箱（M3 研究报告 / M2 简报 / PPT）+ 系统管理 · 邮件发送(SMTP) */
const MAIL = { kind: '', ref: 0, subject: '', to: '', message: '', ppt: '' };
async function mailDialog(kind, ref) {
  const o = await api('/api/mail/options');
  if (!o.can_send) return toast('仅普惠部内部用户可发送邮件');
  if (!o.enabled) return openModal('发送到邮箱', '<div class="alert warn">邮件发送尚未启用：请系统管理员在「系统管理 → 邮件发送」中配置 SMTP、设置<b>允许的收件邮箱域名</b>并启用。</div><button class="secondary" onclick="closeModal()">知道了</button>');
  const p = await api('/api/mail/preview', { method: 'POST', json: { kind, ref } });
  Object.assign(MAIL, { kind, ref, subject: p.subject, to: '', message: '', ppt: '' });
  openModal('发送到邮箱 · ' + p.kind_name, `<div class="note-box mb">内部资料 注意保密：只能发送到管理员允许的邮箱域名（<b>${esc(o.allowed_domains.join('、') || '尚未设置，暂不能发送')}</b>）；附件带「内部资料 注意保密」水印与发送人信息；发送记录可追溯。</div>
  <p class="small mb">文档：${esc(p.title)}（${esc(p.version)}）</p>
  <label>收件人（多个用逗号 / 分号分隔，最多 ${o.max_recipients} 个）<input class="in" id="ml_to" placeholder="name@${esc(o.allowed_domains[0] || 'company.com')}"></label>
  <label>主题<input class="in" id="ml_sub" value="${esc(p.subject)}"></label>
  <label>留言<textarea class="in" id="ml_msg" rows="3" placeholder="可选：写给收件人的说明"></textarea></label>
  <p class="small">附件：${p.attachments.map(a => esc(a.name)).join('、')}（带水印 Word）</p>
  ${p.ppt_options.length ? `<label>同时附带配套 PPT（可选）<select class="in" id="ml_ppt"><option value="">不附带</option>${p.ppt_options.map(x => `<option value="${x.id}">${esc(x.label)}</option>`).join('')}</select></label>` : ''}
  ${p.warnings.map(w => `<div class="alert warn mb">${esc(w)}</div>`).join('')}
  <button class="primary" id="ml_next">下一步：确认收件人</button> <button class="ghost" onclick="closeModal()">取消</button>`);
  $('#ml_next').onclick = () => {
    Object.assign(MAIL, { to: $('#ml_to').value, subject: $('#ml_sub').value, message: $('#ml_msg').value, ppt: $('#ml_ppt') ? $('#ml_ppt').value : '' });
    mailConfirm();
  };
}
async function mailConfirm() {
  const opts = MAIL.ppt ? { ppt_file_id: +MAIL.ppt } : {};
  const p = await api('/api/mail/preview', { method: 'POST', json: { kind: MAIL.kind, ref: MAIL.ref, to: MAIL.to, opts } });
  const bad = p.recipient_error || !p.recipients.length;
  openModal('确认发送', `${bad ? `<div class="alert error mb">${esc(p.recipient_error || '请填写收件人')}</div>` : ''}
  <table class="grid mb"><tbody><tr><th>发件人</th><td class="l">${esc(p.sender)}</td></tr>
  <tr><th>收件人（${p.recipients.length}）</th><td class="l"><b>${p.recipients.map(esc).join('<br>')}</b></td></tr>
  <tr><th>主题</th><td class="l">${esc(MAIL.subject)}</td></tr>
  <tr><th>文档</th><td class="l">${esc(p.kind_name)}《${esc(p.title)}》· ${esc(p.version)}</td></tr>
  <tr><th>附件</th><td class="l">${p.attachments.map(a => esc(a.name) + '（' + (a.size / 1024).toFixed(0) + ' KB）').join('<br>')}</td></tr></tbody></table>
  ${p.sensitive ? `<label class="alert warn mb" style="display:block"><input type="checkbox" id="ml_sens"> 我确认：该文档含 M5 机构业务数据（敏感），收件人有权查阅，可以发送</label>` : ''}
  <div class="alert warn mb">发送后无法撤回。请再次核对收件人。</div>
  <button class="primary" id="ml_go" ${bad || !p.smtp_ready ? 'disabled' : ''}>确认发送</button> <button class="ghost" onclick="mailDialogBack()">返回修改</button>`);
  $('#ml_go').onclick = async () => {
    $('#ml_go').disabled = true;
    try {
      const r = await api('/api/mail/send', { method: 'POST', json: { kind: MAIL.kind, ref: MAIL.ref, to: MAIL.to, subject: MAIL.subject, message: MAIL.message, opts, confirm: true, confirm_sensitive: $('#ml_sens') ? $('#ml_sens').checked : false } });
      closeModal(); toast('已发送至 ' + r.to.join('、'), 5000);
    } catch (e) { $('#ml_go').disabled = false; }
  };
}
function mailDialogBack() { mailDialog(MAIL.kind, MAIL.ref).then(() => { $('#ml_to').value = MAIL.to; $('#ml_sub').value = MAIL.subject; $('#ml_msg').value = MAIL.message; }); }
const mailBtn = (kind, ref) => `<button class="secondary mini" onclick="mailDialog('${kind}',${ref})">发送到邮箱</button>`;

/* ---------- 系统管理 · 邮件发送 ---------- */
async function admMail(v, head) {
  const c = await api('/api/admin/mail/config');
  const t = c.last_test;
  v.innerHTML = head + `<div class="note-box mb">用于把 <b>已定稿的 M3 研究报告</b>（以及已发布的 M2 简报、PPT）发送到收件人邮箱，也供飞书机器人调用。内容属于内部资料：<b>必须先设置「允许的收件邮箱域名」</b>，否则一律不能发送；SMTP 密码加密存储，页面不回显。</div>
  <div class="panel panel-b"><h2 class="mb">SMTP 设置</h2>
  <div class="form-row"><label style="flex:2">SMTP 服务器<input class="in" id="sm_host" value="${esc(c.host)}" placeholder="如 smtp.exmail.qq.com / smtp.qiye.aliyun.com / smtp.163.com"></label>
  <label>端口<input class="in" id="sm_port" type="number" value="${c.port}"></label>
  <label>加密方式<select class="in" id="sm_sec"><option value="ssl" ${c.security === 'ssl' ? 'selected' : ''}>SSL（465）</option><option value="starttls" ${c.security === 'starttls' ? 'selected' : ''}>STARTTLS（587）</option><option value="none" ${c.security === 'none' ? 'selected' : ''}>不加密（仅内网）</option></select></label></div>
  <div class="form-row"><label style="flex:1">登录账号<input class="in" id="sm_user" value="${esc(c.username)}" autocomplete="off"></label>
  <label style="flex:1">密码 / 授权码 ${c.has_password ? '（已设置；留空表示不修改）' : ''}<input class="in" id="sm_pw" type="password" autocomplete="new-password" placeholder="${c.has_password ? '留空不修改' : '邮箱密码或客户端授权码'}"></label></div>
  <div class="form-row"><label style="flex:1">发件人名称<input class="in" id="sm_sn" value="${esc(c.sender_name)}"></label><label style="flex:1">发件人地址<input class="in" id="sm_sa" value="${esc(c.sender_addr)}" placeholder="bot@company.com"></label></div>
  <div class="form-row"><label style="flex:1"><b>允许的收件邮箱域名白名单</b>（逗号/空格分隔；<code>*.corp.com</code> 含子域；为空 = 全部禁止）<input class="in" id="sm_dom" value="${esc(c.allowed_domains.join(', '))}" placeholder="如 example.com, corp.com"></label></div>
  <div class="form-row"><label>单封最多收件人<input class="in" id="sm_mr" type="number" value="${c.max_recipients}"></label><label>每人每小时最多封数<input class="in" id="sm_hl" type="number" value="${c.hourly_limit}"></label><label>附件合计上限（MB）<input class="in" id="sm_mb" type="number" value="${c.max_attach_mb}"></label>
  <label><span><input type="checkbox" id="sm_en" ${c.enabled ? 'checked' : ''}> 启用邮件发送</span></label></div>
  <button class="primary" onclick="admMailSave()">保存</button></div>
  <div class="panel panel-b mt"><h2 class="mb">测试发送</h2><div class="form-row"><label style="flex:1">测试收件邮箱<input class="in" id="sm_to" placeholder="填你自己的邮箱"></label><button class="secondary" onclick="admMailTest()">发送测试邮件</button></div>
  <p class="small">${t ? `最近测试：${esc(t.at)} → ${esc(t.to)}：${t.ok ? '<span class="pill green">成功</span>' : '<span class="pill red">失败</span> ' + esc(t.error || '')}` : '尚未测试。请先保存设置，再发送测试邮件。'}</p></div>`;
}
async function admMailSave() {
  const body = { host: $('#sm_host').value, port: +$('#sm_port').value, security: $('#sm_sec').value, username: $('#sm_user').value, password: $('#sm_pw').value || null, sender_name: $('#sm_sn').value, sender_addr: $('#sm_sa').value,
    allowed_domains: $('#sm_dom').value, max_recipients: $('#sm_mr').value, hourly_limit: $('#sm_hl').value, max_attach_mb: $('#sm_mb').value, enabled: $('#sm_en').checked };
  await api('/api/admin/mail/config', { method: 'PUT', json: body }); toast('已保存'); route();
}
async function admMailTest() {
  toast('发送中…', 15000);
  const r = await api('/api/admin/mail/test', { method: 'POST', json: { to: $('#sm_to').value } });
  toast(r.ok ? '测试邮件已发出，请到邮箱查收' : '⚠ 失败：' + (r.error || ''), 6000); route();
}

/* ---------- 操作留痕 · 邮件发送记录 ---------- */
async function auditMails(v, head) {
  const rows = await api('/api/mail/log' + recQ('mail'));
  v.innerHTML = head + `<div class="panel"><div class="panel-head"><div><h2>邮件发送记录（${rows.length}）</h2><p>谁、发给谁、何时、结果、附件与文档版本。${ME.role === 'admin' ? '管理员可见全部。' : '仅显示本人发送的记录。'}归档/删除只影响历史记录，不影响已发出的邮件。</p></div>${recTabs('mail')}</div>
  <div class="tbl-wrap"><table class="grid"><thead><tr><th></th><th>时间</th><th>发送人</th><th>渠道</th><th>文档</th><th>收件人</th><th>主题</th><th>附件 / 版本</th><th>结果</th><th></th></tr></thead><tbody>
  ${rows.map(r => `<tr><td>${recCb('mail', r)}</td><td class="small">${esc(r.ts)}</td><td>${esc(r.user)}</td><td>${esc(r.channel)}</td><td class="l">${esc(r.kind_name)} #${r.ref_id}<br><small>${esc(r.ref_title || '')}</small></td><td class="l">${esc(r.to_addrs)}</td><td class="l">${esc(r.subject)}</td>
   <td class="l small">${r.attachments.map(a => esc(a.name)).join('<br>')}<br>${esc(r.doc_version || '')}${r.sensitive_confirmed ? '<br><span class="pill gold">已确认涉密发送</span>' : ''}</td>
   <td>${r.status === '已发送' ? '<span class="pill green">已发送</span>' : `<span class="pill red" title="${esc(r.error || '')}">失败</span>`}</td><td>${recBtns('mail', r)} ${recBadge(r)}</td></tr>`).join('') || '<tr><td colspan="10" class="small">暂无邮件发送记录</td></tr>'}</tbody></table></div></div>`;
}
