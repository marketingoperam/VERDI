import { ChildProcessWithoutNullStreams, spawn } from 'child_process';
import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  randomUUID,
  scryptSync,
} from 'crypto';
import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { EventEmitter } from 'events';
import * as fs from 'fs';
import * as path from 'path';
import {
  SendMessageResult,
  TelegramAccountState,
  TelegramDialog,
  TelegramInboundMessage,
  TelegramTransport,
} from './telegram-transport.interface';

type Pending = {
  resolve: (value: SendMessageResult) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

type SyncPending = {
  resolve: (dialogs: number) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

@Injectable()
export class TelegramUserSessionAdapter extends EventEmitter implements TelegramTransport, OnModuleDestroy {
  private readonly logger = new Logger(TelegramUserSessionAdapter.name);
  private connected = false;
  private worker: ChildProcessWithoutNullStreams | null = null;
  private stdoutBuffer = '';
  private readonly pendingSends = new Map<string, Pending>();
  private readonly pendingSyncs = new Map<string, SyncPending>();
  private meId?: string;
  private meUsername?: string;
  private restartTimer: NodeJS.Timeout | null = null;
  private shuttingDown = false;
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
    if (this.useStub()) {
      this.connected = true;
      this.logger.log('Stub Telegram session connected');
      return;
    }

    if (!this.hasApiCredentials()) {
      this.logger.warn('TELEGRAM_API_ID/HASH missing — Telegram worker not started');
      this.connected = false;
      return;
    }

    await this.startWorker();
  }

  async onModuleDestroy(): Promise<void> {
    this.shuttingDown = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    await this.disconnect();
  }

  private useStub(): boolean {
    return this.config.get<string>('TELEGRAM_USE_STUB', 'false') === 'true';
  }

  private hasApiCredentials(): boolean {
    const apiId = this.config.get<string>('TELEGRAM_API_ID', '');
    const apiHash = this.config.get<string>('TELEGRAM_API_HASH', '');
    return Boolean(apiId && apiHash);
  }

  private sessionName(): string {
    return this.config.get<string>('TELEGRAM_SESSION', 'listener_main');
  }

  private resolveScriptPath(): string {
    const configured = this.config.get<string>('TELEGRAM_WORKER_SCRIPT', '');
    if (configured && fs.existsSync(configured)) return configured;

    const candidates = [
      path.resolve(process.cwd(), '../../scripts/telegram_cloud_worker.py'),
      path.resolve(process.cwd(), '../scripts/telegram_cloud_worker.py'),
      path.resolve(process.cwd(), 'scripts/telegram_cloud_worker.py'),
      path.resolve(__dirname, '../../../../scripts/telegram_cloud_worker.py'),
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return candidate;
    }
    return candidates[0];
  }

  private resolveSessionsDir(): string {
    const configured = this.config.get<string>('TELEGRAM_SESSIONS_DIR', '');
    if (configured) {
      fs.mkdirSync(configured, { recursive: true });
      return configured;
    }
    const candidates = [
      path.resolve(process.cwd(), '../../.telegram-sessions'),
      path.resolve('/var/data/telegram-sessions'),
      path.resolve(process.cwd(), '.telegram-sessions'),
    ];
    const dir = candidates[0];
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  private async startWorker(): Promise<void> {
    if (this.worker) return;

    const script = this.resolveScriptPath();
    const session = this.sessionName();
    const sessionsDir = this.resolveSessionsDir();
    const python = this.config.get<string>('TELEGRAM_PYTHON', 'python');

    this.logger.log(`Starting Telegram worker session=${session} script=${script}`);

    const child = spawn(
      python,
      [script, '--session', session, '--sessions-dir', sessionsDir],
      {
        cwd: path.dirname(script),
        stdio: ['pipe', 'pipe', 'pipe'],
        env: {
          ...process.env,
          PYTHONIOENCODING: 'utf-8',
          PYTHONUNBUFFERED: '1',
          TELEGRAM_API_ID: this.config.get<string>('TELEGRAM_API_ID', ''),
          TELEGRAM_API_HASH: this.config.get<string>('TELEGRAM_API_HASH', ''),
          TELEGRAM_SESSION: session,
          TELEGRAM_SESSIONS_DIR: sessionsDir,
        },
      },
    );

    this.worker = child;
    this.stdoutBuffer = '';

    child.stdout.on('data', (chunk: Buffer) => this.onStdout(chunk.toString('utf8')));
    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8').trim();
      if (text) this.logger.warn(`Telegram worker stderr: ${text}`);
    });
    child.on('error', (err) => {
      this.logger.error(`Telegram worker spawn error: ${err.message}`);
      this.connected = false;
    });
    child.on('close', (code, signal) => {
      this.logger.warn(`Telegram worker exited code=${code} signal=${signal ?? ''}`);
      this.worker = null;
      this.connected = false;
      this.rejectAllPending(new Error('Telegram worker disconnected'));
      if (!this.shuttingDown) {
        this.restartTimer = setTimeout(() => {
          void this.startWorker().catch((e) =>
            this.logger.error(`Telegram worker restart failed: ${(e as Error).message}`),
          );
        }, 5000);
      }
    });

    // Wait briefly for ready event (non-blocking overall — inbound can arrive later)
    await new Promise<void>((resolve) => {
      const onReady = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(() => {
        this.off('worker-ready', onReady);
        resolve();
      }, 15000);
      this.once('worker-ready', onReady);
    });
  }

  private onStdout(chunk: string): void {
    this.stdoutBuffer += chunk;
    let idx: number;
    while ((idx = this.stdoutBuffer.indexOf('\n')) >= 0) {
      const line = this.stdoutBuffer.slice(0, idx).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(idx + 1);
      if (!line) continue;
      try {
        this.handleWorkerEvent(JSON.parse(line) as Record<string, unknown>);
      } catch {
        this.logger.warn(`Invalid worker JSON: ${line.slice(0, 200)}`);
      }
    }
  }

  private handleWorkerEvent(event: Record<string, unknown>): void {
    const type = String(event.type ?? '');
    switch (type) {
      case 'ready':
        this.connected = true;
        this.meId = event.meId ? String(event.meId) : undefined;
        this.meUsername = event.username ? String(event.username) : undefined;
        this.logger.log(
          `Telegram worker ready @${this.meUsername ?? '?'} id=${this.meId ?? '?'}`,
        );
        this.emit('worker-ready', event);
        break;
      case 'inbound': {
        const message: TelegramInboundMessage = {
          externalChatId: String(event.externalChatId),
          telegramMessageId: String(event.telegramMessageId),
          senderTelegramUserId: String(event.senderTelegramUserId),
          senderUsername: event.senderUsername ? String(event.senderUsername) : undefined,
          senderFirstName: event.senderFirstName ? String(event.senderFirstName) : undefined,
          senderLastName: event.senderLastName ? String(event.senderLastName) : undefined,
          body: String(event.body ?? ''),
          receivedAt: new Date(String(event.receivedAt ?? new Date().toISOString())),
        };
        this.emit('inbound', message);
        break;
      }
      case 'send_ok': {
        const reqId = String(event.reqId ?? '');
        const pending = this.pendingSends.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        this.pendingSends.delete(reqId);
        pending.resolve({
          telegramMessageId: String(event.telegramMessageId),
          sentAt: new Date(String(event.sentAt)),
        });
        break;
      }
      case 'send_err': {
        const reqId = String(event.reqId ?? '');
        const pending = this.pendingSends.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        this.pendingSends.delete(reqId);
        pending.reject(new Error(String(event.error ?? 'send failed')));
        break;
      }
      case 'sync_dialog':
        this.emit('sync-dialog', event);
        break;
      case 'sync_done': {
        const reqId = String(event.reqId ?? '');
        const pending = this.pendingSyncs.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        this.pendingSyncs.delete(reqId);
        pending.resolve(Number(event.dialogs ?? 0));
        break;
      }
      case 'log':
        this.logger.log(`[worker] ${String(event.message ?? '')}`);
        break;
      case 'fatal':
        this.logger.error(`Telegram worker fatal: ${String(event.error ?? '')}`);
        break;
      default:
        break;
    }
  }

  private writeCommand(cmd: Record<string, unknown>): void {
    if (!this.worker?.stdin.writable) {
      throw new Error('TRANSPORT_DISCONNECTED');
    }
    this.worker.stdin.write(`${JSON.stringify(cmd)}\n`);
  }

  private rejectAllPending(error: Error): void {
    for (const [id, pending] of this.pendingSends) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pendingSends.delete(id);
    }
    for (const [id, pending] of this.pendingSyncs) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pendingSyncs.delete(id);
    }
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    if (this.worker) {
      const child = this.worker;
      this.worker = null;
      try {
        child.stdin.end();
      } catch {
        // ignore
      }
      child.kill('SIGTERM');
    }
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
    _sessionName?: string,
  ): Promise<SendMessageResult> {
    if (this.useStub()) {
      return this.sendMessageStub(conversationExternalId, text);
    }
    if (!this.connected || !this.worker) {
      throw new Error('TRANSPORT_DISCONNECTED');
    }

    const reqId = randomUUID();
    return new Promise<SendMessageResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingSends.delete(reqId);
        reject(new Error('Telegram send timeout'));
      }, 45000);
      this.pendingSends.set(reqId, { resolve, reject, timer });
      try {
        this.writeCommand({
          cmd: 'send',
          reqId,
          peerId: conversationExternalId,
          text,
        });
      } catch (error) {
        clearTimeout(timer);
        this.pendingSends.delete(reqId);
        reject(error as Error);
      }
    });
  }

  requestSync(options?: { limitDialogs?: number; limitMessages?: number }): Promise<number> {
    if (this.useStub() || !this.worker) {
      return Promise.resolve(0);
    }
    const reqId = randomUUID();
    return new Promise<number>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingSyncs.delete(reqId);
        reject(new Error('Telegram sync timeout'));
      }, 120000);
      this.pendingSyncs.set(reqId, { resolve, reject, timer });
      try {
        this.writeCommand({
          cmd: 'sync',
          reqId,
          limitDialogs: options?.limitDialogs ?? 30,
          limitMessages: options?.limitMessages ?? 40,
        });
      } catch (error) {
        clearTimeout(timer);
        this.pendingSyncs.delete(reqId);
        reject(error as Error);
      }
    });
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

  async markRead(conversationExternalId: string): Promise<void> {
    const dialog = this.dialogs.get(conversationExternalId);
    if (dialog) dialog.unreadCount = 0;
  }

  async getAccountState(): Promise<TelegramAccountState> {
    return {
      connected: this.connected,
      telegramUserId: this.meId,
      status: this.connected ? 'active' : 'disconnected',
    };
  }

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
