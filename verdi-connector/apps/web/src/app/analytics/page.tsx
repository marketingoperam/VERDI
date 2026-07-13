'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

type AnalyticsItem = {
  conversationId: string;
  username: string | null;
  firstName: string | null;
  telegramUserId: string;
  invitedAt: string | null;
  source: string | null;
  sessionName: string | null;
  techTitle: string;
  conversationState: string;
  inboxInbound: number;
  inboxOutbound: number;
  inboxTotal: number;
  chatMessages: number;
  chatReactions: number;
  chatTotal: number;
  lastInboxAt: string | null;
  lastChatAt: string | null;
  hasChatActivity: boolean;
};

type AnalyticsResponse = {
  total: number;
  withInboxActivity: number;
  withChatActivity: number;
  inboxMessagesTotal: number;
  chatMessagesTotal: number;
  shadowchatReachable: boolean;
  mirrorUsername: string | null;
  items: AnalyticsItem[];
};

function label(item: AnalyticsItem): string {
  if (item.username) return `@${item.username}`;
  if (item.firstName) return item.firstName;
  return item.telegramUserId;
}

function fmt(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AnalyticsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [sort, setSort] = useState('total');
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [status, setStatus] = useState('');

  useEffect(() => {
    const t = localStorage.getItem('verdi_token');
    if (!t) {
      router.replace('/');
      return;
    }
    setToken(t);
  }, [router]);

  async function loadAnalytics(authToken: string, nextSort = sort) {
    setError('');
    const rows = await api<AnalyticsResponse>(
      `/analytics/invited?sort=${encodeURIComponent(nextSort)}`,
      authToken,
    );
    setData(rows);
  }

  useEffect(() => {
    if (!token) return;
    void loadAnalytics(token).catch((err: Error) => {
      if (err.message === 'Unauthorized') {
        localStorage.removeItem('verdi_token');
        router.replace('/');
        return;
      }
      setError(err.message);
    });
  }, [token, sort, router]);

  async function syncFromTelegram() {
    if (!token || syncing) return;
    setSyncing(true);
    setStatus('Синхронизация Telegram…');
    try {
      const result = await api<{ results: Array<{ session: string; dialogs?: number; error?: string }> }>(
        '/transport/sync',
        token,
        { method: 'POST' },
      );
      const ok = result.results.filter((r) => !r.error).length;
      const fail = result.results.filter((r) => r.error);
      setStatus(
        fail.length
          ? `Синк: ${ok} ок, ошибки: ${fail.map((f) => `${f.session}: ${f.error}`).join('; ')}`
          : `Синк готов (${ok} аккаунтов)`,
      );
      await loadAnalytics(token);
    } catch (err) {
      setStatus((err as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  if (!token) return null;

  return (
    <div className="analytics-page">
      <header className="analytics-header">
        <div>
          <h1>Аналитика приглашённых</h1>
          <p>
            Активность в инбоксе и в чате{' '}
            {data?.mirrorUsername ? `@${data.mirrorUsername}` : '@verdi114'}
          </p>
          {!data?.shadowchatReachable && (
            <p className="hint-warn">
              Активность в чате @verdi114 сейчас недоступна с Render (ShadowChat локальный).
              В таблице обновляется переписка из Telegram DM.
            </p>
          )}
          {status && <p className="hint-status">{status}</p>}
        </div>
        <div className="analytics-actions">
          <Link href="/inbox" className="nav-link">
            ← Диалоги
          </Link>
          <button type="button" className="secondary" disabled={syncing} onClick={() => void syncFromTelegram()}>
            {syncing ? 'Синхронизация…' : 'Обновить из Telegram'}
          </button>
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="total">По общей активности</option>
            <option value="chat">По чату verdi114</option>
            <option value="inbox">По переписке в инбоксе</option>
            <option value="invited_at">По дате инвайта</option>
            <option value="username">По username</option>
          </select>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <div className="analytics-cards">
            <div className="stat-card">
              <span>Всего в инбоксе</span>
              <strong>{data.total}</strong>
            </div>
            <div className="stat-card">
              <span>С перепиской</span>
              <strong>{data.withInboxActivity}</strong>
            </div>
            <div className="stat-card">
              <span>Активны в чате</span>
              <strong>{data.withChatActivity}</strong>
            </div>
            <div className="stat-card">
              <span>Сообщений в чате</span>
              <strong>{data.chatMessagesTotal}</strong>
            </div>
            <div className="stat-card">
              <span>ShadowChat</span>
              <strong>{data.shadowchatReachable ? 'подключён' : 'офлайн'}</strong>
            </div>
          </div>

          <div className="analytics-table-wrap">
            <table className="analytics-table">
              <thead>
                <tr>
                  <th>Пользователь</th>
                  <th>Инвайт</th>
                  <th>Тех-аккаунт</th>
                  <th>Инбокс</th>
                  <th>Чат: сообщ.</th>
                  <th>Чат: реакц.</th>
                  <th>Всего</th>
                  <th>Последняя активность</th>
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="empty">
                      Нет приглашённых диалогов. После отписки они появятся здесь автоматически.
                    </td>
                  </tr>
                ) : (
                  data.items.map((item) => (
                    <tr key={item.conversationId}>
                      <td>
                        <strong>{label(item)}</strong>
                        <div className="sub">{item.conversationState}</div>
                      </td>
                      <td>{fmt(item.invitedAt)}</td>
                      <td>
                        <code>{item.sessionName ?? item.techTitle}</code>
                      </td>
                      <td>
                        {item.inboxInbound}↓ / {item.inboxOutbound}↑
                      </td>
                      <td>{item.chatMessages}</td>
                      <td>{item.chatReactions}</td>
                      <td>
                        <strong>{item.inboxTotal + item.chatTotal}</strong>
                      </td>
                      <td>{fmt(item.lastChatAt ?? item.lastInboxAt)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
