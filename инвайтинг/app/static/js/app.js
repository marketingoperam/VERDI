const API = '/api/v1';
const THEME_KEY = 'inviting-theme';

const App = {
  data: { settings: null, status: null, accounts: [] },

  initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const theme = saved === 'light' || saved === 'dark' ? saved : 'dark';
    this.applyTheme(theme, false);
  },

  applyTheme(theme, save = true) {
    document.documentElement.setAttribute('data-theme', theme);
    document.getElementById('themeDark')?.classList.toggle('active', theme === 'dark');
    document.getElementById('themeLight')?.classList.toggle('active', theme === 'light');
    if (save) localStorage.setItem(THEME_KEY, theme);
  },

  setTheme(theme) {
    if (theme !== 'light' && theme !== 'dark') return;
    this.applyTheme(theme);
  },

  async init() {
    this.initTheme();
    this.bindNav();
    this.renderHelp();
    if (location.port === '8010') {
      this.toast('Старая панель на порту 8010. Откройте http://127.0.0.1:8011', 'error');
    }
    await this.refresh();
    setInterval(() => this.refresh(true), 15000);
  },

  bindNav() {
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(`page-${btn.dataset.page}`).classList.add('active');
        this.loadPage(btn.dataset.page);
      });
    });
  },

  loadPage(page) {
    if (page === 'targets') this.loadTargets();
    if (page === 'analytics') this.loadAnalytics();
    if (page === 'logs') this.loadLogs();
    if (page === 'accounts') this.loadAccounts();
    if (page === 'control') this.refresh();
  },

  toast(msg, type='info') {
    const el = document.createElement('div');
    el.className = 'toast ' + (type || 'info');
    el.textContent = msg;
    document.getElementById('toasts').appendChild(el);
    setTimeout(() => el.remove(), 4000);
  },

  async api(path, opts = {}) {
    let res;
    try {
      res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch (e) {
      throw new Error('Сервер не запущен (start.bat)');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      let msg = typeof err.detail === 'string' ? err.detail : (err.detail?.[0]?.msg || JSON.stringify(err.detail) || 'Ошибка');
      if (res.status === 404 && String(msg).toLowerCase() === 'not found' && location.port === '8010') {
        msg = 'Устаревшая панель (порт 8010). Откройте http://127.0.0.1:8011';
      }
      throw new Error(msg);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  async refresh(silent=false) {
    try {
      const [settings, status] = await Promise.all([
        this.api('/settings'),
        this.api('/status'),
      ]);
      this.data.settings = settings;
      this.data.status = status;
      this.updateStatus(status);
      this.renderCards(status);
      this.fillSettings(settings);
    } catch (e) {
      if (!silent) this.toast(e.message, 'error');
      this.setStatusDot('error', 'Ошибка');
    }
  },

  setStatusDot(kind, text) {
    const dot = document.getElementById('statusDot');
    const t = document.getElementById('statusText');
    dot.className = 'status-dot ' + (kind === 'ok' ? 'ok' : kind === 'degraded' ? 'degraded' : '');
    t.textContent = text;
  },

  updateStatus(s) {
    if (s.running && (!s.blockers || !s.blockers.length)) this.setStatusDot('ok', 'Запущен');
    else if (s.running && s.blockers?.length) this.setStatusDot('degraded', 'Запущен, есть блокеры');
    else if (s.configured) this.setStatusDot('degraded', 'Настроен, остановлен');
    else this.setStatusDot('error', 'Нужно настроить');

    document.getElementById('btnStart').disabled = !s.configured || s.running;
    document.getElementById('btnStop').disabled = !s.running;
    this.renderBlockers(s);
  },

  renderBlockers(s) {
    const panel = document.getElementById('blockersPanel');
    const list = document.getElementById('blockersList');
    if (!panel || !list) return;
    const blockers = s.blockers || [];
    if (!blockers.length) {
      panel.style.display = 'none';
      list.innerHTML = '';
      return;
    }
    panel.style.display = 'block';
    list.innerHTML = `<ul style="margin:0;padding-left:18px;line-height:1.6">
      ${blockers.map(b => `<li style="color:var(--danger)">${this.escape(b)}</li>`).join('')}
    </ul>
    <p class="hint" style="margin-top:10px">Авторизованные аккаунты: ${(s.session_files || []).length ?
      (s.session_files || []).map(f => `<code>${this.escape(f)}</code>`).join(' ') : 'нет'}</p>`;
  },

  renderCards(s) {
    const el = document.getElementById('cards');
    el.innerHTML = `
      <div class="card"><div class="card-label">Инвайт</div><div class="card-value">${s.running ? 'RUN' : 'STOP'}</div></div>
      <div class="card"><div class="card-label">Отписка</div><div class="card-value">${s.outreach_running ? 'RUN' : 'STOP'}</div><div class="hint">ready ${s.outreach_ready || 0}/${s.outreach_expected || 0}</div></div>
      <div class="card"><div class="card-label">Инвайтеры</div><div class="card-value">${s.sessions_ready}/${s.sessions_expected}</div></div>
      <div class="card"><div class="card-label">Инвайт сегодня</div><div class="card-value">${s.invited_today}/${s.daily_limit}</div></div>
      <div class="card"><div class="card-label">Очередь инвайта</div><div class="card-value">${s.queue_remaining}</div><div class="hint">всего: ${s.queue_total}</div></div>
      <div class="card"><div class="card-label">Отписка сегодня</div><div class="card-value">${s.outreach_sent_today || 0}</div><div class="hint">ждёт: ${s.outreach_pending || 0}</div></div>
    `;
  },

  fillSettings(s) {
    document.getElementById('s_chat_link').value = s.chat_link || '';
    document.getElementById('s_delay').value = s.min_delay_seconds ?? 45;
    document.getElementById('s_daily').value = s.daily_limit ?? 50;
    document.getElementById('s_inviters').value = (s.inviter_sessions || []).join(', ');
    document.getElementById('s_outreach_enabled').checked = !!s.outreach_enabled;
    document.getElementById('s_outreach_msg').value = s.outreach_message || '';
    document.getElementById('s_outreach_delay').value = s.outreach_delay_seconds ?? 60;
    document.getElementById('s_outreach_daily').value = s.outreach_daily_limit ?? 20;
    document.getElementById('s_outreach').value = (s.outreach_sessions || []).join(', ');
  },

  splitNames(raw) {
    return String(raw || '').split(',').map(s => s.trim()).filter(Boolean);
  },

  gatherSettings() {
    return {
      chat_link: document.getElementById('s_chat_link').value.trim(),
      min_delay_seconds: parseInt(document.getElementById('s_delay').value) || 0,
      daily_limit: parseInt(document.getElementById('s_daily').value) || 0,
      inviter_sessions: this.splitNames(document.getElementById('s_inviters').value),
      outreach_sessions: this.splitNames(document.getElementById('s_outreach').value),
      outreach_enabled: document.getElementById('s_outreach_enabled').checked,
      outreach_message: document.getElementById('s_outreach_msg').value,
      outreach_delay_seconds: parseInt(document.getElementById('s_outreach_delay').value) || 0,
      outreach_daily_limit: parseInt(document.getElementById('s_outreach_daily').value) || 0,
    };
  },

  async saveSettings() {
    try {
      await this.api('/settings', { method: 'PUT', body: this.gatherSettings() });
      this.toast('Сохранено', 'success');
      await this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async probeSessions() {
    try {
      const s = await this.api('/status');
      this.toast(
        `Инвайтеры ${s.sessions_ready}/${s.sessions_expected}, outreach ${s.outreach_ready}/${s.outreach_expected}`,
        (s.sessions_ready >= 1) ? 'success' : 'error'
      );
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async start() {
    try {
      await this.api('/run/start', { method: 'POST' });
      this.toast('Инвайт (+отписка если включена) запущен', 'success');
      await this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async stop() {
    try {
      await this.api('/run/stop', { method: 'POST' });
      this.toast('Остановлено', 'success');
      await this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async startOutreach() {
    try {
      await this.api('/outreach/start', { method: 'POST' });
      this.toast('Отписка запущена', 'success');
      await this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async stopOutreach() {
    try {
      await this.api('/outreach/stop', { method: 'POST' });
      this.toast('Отписка остановлена', 'success');
      await this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async loadAccounts() {
    try {
      const rows = await this.api('/accounts');
      this.data.accounts = rows;
      const el = document.getElementById('accountsList');
      if (!rows.length) {
        el.innerHTML = '<div class="hint">Пока нет аккаунтов. Создайте inviter и outreach отдельно.</div>';
        return;
      }
      el.innerHTML = rows.map(a => `
        <div class="panel" style="margin-bottom:12px" data-acc="${a.id}">
          <div class="panel-body" style="padding:14px">
            <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center">
              <div>
                <strong><code>${this.escape(a.name)}</code></strong>
                <span class="badge ${a.role === 'outreach' ? '' : 'success'}" style="margin-left:8px">${this.escape(a.role)}</span>
                ${a.is_authorized
                  ? '<span class="badge success">авторизован</span>'
                  : '<span class="badge error">нет входа</span>'}
                ${a.username ? `<span class="hint">@${this.escape(a.username)}</span>` : ''}
                ${a.phone ? `<span class="hint">${this.escape(a.phone)}</span>` : ''}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                <button class="btn btn-secondary btn-sm" onclick="App.logoutAccount(${a.id})">Выйти</button>
                <button class="btn btn-secondary btn-sm" onclick="App.deleteAccount(${a.id})">Удалить</button>
              </div>
            </div>
            ${a.is_authorized ? '' : `
              <div class="form-row" style="margin-top:12px">
                <div class="form-group">
                  <label>Телефон</label>
                  <input id="phone_${a.id}" placeholder="+7900..." value="${this.escape(a.phone || '')}" />
                </div>
                <div class="form-group" style="display:flex;align-items:flex-end">
                  <button class="btn btn-primary btn-sm" onclick="App.sendCode(${a.id})">Отправить код</button>
                </div>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Код из Telegram</label>
                  <input id="code_${a.id}" placeholder="12345" />
                </div>
                <div class="form-group" style="display:flex;align-items:flex-end">
                  <button class="btn btn-primary btn-sm" onclick="App.verifyCode(${a.id})">Подтвердить код</button>
                </div>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Пароль 2FA (если просят)</label>
                  <input id="pwd_${a.id}" type="password" placeholder="облачный пароль" />
                </div>
                <div class="form-group" style="display:flex;align-items:flex-end">
                  <button class="btn btn-secondary btn-sm" onclick="App.verifyPassword(${a.id})">Отправить 2FA</button>
                </div>
              </div>
            `}
            ${a.last_error ? `<p class="hint" style="color:var(--danger);margin-top:8px">${this.escape(a.last_error)}</p>` : ''}
          </div>
        </div>
      `).join('');
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async createAccount() {
    const name = document.getElementById('acc_name').value.trim();
    const role = document.getElementById('acc_role').value;
    if (!name) { this.toast('Укажите имя', 'error'); return; }
    try {
      await this.api('/accounts', { method: 'POST', body: { name, role } });
      document.getElementById('acc_name').value = '';
      this.toast('Аккаунт создан — войдите по коду', 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async deleteAccount(id) {
    if (!confirm('Удалить аккаунт?')) return;
    try {
      await this.api(`/accounts/${id}`, { method: 'DELETE' });
      this.toast('Удалён', 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async logoutAccount(id) {
    try {
      await this.api(`/accounts/${id}/logout`, { method: 'POST' });
      this.toast('Сессия сброшена', 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async sendCode(id) {
    const phone = document.getElementById(`phone_${id}`)?.value?.trim();
    if (!phone) { this.toast('Укажите телефон', 'error'); return; }
    try {
      const r = await this.api(`/accounts/${id}/auth/send-code`, { method: 'POST', body: { phone } });
      if (r.status === 'authorized') this.toast('Уже авторизован', 'success');
      else this.toast(`Код отправлен на ${r.phone}`, 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async verifyCode(id) {
    const code = document.getElementById(`code_${id}`)?.value?.trim();
    if (!code) { this.toast('Введите код', 'error'); return; }
    try {
      const r = await this.api(`/accounts/${id}/auth/verify-code`, { method: 'POST', body: { code } });
      if (r.status === 'need_password') this.toast('Нужен пароль 2FA', 'error');
      else this.toast(`Готово: @${r.username || r.phone}`, 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async verifyPassword(id) {
    const password = document.getElementById(`pwd_${id}`)?.value || '';
    if (!password) { this.toast('Введите пароль 2FA', 'error'); return; }
    try {
      const r = await this.api(`/accounts/${id}/auth/verify-password`, { method: 'POST', body: { password } });
      this.toast(`Готово: @${r.username || r.phone}`, 'success');
      await this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async uploadCsv() {
    const f = document.getElementById('csvFile')?.files?.[0];
    if (!f) { this.toast('Выберите файл CSV / XLS / XLSX', 'error'); return; }
    const form = new FormData();
    form.append('file', f);
    let res;
    try {
      res = await fetch(API + '/targets/import', { method: 'POST', body: form });
    } catch (e) {
      this.toast('Сервер не запущен', 'error'); return;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      this.toast(err.detail || 'Ошибка импорта', 'error');
      return;
    }
    const data = await res.json();
    this.toast(`Импорт: +${data.inserted}, дублей ${data.skipped_duplicates}, ошибок ${data.errors}` +
      (data.errors ? ' (некорректный username или пустая строка)' : ''), 'success');
    this.loadTargets();
    this.refresh(true);
  },

  statusBadges(r) {
    const parts = [];
    if (r.is_skipped) parts.push('<span class="badge error">skipped</span>');
    else if (r.is_invited) parts.push('<span class="badge success">invited</span>');
    else parts.push('<span class="badge">pending</span>');
    if (r.is_messaged) parts.push('<span class="badge success">dm</span>');
    else if (r.is_invited && !r.is_skipped) parts.push('<span class="badge">dm?</span>');
    return parts.join(' ');
  },

  async loadTargets() {
    try {
      const rows = await this.api('/targets?limit=500');
      const el = document.getElementById('targetsTable');
      if (!rows.length) {
        el.innerHTML = '<div class="hint">База пустая. Загрузите CSV / XLS / XLSX с реальными @username или user_id.</div>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>ID</th><th>Пользователь</th><th>Статус</th><th>Попыток</th><th>Ошибка</th><th></th>
      </tr></thead><tbody>
        ${rows.map(r => `<tr>
          <td>${r.id}</td>
          <td>${r.username ? `<code>@${this.escape(r.username)}</code>` : `<code>${r.user_id}</code>`}</td>
          <td>${this.statusBadges(r)}</td>
          <td>${r.attempts}</td>
          <td style="color:var(--muted)">${this.escape(r.outreach_error || r.last_error || '')}</td>
          <td><button class="btn btn-secondary btn-sm" onclick="App.skipTarget(${r.id})">Пропустить</button>
              <button class="btn btn-secondary btn-sm" onclick="App.deleteTarget(${r.id})">Удалить</button></td>
        </tr>`).join('')}
      </tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async skipTarget(id) {
    try {
      await this.api('/targets/' + id + '/skip', { method: 'POST' });
      this.toast('Пропущен', 'success');
      this.loadTargets();
      this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async deleteTarget(id) {
    try {
      await this.api('/targets/' + id, { method: 'DELETE' });
      this.toast('Удалено', 'success');
      this.loadTargets();
      this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async resetTargets() {
    try {
      await this.api('/targets/reset', { method: 'POST' });
      this.toast('Статусы сброшены', 'success');
      this.loadTargets();
      this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async resetOutreach() {
    try {
      await this.api('/targets/reset-outreach', { method: 'POST' });
      this.toast('Статусы отписки сброшены', 'success');
      this.loadTargets();
      this.refresh(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  renderAnalyticsCards(data) {
    const el = document.getElementById('analyticsCards');
    if (!el) return;
    const chatLabel = data.mirror_username ? `@${data.mirror_username}` : 'чат';
    const reach = data.shadowchat_reachable
      ? `<span class="badge success">ShadowChat OK</span>`
      : `<span class="badge error">ShadowChat недоступен</span>`;
    el.innerHTML = `
      <div class="card"><div class="card-label">Приглашено</div><div class="card-value">${data.invited_total}</div></div>
      <div class="card"><div class="card-label">С активностью</div><div class="card-value success">${data.with_activity}</div></div>
      <div class="card"><div class="card-label">Сообщений</div><div class="card-value">${data.messages_total}</div></div>
      <div class="card"><div class="card-label">Реакций</div><div class="card-value">${data.reactions_total}</div></div>
      <div class="card"><div class="card-label">Чат</div><div class="card-value" style="font-size:1rem">${chatLabel} ${reach}</div></div>
    `;
  },

  async loadAnalytics(silent = false) {
    const el = document.getElementById('analyticsTable');
    if (!el) return;
    const sort = document.getElementById('analyticsSort')?.value || 'total';
    try {
      const data = await this.api(`/analytics/invited?sort=${encodeURIComponent(sort)}`);
      this.renderAnalyticsCards(data);
      if (!data.items.length) {
        el.innerHTML = `<div class="hint">Нет приглашённых пользователей или ShadowChat ещё не собрал активность.<br>
          Запустите <code>shadowchat/start.bat</code> и нажмите «Сканировать историю».</div>`;
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Пользователь</th><th>Инвайт</th><th>Отписка</th><th>Сообщения</th><th>Реакции</th><th>Всего</th><th>Последняя активность</th>
      </tr></thead><tbody>
        ${data.items.map(r => `<tr>
          <td>${r.username ? `<code>@${this.escape(r.username)}</code>` : `<code>${r.user_id || '—'}</code>`}</td>
          <td style="color:var(--muted)">${this.dt(r.invited_at)}</td>
          <td>${r.is_messaged ? '<span class="badge success">dm</span>' : '<span class="badge">—</span>'}</td>
          <td><span class="badge">${r.message_count}</span></td>
          <td><span class="badge">${r.reaction_count}</span></td>
          <td><strong>${r.total_count}</strong></td>
          <td style="color:var(--muted)">${r.last_active_at ? this.dt(r.last_active_at) : (r.has_activity ? '—' : '<span style="opacity:.6">нет в чате</span>')}</td>
        </tr>`).join('')}
      </tbody></table>`;
    } catch (e) {
      if (!silent) this.toast(e.message, 'error');
    }
  },

  async backfillAnalytics() {
    try {
      this.toast('Сканирование истории чата…', 'info');
      const result = await this.api('/analytics/backfill', { method: 'POST' });
      const recorded = result.recorded ?? result.chats ?? '—';
      this.toast(`Готово: ${recorded} событий обработано`, 'success');
      await this.loadAnalytics(true);
    } catch (e) { this.toast(e.message, 'error'); }
  },

  badgeStatus(status) {
    if (status === 'success' || status === 'outreach_ok') return `<span class="badge success">${this.escape(status)}</span>`;
    return `<span class="badge error">${this.escape(status)}</span>`;
  },

  async loadLogs() {
    try {
      const rows = await this.api('/logs?limit=200');
      const el = document.getElementById('logsTable');
      if (!rows.length) {
        el.innerHTML = '<div class="hint">Журнал пуст.</div>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Время</th><th>Аккаунт</th><th>Цель</th><th>Статус</th><th>Ошибка</th>
      </tr></thead><tbody>
        ${rows.map(r => `<tr>
          <td style="color:var(--muted)">${this.dt(r.created_at)}</td>
          <td><code>${this.escape(r.inviter_session)}</code></td>
          <td><code>${this.escape(r.target_label)}</code></td>
          <td>${this.badgeStatus(r.status)}</td>
          <td style="color:var(--muted)">${this.escape(r.error_text || '')}</td>
        </tr>`).join('')}
      </tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  renderHelp() {
    document.getElementById('help').innerHTML = `
      <div style="line-height:1.55">
        <p><strong>1)</strong> Запустите <code>инвайтинг/start.bat</code></p>
        <p><strong>2)</strong> В <code>.env</code>: <code>INV_TG_API_ID</code> и <code>INV_TG_API_HASH</code></p>
        <p><strong>3)</strong> Вкладка <strong>Аккаунты</strong>: создайте отдельно <code>inviter</code> и <code>outreach</code>, войдите по телефону + коду (файлы .session больше не нужны)</p>
        <p><strong>4)</strong> В «Управление»: укажите ссылку, списки имён аккаунтов (разные пулы), текст отписки, загрузите базу юзернеймов</p>
        <p><strong>5)</strong> «Старт» — инвайт; если отписка включена, она тоже стартует. Можно отдельно «Старт отписки»</p>
        <p><strong>6)</strong> Отписка автоматически попадает в <a href="https://verdi-connector-web.onrender.com/inbox" target="_blank" rel="noopener">Operator Inbox</a> (нужны <code>INV_CONNECTOR_API_URL</code> + <code>INV_CONNECTOR_SYNC_SECRET</code> в <code>.env</code>)</p>
        <p><strong>7)</strong> Вкладка <strong>Аналитика</strong> — активность приглашённых в <code>@verdi114</code> (нужен запущенный ShadowChat на <code>8001</code>)</p>
        <hr style="border:0;border-top:1px solid var(--border);margin:16px 0" />
        <p><strong>Важно:</strong> один аккаунт не должен быть одновременно инвайтером и отписчиком. Не используйте ту же сессию на Render/ShadowChat.</p>
        <p><strong>Очередь отписки:</strong> пишем только тем, у кого уже <code>invited</code> и ещё нет <code>dm</code>.</p>
      </div>
    `;
  },

  escape(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  dt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
