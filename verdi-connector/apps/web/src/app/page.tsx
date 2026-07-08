'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('andf1n@verdi.local');
  const [password, setPassword] = useState('admin123');
  const [error, setError] = useState('');

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');
    try {
      const data = await api<{ accessToken: string }>('/auth/login', undefined, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem('verdi_token', data.accessToken);
      router.push('/inbox');
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="login">
      <form className="card" onSubmit={onSubmit}>
        <h1>VERDI Operator Inbox</h1>
        <p>Личные диалоги через технический Telegram-аккаунт</p>
        <label>
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Пароль
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="error">{error}</div>}
        <button type="submit">Войти</button>
      </form>
    </main>
  );
}
