import type { ReactNode } from 'react';
import './globals.css';

export const metadata = {
  title: 'VERDI Operator Inbox',
  description: 'Connector inbox for technical Telegram accounts',
  viewport: 'width=device-width, initial-scale=1, viewport-fit=cover',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
