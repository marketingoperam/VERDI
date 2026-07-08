export interface TelegramDialog {
  externalChatId: string;
  title: string;
  unreadCount: number;
  lastMessageAt?: Date;
}

export interface TelegramInboundMessage {
  externalChatId: string;
  telegramMessageId: string;
  senderTelegramUserId: string;
  senderUsername?: string;
  senderFirstName?: string;
  senderLastName?: string;
  body: string;
  receivedAt: Date;
}

export interface TelegramAccountState {
  connected: boolean;
  telegramUserId?: string;
  status: 'active' | 'paused' | 'limited' | 'banned' | 'disconnected';
  lastError?: string;
}

export interface SendMessageResult {
  telegramMessageId: string;
  sentAt: Date;
}

export interface TelegramTransport {
  connectSession(): Promise<void>;
  disconnect(): Promise<void>;
  fetchDialogs(): Promise<TelegramDialog[]>;
  fetchMessages(conversationExternalId: string, limit?: number): Promise<TelegramInboundMessage[]>;
  sendMessage(
    conversationExternalId: string,
    text: string,
    sessionName?: string,
    username?: string,
  ): Promise<SendMessageResult>;
  markRead(conversationExternalId: string): Promise<void>;
  getAccountState(): Promise<TelegramAccountState>;
}

export const TELEGRAM_TRANSPORT = Symbol('TELEGRAM_TRANSPORT');
