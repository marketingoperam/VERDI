'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { io, Socket } from 'socket.io-client';
import { api, WS_URL } from '@/lib/api';

type Conversation = {
  id: string;
  state: string;
  unreadCount: number;
  isStopListed: boolean;
  externalChatId?: string;
  lastInboundAt?: string;
  technicalAccountId?: string;
  lead: { username?: string; firstName?: string; telegramUserId: string };
  technicalAccount: {
    id?: string;
    title: string;
    status: string;
    riskScore: number;
    sessionName?: string;
  };
  assignedOperator?: { displayName: string };
  messages?: Message[];
};

type Message = {
  id: string;
  direction: string;
  body: string;
  deliveryStatus: string;
  createdAt: string;
};

type Template = { id: string; title: string; body: string };

type TechAccount = {
  id: string;
  title: string;
  sessionName?: string;
  status: string;
  riskScore: number;
};

function leadLabel(c: Conversation): string {
  if (c.lead.username) return `@${c.lead.username}`;
  if (c.lead.firstName) return c.lead.firstName;
  return c.lead.telegramUserId;
}

export default function InboxPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [accounts, setAccounts] = useState<TechAccount[]>([]);
  const [accountId, setAccountId] = useState<string>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<'list' | 'chat'>('list');
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState('');
  const [templates, setTemplates] = useState<Template[]>([]);
  const [status, setStatus] = useState('');

  const selected = useMemo(
    () => conversations.find((c) => c.id === selectedId) ?? null,
    [conversations, selectedId],
  );

  useEffect(() => {
    const t = localStorage.getItem('verdi_token');
    if (!t) {
      router.replace('/');
      return;
    }
    setToken(t);
  }, [router]);

  useEffect(() => {
    if (!token) return;
    void api<TechAccount[]>('/technical-accounts', token)
      .then((rows) => {
        setAccounts(rows.filter((a) => a.status === 'active' || a.status === 'limited'));
      })
      .catch(() => undefined);
    void api<Template[]>('/templates', token).then(setTemplates).catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    void loadConversations(token);
  }, [token, filter, search, accountId]);

  useEffect(() => {
    if (!token) return;
    const socket: Socket = io(WS_URL, { transports: ['websocket'] });
    socket.on('conversation.updated', (payload: Conversation) => {
      setConversations((prev) => {
        if (accountId !== 'all') {
          const techId = payload.technicalAccountId ?? payload.technicalAccount?.id;
          if (techId && techId !== accountId) return prev;
        }
        const idx = prev.findIndex((c) => c.id === payload.id);
        if (idx === -1) return [payload, ...prev];
        const copy = [...prev];
        copy[idx] = { ...copy[idx], ...payload };
        return copy;
      });
    });
    socket.on('message.created', async ({ conversationId }: { conversationId: string }) => {
      if (!token) return;
      const detail = await api<Conversation>(`/conversations/${conversationId}`, token);
      setConversations((prev) => prev.map((c) => (c.id === conversationId ? { ...c, ...detail } : c)));
    });
    socket.on('outbox.updated', (payload: { blockReason?: string; sendStatus: string }) => {
      setStatus(`${payload.sendStatus}${payload.blockReason ? `: ${payload.blockReason}` : ''}`);
    });
    return () => {
      socket.disconnect();
    };
  }, [token, accountId]);

  async function loadConversations(authToken: string) {
    const params = new URLSearchParams();
    if (filter !== 'all') params.set('state', filter);
    if (search) params.set('search', search);
    if (accountId !== 'all') params.set('technicalAccountId', accountId);
    try {
      const rows = await api<Conversation[]>(`/conversations?${params}`, authToken);
      setConversations(rows);
      setSelectedId((prev) => (prev && rows.some((r) => r.id === prev) ? prev : null));
      setMobileView('list');
      setStatus('');
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  async function openConversation(id: string) {
    if (!token) return;
    setSelectedId(id);
    setMobileView('chat');
    const detail = await api<Conversation>(`/conversations/${id}`, token);
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, ...detail } : c)));
    await api(`/conversations/${id}/read`, token, { method: 'PATCH' });
  }

  function backToList() {
    setMobileView('list');
  }

  async function sendReply() {
    if (!token || !selected || !draft.trim()) return;
    setStatus('sending...');
    try {
      await api('/outbox', token, {
        method: 'POST',
        body: JSON.stringify({ conversationId: selected.id, text: draft, messageType: 'reply' }),
      });
      setDraft('');
      setStatus('queued');
    } catch (err) {
      setStatus((err as Error).message);
    }
  }

  async function simulateInbound() {
    if (!token || !selected) return;
    await api('/transport/simulate-inbound', token, {
      method: 'POST',
      body: JSON.stringify({
        externalChatId: selected.externalChatId ?? selected.lead.telegramUserId,
        senderTelegramUserId: selected.lead.telegramUserId,
        senderUsername: selected.lead.username,
        senderFirstName: selected.lead.firstName,
        body: 'Тестовое входящее сообщение',
      }),
    });
  }

  if (!token) return null;

  const inboxClass = `inbox ${mobileView === 'chat' && selectedId ? 'show-chat' : 'show-list'}`;

  return (
    <div className={inboxClass}>
      <aside className="sidebar">
        <header>
          <h2>Диалоги</h2>
          <button type="button" className="secondary" onClick={() => token && void loadConversations(token)}>
            Обновить
          </button>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="all">Все тех-аккаунты</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.title}{a.sessionName ? ` (${a.sessionName})` : ''}
              </option>
            ))}
          </select>
          <input
            placeholder="Поиск username"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">Все</option>
            <option value="new">New</option>
            <option value="active">Active</option>
            <option value="moderation">Moderation</option>
            <option value="closed">Closed</option>
          </select>
        </header>
        <div className="list">
          {conversations.length === 0 ? (
            <div className="empty">Нет клиентских диалогов</div>
          ) : (
            conversations.map((c) => (
              <button
                key={c.id}
                className={`item ${selectedId === c.id ? 'active' : ''}`}
                onClick={() => void openConversation(c.id)}
              >
                <strong>{leadLabel(c)}</strong>
                <span>{c.technicalAccount.title} · {c.state} · unread {c.unreadCount}</span>
                {c.isStopListed && <em>stop-list</em>}
              </button>
            ))
          )}
        </div>
      </aside>

      <main className="chat">
        {selected ? (
          <>
            <header>
              <button type="button" className="mobile-back" onClick={backToList}>
                ← Назад
              </button>
              <h3>{leadLabel(selected)}</h3>
              <span>{status}</span>
            </header>
            <div className="messages">
              {(selected.messages ?? []).map((m) => (
                <div key={m.id} className={`msg ${m.direction}`}>
                  <div>{m.body}</div>
                  <small>{m.direction} · {m.deliveryStatus}</small>
                </div>
              ))}
            </div>
            <div className="composer">
              <div className="templates">
                {templates
                  .filter((t, idx, all) => all.findIndex((x) => x.title === t.title) === idx)
                  .slice(0, 2)
                  .map((t) => (
                    <button key={t.id} type="button" onClick={() => setDraft(t.body)}>
                      {t.title}
                    </button>
                  ))}
              </div>
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} />
              <div className="actions">
                <button onClick={() => void sendReply()}>Отправить ответ</button>
                <button className="secondary" onClick={() => void simulateInbound()}>
                  Симулировать входящее
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="empty">Выберите диалог</div>
        )}
      </main>

      <aside className="lead-card">
        {selected ? (
          <>
            <h3>Карточка лида</h3>
            <p>Telegram ID: {selected.lead.telegramUserId}</p>
            <p>Username: {selected.lead.username ? `@${selected.lead.username}` : '—'}</p>
            <p>Состояние: {selected.state}</p>
            <p>Тех-аккаунт: {selected.technicalAccount.title}</p>
            <p>Session: {selected.technicalAccount.sessionName ?? '—'}</p>
            <p>Account status: {selected.technicalAccount.status}</p>
            <p className={selected.technicalAccount.riskScore > 50 ? 'risk high' : 'risk'}>
              Risk score: {selected.technicalAccount.riskScore}
            </p>
            <p>Оператор: {selected.assignedOperator?.displayName ?? 'не назначен'}</p>
          </>
        ) : (
          <p>Нет выбранного лида</p>
        )}
      </aside>
    </div>
  );
}
