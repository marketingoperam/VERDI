import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from 'crypto';
import { spawn } from 'child_process';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { EventEmitter } from 'events';
import * as path from 'path';
import {
  SendMessageResult,
  TelegramAccountState,
  TelegramDialog,
  TelegramInboundMessage,
  TelegramTransport,
} from './telegram-transport.interface';

@Injectable()
export class TelegramUserSessionAdapter extends EventEmitter implements TelegramTransport {
  private readonly logger = new Logger(TelegramUserSessionAdapter.name);
  private connected = false;
  private readonly dialogs = new Map<string, TelegramDialog>();
  private readonly messages = new Map<string, TelegramInboundMessage[]>();

  constructor(private readonly config: ConfigService) {
    super();
  }

  static encryptSession(plain: string, keyHex: string): string {
    const key = scryptSync(keyHex, 'verdi-salt', 32);
    const iv = randomBytes(16);
    const cipher = createCipheriv('aes-256-gcm', key, iv);
    const encrypted = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]);
    const tag = cipher.getAuthTag();
    return Buffer.concat([iv, tag, encrypted]).toString('base64');
  }

  static decryptSession(payload: string, keyHex: string): string {
    const raw = Buffer.from(payload, 'base64');
    const iv = raw.subarray(0, 16);
    const tag = raw.subarray(16, 32);
    const data = raw.subarray(32);
    const key = scryptSync(keyHex, 'verdi-salt', 32);
    const decipher = createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8');
  }

  async connectSession(): Promise<void> {
    this.connected = true;
    if (this.useStub()) {
      this.logger.log('Stub Telegram session connected');
      return;
    }
    const session = this.config.get<string>('TELEGRAM_SESSION', 'tech_13309563469');
    this.logger.log(`Telegram transport ready (session=${session}, via Telethon)`);
  }

  private useStub(): boolean {
    return this.config.get<string>('TELEGRAM_USE_STUB', 'false') === 'true';
  }

  async disconnect(): Promise<void> {
    this.connected = false;
  }

  async fetchDialogs(): Promise<TelegramDialog[]> {
    return [...this.dialogs.values()];
  }

  async fetchMessages(
    conversationExternalId: string,
    limit = 50,
  ): Promise<TelegramInboundMessage[]> {
    const list = this.messages.get(conversationExternalId) ?? [];
    return list.slice(-limit);
  }

  async sendMessage(
    conversationExternalId: string,
    text: string,
    sessionName?: string,
  ): Promise<SendMessageResult> {
    if (!this.connected) {
      throw new Error('TRANSPORT_DISCONNECTED');
    }
    if (this.useStub()) {
      return this.sendMessageStub(conversationExternalId, text);
    }
    return this.sendMessageViaPython(conversationExternalId, text, sessionName);
  }

  private sendMessageStub(conversationExternalId: string, text: string): SendMessageResult {
    const sentAt = new Date();
    const telegramMessageId = `stub-${Date.now()}`;
    const list = this.messages.get(conversationExternalId) ?? [];
    list.push({
      externalChatId: conversationExternalId,
      telegramMessageId,
      senderTelegramUserId: '900000001',
      body: text,
      receivedAt: sentAt,
    });
    this.messages.set(conversationExternalId, list);
    return { telegramMessageId, sentAt };
  }

  private sendMessageViaPython(peerId: string, text: string, sessionName?: string): Promise<SendMessageResult> {
    const script = path.resolve(process.cwd(), '../../scripts/send_telegram_dm.py');
    const session = sessionName || this.config.get<string>('TELEGRAM_SESSION', 'tech_13309563469');
    const cwd = path.resolve(process.cwd(), '../..');

    return new Promise((resolve, reject) => {
      const child = spawn('python', [script, '--peer-id', peerId, '--session', session], {
        cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      });

      let stdout = '';
      let stderr = '';
      child.stdout.on('data', (chunk: Buffer) => {
        stdout += chunk.toString('utf8');
      });
      child.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString('utf8');
      });
      child.on('error', (error) => reject(error));
      child.on('close', (code) => {
        if (code !== 0) {
          let message = stderr.trim();
          try {
            const parsed = JSON.parse(message) as { error?: string };
            message = parsed.error ?? message;
          } catch {
            // keep raw stderr
          }
          reject(new Error(message || `send_telegram_dm exited with code ${code}`));
          return;
        }
        try {
          const parsed = JSON.parse(stdout.trim()) as {
            telegramMessageId: string;
            sentAt: string;
          };
          resolve({
            telegramMessageId: parsed.telegramMessageId,
            sentAt: new Date(parsed.sentAt),
          });
        } catch {
          reject(new Error(`Invalid Telegram send response: ${stdout}`));
        }
      });

      child.stdin.write(text, 'utf8');
      child.stdin.end();
    });
  }

  async markRead(conversationExternalId: string): Promise<void> {
    const dialog = this.dialogs.get(conversationExternalId);
    if (dialog) dialog.unreadCount = 0;
  }

  async getAccountState(): Promise<TelegramAccountState> {
    return {
      connected: this.connected,
      telegramUserId: '900000001',
      status: this.connected ? 'active' : 'disconnected',
    };
  }

  /** Dev helper: simulate inbound lead message */
  simulateInbound(message: TelegramInboundMessage): void {
    const dialog: TelegramDialog = {
      externalChatId: message.externalChatId,
      title: message.senderUsername ?? message.senderFirstName ?? message.externalChatId,
      unreadCount: (this.dialogs.get(message.externalChatId)?.unreadCount ?? 0) + 1,
      lastMessageAt: message.receivedAt,
    };
    this.dialogs.set(message.externalChatId, dialog);
    const list = this.messages.get(message.externalChatId) ?? [];
    list.push(message);
    this.messages.set(message.externalChatId, list);
    this.emit('inbound', message);
  }
}
