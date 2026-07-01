const API = '/api/v1';

const App = {
  data: { settings: null, employees: [], sessions: [] },

  async init() {
    this.bindNav();
    this.renderHelp();
    try {
      await this.refreshDashboard();
      this.startAutoRefresh();
    } catch (e) {
      this.showBanner('Не удалось загрузить данные: ' + e.message, 'error');
    }
  },

  showBanner(msg, type = 'info') {
    let b = document.getElementById('topBanner');
    if (!b) {
      b = document.createElement('div');
      b.id = 'topBanner';
      b.style.cssText = 'padding:12px 20px;margin-bottom:16px;border-radius:8px;font-size:.9rem';
      document.querySelector('.main')?.prepend(b);
    }
    const colors = { error: '#331a14', info: '#142233', success: '#0d3328' };
    const borders = { error: '#e17055', info: '#74b9ff', success: '#00b894' };
    b.style.background = colors[type] || colors.info;
    b.style.border = '1px solid ' + (borders[type] || borders.info);
    b.textContent = msg;
  },

  bindNav() {
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const page = btn.dataset.page;
        document.getElementById(`page-${page}`).classList.add('active');
        this.loadPage(page);
      });
    });
  },

  loadPage(page) {
    const loaders = {
      dashboard: () => this.refreshDashboard(),
      chats: () => this.loadChats(),
      accounts: () => this.loadAccounts(),
      employees: () => this.loadEmployees(),
      logs: () => this.loadLogs(),
      settings: () => this.loadSettings(),
    };
    loaders[page]?.();
  },

  startAutoRefresh() {
    setInterval(() => {
      const active = document.querySelector('.page.active');
      if (active?.id === 'page-dashboard') this.refreshDashboard(true);
    }, 30000);
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
      throw new Error('Сервер не запущен. Запустите start.bat');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Ошибка запроса');
    }
    if (res.status === 204) return null;
    return res.json();
  },

  async upload(path, formData) {
    let res;
    try {
      res = await fetch(API + path, { method: 'POST', body: formData });
    } catch (e) {
      throw new Error('Сервер не запущен. Запустите start.bat');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Ошибка загрузки');
    }
    return res.json();
  },

  toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    document.getElementById('toasts').appendChild(el);
    setTimeout(() => el.remove(), 4000);
  },

  formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  },

  statusBadge(ok) {
    return ok
      ? '<span class="badge badge-success">Активен</span>'
      : '<span class="badge badge-muted">Выключен</span>';
  },

  /* ── Dashboard ── */
  async refreshDashboard(silent = false) {
    try {
      const dash = await this.api('/dashboard');
      this.updateStatus(dash.health);
      this.renderDashCards(dash.stats);
      this.renderSetup(dash.setup);
      this.renderRecentLogs(dash.recent_logs);
    } catch (e) {
      if (!silent) this.toast(e.message, 'error');
      this.updateStatus({ status: 'error', listener: 'error' });
    }
  },

  updateStatus(health) {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    dot.className = 'status-dot ' + (health.status === 'ok' ? '' : health.status === 'degraded' ? 'degraded' : 'error');
    const labels = { ok: 'Система работает', degraded: 'Частичная работа', error: 'Ошибка' };
    text.textContent = labels[health.status] || health.status;
  },

  renderDashCards(s) {
    document.getElementById('dashCards').innerHTML = `
      <div class="card"><div class="card-label">Активных пар</div><div class="card-value">${s.active_pairs}</div></div>
      <div class="card"><div class="card-label">Сообщений сегодня</div><div class="card-value success">${s.messages_mirrored_today}</div></div>
      <div class="card"><div class="card-label">Ошибок сегодня</div><div class="card-value ${s.errors_today ? 'danger' : ''}">${s.errors_today}</div></div>
      <div class="card"><div class="card-label">Сотрудников</div><div class="card-value">${s.employees}</div></div>
      <div class="card"><div class="card-label">Аккаунтов</div><div class="card-value">${s.sessions_assigned}/${s.sessions}</div></div>
    `;
  },

  renderSetup(setup) {
    document.getElementById('setupPercent').textContent = setup.progress_percent + '%';
    document.getElementById('setupProgress').style.width = setup.progress_percent + '%';
    document.getElementById('setupSteps').innerHTML = setup.steps.map(s => `
      <li class="setup-step">
        <div class="step-check ${s.done ? 'done' : ''}">${s.done ? '✓' : ''}</div>
        <div class="step-content">
          <h4>${s.title}</h4>
          <p>${s.description}</p>
        </div>
        ${!s.done && s.action ? `<button class="btn btn-secondary btn-sm" onclick="App.goTo('${s.action}')">Настроить</button>` : ''}
      </li>
    `).join('');
  },

  renderRecentLogs(logs) {
    const el = document.getElementById('recentLogs');
    if (!logs.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📭</div><h4>Пока нет событий</h4><p>Добавьте пару чатов — сообщения появятся здесь</p></div>';
      return;
    }
    el.innerHTML = `<table><thead><tr><th>Время</th><th>Событие</th><th>Статус</th><th>Детали</th></tr></thead><tbody>
      ${logs.map(l => `<tr class="${l.status === 'error' ? 'log-row error' : ''}">
        <td>${this.formatDate(l.created_at)}</td>
        <td>${this.eventLabel(l.event_type)}</td>
        <td>${this.logStatusBadge(l.status)}</td>
        <td style="color:var(--text-muted);font-size:.8rem">${l.error_text || `msg #${l.source_message_id || '—'}`}</td>
      </tr>`).join('')}
    </tbody></table>`;
  },

  eventLabel(t) {
    return { new_message: 'Новое сообщение', edit: 'Редактирование', delete: 'Удаление' }[t] || t;
  },

  logStatusBadge(s) {
    const m = { success: 'badge-success', error: 'badge-danger', skipped: 'badge-muted', partial: 'badge-warning', not_found: 'badge-muted' };
    const l = { success: 'OK', error: 'Ошибка', skipped: 'Пропущено', partial: 'Частично', not_found: 'Не найдено' };
    return `<span class="badge ${m[s] || 'badge-muted'}">${l[s] || s}</span>`;
  },

  goTo(action) {
    const map = { chats: 'chats', accounts: 'accounts', 'help-api': 'help', 'help-listener': 'help' };
    const page = map[action] || action;
    document.querySelector(`[data-page="${page}"]`)?.click();
  },

  /* ── Chats ── */
  async loadChats() {
    try {
      const pairs = await this.api('/chat-pairs');
      const el = document.getElementById('chatsTable');
      if (!pairs.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">💬</div><h4>Нет пар чатов</h4><p>Нажмите «Добавить пару чатов» чтобы начать зеркалирование</p></div>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Название</th><th>Исходный ID</th><th>Зеркало ID</th><th>Режим</th><th>Статус</th><th></th>
      </tr></thead><tbody>${pairs.map(p => `<tr>
        <td><strong>${p.source_title}</strong></td>
        <td><code>${p.source_telegram_chat_id}</code></td>
        <td><code>${p.mirror_telegram_chat_id}</code></td>
        <td>${p.mirror_mode === 'safe' ? '<span class="badge badge-info">Безопасный</span>' : '<span class="badge badge-warning">Профили</span>'}</td>
        <td>${this.statusBadge(p.source_is_active && p.mirror_is_active)}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="App.toggleChatPair(${p.source_id}, ${p.mirror_id}, ${p.source_is_active})">
          ${p.source_is_active ? 'Выключить' : 'Включить'}
        </button></td>
      </tr>`).join('')}</tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async toggleChatPair(sourceId, mirrorId, isActive) {
    try {
      await this.api(`/source-chats/${sourceId}`, { method: 'PUT', body: { is_active: !isActive } });
      await this.api(`/mirror-chats/${mirrorId}`, { method: 'PUT', body: { is_active: !isActive } });
      this.toast(isActive ? 'Пара выключена' : 'Пара включена', 'success');
      this.loadChats();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  /* ── Accounts ── */
  async loadAccounts() {
    try {
      const sessions = await this.api('/sessions');
      this.data.sessions = sessions;

      const el = document.getElementById('accountsTable');
      if (!sessions.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">👤</div><h4>Нет аккаунтов</h4><p>Добавьте технический аккаунт, войдите в него и пригласите в зеркальный чат.</p></div>';
        return;
      }

      el.innerHTML = `<table><thead><tr>
        <th>Имя</th><th>Вход</th><th>Закреплён за</th><th>Статус</th><th></th>
      </tr></thead><tbody>${sessions.map(s => `<tr>
        <td><strong>${s.session_name}</strong></td>
        <td>${s.is_authorized
          ? '<span class="badge badge-success">Вошёл</span>'
          : '<span class="badge badge-warning">Нужен вход</span>'}</td>
        <td>${s.employee_name
          ? `${s.employee_name} <span style="color:var(--text-muted)">(авто)</span>`
          : '<span class="badge badge-info">Свободен</span>'}</td>
        <td>${this.statusBadge(s.is_active)}</td>
        <td>
          ${!s.is_authorized ? `<button class="btn btn-primary btn-sm" onclick='App.openAuthModal(${s.id}, ${JSON.stringify(s.session_name)})'>Войти</button>` : ''}
          <button class="btn btn-secondary btn-sm" onclick="App.toggleSession(${s.id}, ${!s.is_active})">
            ${s.is_active ? 'Выключить' : 'Включить'}
          </button>
        </td>
      </tr>`).join('')}</tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  authState: { sessionId: null, sessionName: '', step: 'phone' },

  async openAuthModal(sessionId, sessionName) {
    this.authState = { sessionId, sessionName, step: 'phone' };
    const overlay = document.getElementById('modalOverlay');
    document.getElementById('modalTitle').textContent = `Вход: ${sessionName}`;
    await this.renderAuthStep();
    overlay.classList.add('open');
  },

  async renderAuthStep() {
    const body = document.getElementById('modalBody');
    const footer = document.getElementById('modalFooter');
    const { sessionId, step } = this.authState;

    let status = { api_id: '', api_hash: '' };
    try {
      status = await this.api(`/sessions/${sessionId}/auth/status`);
    } catch (e) { /* ignore */ }

    if (status.status === 'authorized') {
      body.innerHTML = `<div class="empty-state" style="padding:24px">
        <div class="icon">✅</div>
        <h4>Аккаунт подключён</h4>
        <p>${status.first_name || ''} ${status.username ? '@' + status.username : ''}</p>
        <p style="color:var(--text-muted)">${status.phone || ''}</p>
      </div>`;
      footer.innerHTML = `<button class="btn btn-primary" onclick="App.closeModal();App.loadAccounts()">Готово</button>`;
      return;
    }

    if (step === 'phone' || status.status === 'need_phone') {
      body.innerHTML = `
        <p style="color:var(--text-muted);margin-bottom:16px;font-size:.9rem">
          Получите API ID и API Hash на <strong>my.telegram.org</strong> → API development tools
        </p>
        <div class="form-row">
          <div class="form-group">
            <label>API ID</label>
            <input id="auth_api_id" type="number" placeholder="12345678" value="${status.api_id || ''}">
          </div>
          <div class="form-group">
            <label>API Hash</label>
            <input id="auth_api_hash" placeholder="abcdef1234..." value="${status.api_hash || ''}">
          </div>
        </div>
        <div class="form-group">
          <label>Номер телефона</label>
          <input id="auth_phone" type="tel" placeholder="+79001234567">
          <p class="hint">В международном формате, с кодом страны</p>
        </div>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.closeModal()">Отмена</button>
        <button class="btn btn-primary" onclick="App.authSendCode()">Получить код</button>
      `;
      return;
    }

    if (step === 'code' || status.status === 'code_sent') {
      body.innerHTML = `
        <p style="margin-bottom:16px">Код отправлен на <strong>${status.phone || ''}</strong></p>
        <div class="form-group">
          <label>Код из Telegram</label>
          <input id="auth_code" placeholder="12345" autocomplete="one-time-code">
        </div>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.authState.step='phone';App.renderAuthStep()">Назад</button>
        <button class="btn btn-primary" onclick="App.authVerifyCode()">Войти</button>
      `;
      return;
    }

    if (step === 'password' || status.status === 'need_password') {
      body.innerHTML = `
        <p style="margin-bottom:16px">У аккаунта включена двухфакторная защита</p>
        <div class="form-group">
          <label>Пароль 2FA</label>
          <input id="auth_password" type="password" placeholder="Пароль">
        </div>
      `;
      footer.innerHTML = `
        <button class="btn btn-primary" onclick="App.authVerifyPassword()">Подтвердить</button>
      `;
    }
  },

  async authSendCode() {
    const { sessionId } = this.authState;
    const phone = document.getElementById('auth_phone').value.trim();
    const api_id = parseInt(document.getElementById('auth_api_id').value);
    const api_hash = document.getElementById('auth_api_hash').value.trim();

    if (!phone || !api_id || !api_hash) {
      this.toast('Заполните API ID, API Hash и номер телефона', 'error');
      return;
    }

    try {
      const res = await this.api(`/sessions/${sessionId}/auth/send-code`, {
        method: 'POST',
        body: { phone, api_id, api_hash },
      });
      this.authState.step = res.status === 'authorized' ? 'done' : 'code';
      if (res.status === 'authorized') {
        this.toast('Аккаунт уже авторизован', 'success');
      } else {
        this.toast('Код отправлен в Telegram', 'success');
      }
      await this.renderAuthStep();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async authVerifyCode() {
    const { sessionId } = this.authState;
    const code = document.getElementById('auth_code').value.trim();
    if (!code) { this.toast('Введите код', 'error'); return; }

    try {
      const res = await this.api(`/sessions/${sessionId}/auth/verify-code`, {
        method: 'POST',
        body: { code },
      });
      if (res.status === 'need_password') {
        this.authState.step = 'password';
        this.toast('Введите пароль 2FA', 'info');
      } else {
        this.toast(`Вход выполнен: ${res.first_name || 'OK'}`, 'success');
      }
      await this.renderAuthStep();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async authVerifyPassword() {
    const { sessionId } = this.authState;
    const password = document.getElementById('auth_password').value;
    if (!password) { this.toast('Введите пароль', 'error'); return; }

    try {
      const res = await this.api(`/sessions/${sessionId}/auth/verify-password`, {
        method: 'POST',
        body: { password },
      });
      this.toast(`Вход выполнен: ${res.first_name || 'OK'}`, 'success');
      await this.renderAuthStep();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async toggleSession(id, isActive) {
    try {
      await this.api(`/sessions/${id}`, { method: 'PUT', body: { is_active: isActive } });
      this.toast(isActive ? 'Аккаунт включён' : 'Аккаунт выключен', 'success');
      this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  /* ── Employees ── */
  async loadEmployees() {
    try {
      const employees = await this.api('/employees');
      const el = document.getElementById('employeesTable');
      if (!employees.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">👥</div><h4>Нет сотрудников</h4><p>Сотрудники появятся автоматически, когда напишут в исходном чате</p></div>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>Имя</th><th>Telegram ID</th><th>Username</th><th>Согласие</th><th>Игнор</th><th></th>
      </tr></thead><tbody>${employees.map(e => `<tr>
        <td><strong>${e.first_name} ${e.last_name || ''}</strong></td>
        <td><code>${e.telegram_user_id}</code></td>
        <td>${e.username ? '@' + e.username : '—'}</td>
        <td>${e.consent_signed ? '<span class="badge badge-success">Да</span>' : '<span class="badge badge-warning">Нет</span>'}</td>
        <td>${e.is_muted ? '<span class="badge badge-danger">Да</span>' : '—'}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="App.toggleEmployee(${e.id}, 'consent_signed', ${!e.consent_signed})">
            ${e.consent_signed ? 'Снять согласие' : 'Согласие ✓'}
          </button>
          <button class="btn btn-secondary btn-sm" onclick="App.toggleEmployee(${e.id}, 'is_muted', ${!e.is_muted})">
            ${e.is_muted ? 'Включить' : 'Игнор'}
          </button>
        </td>
      </tr>`).join('')}</tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async toggleEmployee(id, field, value) {
    try {
      await this.api(`/employees/${id}`, { method: 'PUT', body: { [field]: value } });
      this.toast('Обновлено', 'success');
      this.loadEmployees();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  /* ── Logs ── */
  async loadLogs() {
    try {
      const logs = await this.api('/logs?limit=200');
      const el = document.getElementById('logsTable');
      if (!logs.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">📋</div><h4>Журнал пуст</h4></div>';
        return;
      }
      el.innerHTML = `<table><thead><tr>
        <th>ID</th><th>Время</th><th>Событие</th><th>Чат</th><th>Сообщение</th><th>Статус</th><th>Ошибка</th>
      </tr></thead><tbody>${logs.map(l => `<tr class="${l.status === 'error' ? 'log-row error' : ''}">
        <td>${l.id}</td>
        <td>${this.formatDate(l.created_at)}</td>
        <td>${this.eventLabel(l.event_type)}</td>
        <td>${l.source_chat_id || '—'}</td>
        <td>${l.source_message_id || '—'}</td>
        <td>${this.logStatusBadge(l.status)}</td>
        <td style="color:var(--danger);font-size:.8rem">${l.error_text || ''}</td>
      </tr>`).join('')}</tbody></table>`;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  /* ── Settings ── */
  async loadSettings() {
    try {
      const s = await this.api('/settings');
      this.data.settings = s;
      document.getElementById('settingsForm').innerHTML = `
        <div class="toggle-row">
          <div class="toggle-info"><h4>Синхронизация профилей</h4><p>Копировать имя и аватар сотрудника на технический аккаунт (расширенный режим)</p></div>
          <label class="switch"><input type="checkbox" id="s_profile_sync" ${s.profile_sync_enabled ? 'checked' : ''}><span class="slider"></span></label>
        </div>
        <div class="toggle-row">
          <div class="toggle-info"><h4>Игнорировать ботов</h4><p>Не зеркалировать сообщения от Telegram-ботов</p></div>
          <label class="switch"><input type="checkbox" id="s_ignore_bots" ${s.ignore_bots ? 'checked' : ''}><span class="slider"></span></label>
        </div>
        <div class="toggle-row">
          <div class="toggle-info"><h4>Игнорировать сервисные</h4><p>Пропускать «вошёл в чат», «закрепил сообщение» и т.п.</p></div>
          <label class="switch"><input type="checkbox" id="s_ignore_service" ${s.ignore_service_messages ? 'checked' : ''}><span class="slider"></span></label>
        </div>
        <div class="form-row" style="margin-top:20px">
          <div class="form-group">
            <label>Режим удаления</label>
            <select id="s_delete_mode">
              <option value="soft_delete" ${s.delete_mode === 'soft_delete' ? 'selected' : ''}>Мягкое (пометка «удалено»)</option>
              <option value="hard_delete" ${s.delete_mode === 'hard_delete' ? 'selected' : ''}>Жёсткое (удалить из зеркала)</option>
            </select>
          </div>
          <div class="form-group">
            <label>Фильтр сообщений</label>
            <select id="s_filter_mode">
              <option value="all" ${s.message_filter_mode === 'all' ? 'selected' : ''}>Все сообщения</option>
              <option value="text_only" ${s.message_filter_mode === 'text_only' ? 'selected' : ''}>Только с текстом</option>
              <option value="min_length" ${s.message_filter_mode === 'min_length' ? 'selected' : ''}>Минимальная длина</option>
            </select>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Мин. длина текста (символов)</label>
            <input type="number" id="s_min_length" value="${s.min_message_length}" min="0">
          </div>
          <div class="form-group">
            <label>Макс. размер медиа (МБ)</label>
            <input type="number" id="s_max_media" value="${s.max_media_size_mb}" min="1" max="200">
          </div>
        </div>
      `;
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async saveSettings() {
    try {
      const body = {
        profile_sync_enabled: document.getElementById('s_profile_sync').checked,
        ignore_bots: document.getElementById('s_ignore_bots').checked,
        ignore_service_messages: document.getElementById('s_ignore_service').checked,
        delete_mode: document.getElementById('s_delete_mode').value,
        message_filter_mode: document.getElementById('s_filter_mode').value,
        min_message_length: parseInt(document.getElementById('s_min_length').value) || 0,
        max_media_size_mb: parseInt(document.getElementById('s_max_media').value) || 50,
      };
      await this.api('/settings', { method: 'PUT', body });
      this.toast('Настройки сохранены', 'success');
    } catch (e) { this.toast(e.message, 'error'); }
  },

  /* ── Help ── */
  renderHelp() {
    document.getElementById('helpContent').innerHTML = `
      <div class="help-block">
        <h4>🚀 Быстрый запуск (3 шага)</h4>
        <ol>
          <li>Дважды кликните <code>start.bat</code> в папке shadowchat</li>
          <li>Откройте эту страницу: <code>http://localhost:8000</code></li>
          <li>Следуйте чеклисту на главной странице</li>
        </ol>
      </div>
      <div class="help-block">
        <h4>1. API-ключи Telegram</h4>
        <p>Зайдите на <strong>my.telegram.org</strong> → API development tools → создайте приложение.</p>
        <p>Скопируйте <code>api_id</code> и <code>api_hash</code> в файл <code>.env</code> (рядом с start.bat).</p>
      </div>
      <div class="help-block">
        <h4>2. Авторизация слушателя</h4>
        <p>Откройте терминал в папке shadowchat и выполните:</p>
        <p><code>python scripts/auth_session.py --session listener_main</code></p>
        <p>Введите номер телефона и код из Telegram. Этот аккаунт должен быть <strong>участником всех исходных чатов</strong>.</p>
      </div>
      <div class="help-block">
        <h4>3. Как узнать ID чата</h4>
        <ul>
          <li>Добавьте бота <strong>@userinfobot</strong> или <strong>@getidsbot</strong> в чат — он покажет ID</li>
          <li>ID группы обычно начинается с <code>-100</code></li>
          <li>Исходный чат — рабочий чат, зеркало — обучающий чат для стажёров</li>
        </ul>
      </div>
      <div class="help-block">
        <h4>4. Технические аккаунты (Telethon)</h4>
        <p><strong>Способ 1 — файл .session:</strong> вкладка «Файл .session», имя + загрузите account_01.session</p>
        <p><strong>Способ 2 — строка:</strong> вкладка «Строка Telethon», вставьте StringSession</p>
        <p><strong>Способ 3 — телефон:</strong> вкладка «По телефону», API ID/Hash + код из SMS</p>
        <p>Формат для передачи мне списка:</p>
        <p><code>account_01 | файл account_01.session</code><br>
        <code>account_02 | строка: 1BVtsOHwBu4...</code></p>
      </div>
      <div class="help-block">
        <h4>5. Как это работает</h4>
        <p>Сообщение в исходном чате → система определяет автора → находит его технический аккаунт → публикует копию в зеркале с пометкой имени. Всё автоматически, в реальном времени.</p>
      </div>
    `;
  },

  /* ── Modals ── */
  openModal(type) {
    const overlay = document.getElementById('modalOverlay');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');
    const footer = document.getElementById('modalFooter');

    if (type === 'chatPair') {
      title.textContent = 'Добавить пару чатов';
      body.innerHTML = `
        <div class="form-group">
          <label>Название (для удобства)</label>
          <input id="f_title" placeholder="Например: Отдел продаж">
        </div>
        <div class="form-group">
          <label>ID исходного чата</label>
          <input id="f_source_id" type="number" placeholder="-1001234567890">
          <p class="hint">Рабочий чат, откуда копируем сообщения</p>
        </div>
        <div class="form-group">
          <label>ID зеркального чата</label>
          <input id="f_mirror_id" type="number" placeholder="-1009876543210">
          <p class="hint">Обучающий чат для стажёров</p>
        </div>
        <div class="form-group">
          <label>Режим</label>
          <select id="f_mode">
            <option value="safe">Безопасный (с пометкой автора)</option>
            <option value="profile_sync">Синхронизация профилей</option>
          </select>
        </div>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.closeModal()">Отмена</button>
        <button class="btn btn-primary" onclick="App.submitChatPair()">Создать пару</button>
      `;
    }

    if (type === 'account') {
      this.accountTab = 'file';
      title.textContent = 'Добавить аккаунт';
      this.renderAccountModal();
    }

    overlay.classList.add('open');
  },

  accountTab: 'file',

  renderAccountModal() {
    const body = document.getElementById('modalBody');
    const footer = document.getElementById('modalFooter');
    const t = this.accountTab;

    body.innerHTML = `
      <div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap">
        <button class="btn btn-sm ${t === 'file' ? 'btn-primary' : 'btn-secondary'}" onclick="App.switchAccountTab('file')">Файл .session</button>
        <button class="btn btn-sm ${t === 'string' ? 'btn-primary' : 'btn-secondary'}" onclick="App.switchAccountTab('string')">Строка Telethon</button>
        <button class="btn btn-sm ${t === 'phone' ? 'btn-primary' : 'btn-secondary'}" onclick="App.switchAccountTab('phone')">По телефону</button>
      </div>
      <div id="accountTabContent"></div>
    `;
    const content = document.getElementById('accountTabContent');

    if (t === 'file') {
      content.innerHTML = `
        <div class="form-group">
          <label>Имя аккаунта</label>
          <input id="f_session_name" placeholder="account_01">
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>API ID <span style="color:var(--text-muted)">(опц.)</span></label>
            <input id="imp_api_id" type="number" placeholder="из .env">
          </div>
          <div class="form-group">
            <label>API Hash <span style="color:var(--text-muted)">(опц.)</span></label>
            <input id="imp_api_hash" placeholder="из .env">
          </div>
        </div>
        <div class="form-group">
          <label>Файл сессии Telethon (.session)</label>
          <input id="f_session_file" type="file" accept=".session">
        </div>
        <div class="form-group">
          <label>Journal-файл <span style="color:var(--text-muted)">(опц.)</span></label>
          <input id="f_journal_file" type="file" accept=".session-journal">
        </div>
        <p class="hint">Положите готовые файлы из папки sessions Telethon — account_01.session</p>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.closeModal()">Отмена</button>
        <button class="btn btn-primary" onclick="App.importSessionFile()">Импортировать</button>
      `;
    } else if (t === 'string') {
      content.innerHTML = `
        <div class="form-group">
          <label>Имя аккаунта</label>
          <input id="f_session_name" placeholder="account_01">
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>API ID <span style="color:var(--text-muted)">(опц.)</span></label>
            <input id="imp_api_id" type="number">
          </div>
          <div class="form-group">
            <label>API Hash <span style="color:var(--text-muted)">(опц.)</span></label>
            <input id="imp_api_hash">
          </div>
        </div>
        <div class="form-group">
          <label>Строка сессии (StringSession)</label>
          <textarea id="f_session_string" rows="4" placeholder="1BVtsOHwBu4..."></textarea>
          <p class="hint">Длинная строка из Telethon StringSession.save()</p>
        </div>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.closeModal()">Отмена</button>
        <button class="btn btn-primary" onclick="App.importSessionString()">Импортировать</button>
      `;
    } else {
      content.innerHTML = `
        <div class="form-group">
          <label>Имя аккаунта</label>
          <input id="f_session_name" placeholder="account_01">
        </div>
        <p class="hint">Создаст пустую запись — затем откроется вход по API ID, Hash и номеру телефона.</p>
      `;
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="App.closeModal()">Отмена</button>
        <button class="btn btn-primary" onclick="App.submitAccount()">Создать и войти</button>
      `;
    }
  },

  switchAccountTab(tab) {
    this.accountTab = tab;
    this.renderAccountModal();
  },

  async importSessionFile() {
    const session_name = document.getElementById('f_session_name')?.value.trim();
    const fileInput = document.getElementById('f_session_file');
    if (!session_name || !fileInput?.files?.length) {
      this.toast('Укажите имя и выберите .session файл', 'error');
      return;
    }
    const form = new FormData();
    form.append('session_name', session_name);
    form.append('session_file', fileInput.files[0]);
    const apiId = document.getElementById('imp_api_id')?.value;
    const apiHash = document.getElementById('imp_api_hash')?.value;
    if (apiId) form.append('api_id', apiId);
    if (apiHash) form.append('api_hash', apiHash);
    const journal = document.getElementById('f_journal_file');
    if (journal?.files?.length) form.append('journal_file', journal.files[0]);

    try {
      const res = await this.upload('/sessions/import/file', form);
      const msg = res.verify_warning
        ? `Аккаунт добавлен (проверка Telegram: ${res.verify_warning})`
        : `Импорт OK: ${res.first_name || res.session_name}`;
      this.toast(msg, res.verify_warning ? 'warning' : 'success');
      this.closeModal();
      this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async importSessionString() {
    const session_name = document.getElementById('f_session_name')?.value.trim();
    const session_string = document.getElementById('f_session_string')?.value.trim();
    const api_id = parseInt(document.getElementById('imp_api_id')?.value) || null;
    const api_hash = document.getElementById('imp_api_hash')?.value.trim() || null;

    if (!session_name || !session_string) {
      this.toast('Укажите имя и строку сессии', 'error');
      return;
    }

    try {
      const res = await this.api('/sessions/import/string', {
        method: 'POST',
        body: { session_name, session_string, api_id, api_hash },
      });
      const msg = res.verify_warning
        ? `Аккаунт добавлен (проверка Telegram: ${res.verify_warning})`
        : `Импорт OK: ${res.first_name || res.session_name}`;
      this.toast(msg, res.verify_warning ? 'warning' : 'success');
      this.closeModal();
      this.loadAccounts();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  closeModal() {
    document.getElementById('modalOverlay').classList.remove('open');
  },

  async submitChatPair() {
    const title = document.getElementById('f_title').value.trim();
    const sourceId = parseInt(document.getElementById('f_source_id').value);
    const mirrorId = parseInt(document.getElementById('f_mirror_id').value);
    const mode = document.getElementById('f_mode').value;

    if (!title || !sourceId || !mirrorId) {
      this.toast('Заполните все поля', 'error');
      return;
    }

    try {
      await this.api('/chat-pairs', {
        method: 'POST',
        body: {
          title,
          source_telegram_chat_id: sourceId,
          mirror_telegram_chat_id: mirrorId,
          mode,
        },
      });
      this.toast('Пара чатов создана!', 'success');
      this.closeModal();
      this.loadChats();
      this.refreshDashboard();
    } catch (e) { this.toast(e.message, 'error'); }
  },

  async submitAccount() {
    const session_name = document.getElementById('f_session_name').value.trim();

    if (!session_name) {
      this.toast('Укажите имя аккаунта', 'error');
      return;
    }

    try {
      const res = await this.api('/sessions', {
        method: 'POST',
        body: { session_name },
      });
      this.toast('Аккаунт добавлен', 'success');
      this.closeModal();
      this.loadAccounts();
      this.openAuthModal(res.id, session_name);
    } catch (e) { this.toast(e.message, 'error'); }
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());

// Close modal on overlay click
document.getElementById('modalOverlay').addEventListener('click', e => {
  if (e.target.id === 'modalOverlay') App.closeModal();
});
