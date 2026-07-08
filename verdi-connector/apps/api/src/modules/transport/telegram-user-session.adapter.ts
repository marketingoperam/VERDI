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

type WorkerRuntime = {
  session: string;
  child: ChildProcessWithoutNullStreams;
  stdoutBuffer: string;
  connected: boolean;
  meId?: string;
  meUsername?: string;
  lastFatal?: string;
  restartDelayMs: number;
  restartTimer: NodeJS.Timeout | null;
  pendingSends: Map<string, Pending>;
  pendingSyncs: Map<string, SyncPending>;
};

@Injectable()
export class TelegramUserSessionAdapter extends EventEmitter implements TelegramTransport, OnModuleDestroy {
  private readonly logger = new Logger(TelegramUserSessionAdapter.name);
  private connected = false;
  private shuttingDown = false;
  private starting: Promise<void> | null = null;
  private readonly workers = new Map<string, WorkerRuntime>();
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
    await this.startAllWorkers();
  }

  async onModuleDestroy(): Promise<void> {
    this.shuttingDown = true;
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

  configuredSessions(): string[] {
    const multi = this.config.get<string>('TELEGRAM_SESSIONS', '');
    if (multi.trim()) {
      return [...new Set(multi.split(',').map((s) => s.trim()).filter(Boolean))];
    }
    return [this.config.get<string>('TELEGRAM_SESSION', 'listener_main')];
  }

  private primarySession(): string {
    return this.configuredSessions()[0] ?? 'listener_main';
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
    const dir = path.resolve(process.cwd(), '../../.telegram-sessions');
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  private sessionB64EnvKey(session: string): string {
    return `TELEGRAM_SESSION_B64_${session.replace(/[^a-zA-Z0-9]/g, '_')}`;
  }

  private async startAllWorkers(): Promise<void> {
    if (this.starting) {
      await this.starting;
      return;
    }
    this.starting = (async () => {
      for (const session of this.configuredSessions()) {
        await this.spawnWorker(session);
      }
      this.connected = [...this.workers.values()].some((w) => w.connected);
    })().finally(() => {
      this.starting = null;
    });
    await this.starting;
  }

  private async spawnWorker(session: string): Promise<void> {
    const existing = this.workers.get(session);
    if (existing?.child && !existing.child.killed) return;

    const script = this.resolveScriptPath();
    const sessionsDir = this.resolveSessionsDir();
    const python = this.config.get<string>('TELEGRAM_PYTHON', 'python');
    const b64 =
      this.config.get<string>(this.sessionB64EnvKey(session), '') ||
      (session === this.config.get<string>('TELEGRAM_SESSION', 'listener_main')
        ? this.config.get<string>('TELEGRAM_SESSION_B64', '')
        : '');

    this.logger.log(`Starting Telegram worker session=${session}`);

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
          ...(b64 ? { TELEGRAM_SESSION_B64: b64 } : {}),
        },
      },
    );

    const runtime: WorkerRuntime = {
      session,
      child,
      stdoutBuffer: '',
      connected: false,
      restartDelayMs: 5000,
      restartTimer: null,
      pendingSends: new Map(),
      pendingSyncs: new Map(),
    };
    this.workers.set(session, runtime);

    child.stdout.on('data', (chunk: Buffer) => this.onStdout(runtime, chunk.toString('utf8')));
    child.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8').trim();
      if (text) this.logger.warn(`[${session}] stderr: ${text.slice(0, 2000)}`);
    });
    child.on('error', (err) => {
      this.logger.error(`[${session}] spawn error: ${err.message}`);
      runtime.connected = false;
      this.connected = [...this.workers.values()].some((w) => w.connected);
    });
    child.on('close', (code, signal) => {
      this.logger.warn(`[${session}] exited code=${code} signal=${signal ?? ''}`);
      runtime.connected = false;
      this.rejectAllPending(runtime, new Error(`Telegram worker disconnected (${session})`));
      this.workers.delete(session);
      this.connected = [...this.workers.values()].some((w) => w.connected);
      // Do not endlessly restart dead/auth-conflict sessions.
      const fatal = (runtime.lastFatal ?? '').toLowerCase();
      const permanentFail =
        fatal.includes('not authorized') ||
        fatal.includes('authkeyduplicated') ||
        fatal.includes('two different ip');
      if (!this.shuttingDown && !permanentFail) {
        const delay = runtime.restartDelayMs;
        runtime.restartDelayMs = Math.min(runtime.restartDelayMs * 2, 60000);
        runtime.restartTimer = setTimeout(() => {
          void this.spawnWorker(session).catch((e) =>
            this.logger.error(`[${session}] restart failed: ${(e as Error).message}`),
          );
        }, delay);
      } else if (permanentFail) {
        this.logger.warn(`[${session}] permanent auth failure — stop restart loop`);
      }
    });

    await new Promise<void>((resolve) => {
      const onReady = (payload: { session?: string }) => {
        if (payload?.session && payload.session !== session) return;
        runtime.restartDelayMs = 5000;
        clearTimeout(timer);
        this.off('worker-ready', onReady as (...args: unknown[]) => void);
        resolve();
      };
      const timer = setTimeout(() => {
        this.off('worker-ready', onReady as (...args: unknown[]) => void);
        resolve();
      }, 25000);
      this.on('worker-ready', onReady as (...args: unknown[]) => void);
    });
  }

  private onStdout(runtime: WorkerRuntime, chunk: string): void {
    runtime.stdoutBuffer += chunk;
    let idx: number;
    while ((idx = runtime.stdoutBuffer.indexOf('\n')) >= 0) {
      const line = runtime.stdoutBuffer.slice(0, idx).trim();
      runtime.stdoutBuffer = runtime.stdoutBuffer.slice(idx + 1);
      if (!line) continue;
      try {
        this.handleWorkerEvent(runtime, JSON.parse(line) as Record<string, unknown>);
      } catch {
        this.logger.warn(`[${runtime.session}] invalid JSON: ${line.slice(0, 200)}`);
      }
    }
  }

  private handleWorkerEvent(runtime: WorkerRuntime, event: Record<string, unknown>): void {
    const type = String(event.type ?? '');
    switch (type) {
      case 'ready':
        runtime.connected = true;
        runtime.meId = event.meId ? String(event.meId) : undefined;
        runtime.meUsername = event.username ? String(event.username) : undefined;
        this.connected = true;
        this.logger.log(
          `Telegram worker ready session=${runtime.session} @${runtime.meUsername ?? '?'} id=${runtime.meId ?? '?'}`,
        );
        this.emit('worker-ready', {
          ...event,
          session: runtime.session,
          sessionName: runtime.session,
        });
        break;
      case 'inbound': {
        const message: TelegramInboundMessage & { sessionName?: string } = {
          externalChatId: String(event.externalChatId),
          telegramMessageId: String(event.telegramMessageId),
          senderTelegramUserId: String(event.senderTelegramUserId),
          senderUsername: event.senderUsername ? String(event.senderUsername) : undefined,
          senderFirstName: event.senderFirstName ? String(event.senderFirstName) : undefined,
          senderLastName: event.senderLastName ? String(event.senderLastName) : undefined,
          body: String(event.body ?? ''),
          receivedAt: new Date(String(event.receivedAt ?? new Date().toISOString())),
          sessionName: String(event.sessionName ?? runtime.session),
        };
        this.emit('inbound', message);
        break;
      }
      case 'send_ok': {
        const reqId = String(event.reqId ?? '');
        const pending = runtime.pendingSends.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        runtime.pendingSends.delete(reqId);
        pending.resolve({
          telegramMessageId: String(event.telegramMessageId),
          sentAt: new Date(String(event.sentAt)),
        });
        break;
      }
      case 'send_err': {
        const reqId = String(event.reqId ?? '');
        const pending = runtime.pendingSends.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        runtime.pendingSends.delete(reqId);
        pending.reject(new Error(String(event.error ?? 'send failed')));
        break;
      }
      case 'sync_dialog':
        this.emit('sync-dialog', { ...event, sessionName: event.sessionName ?? runtime.session });
        break;
      case 'sync_done': {
        const reqId = String(event.reqId ?? '');
        const pending = runtime.pendingSyncs.get(reqId);
        if (!pending) break;
        clearTimeout(pending.timer);
        runtime.pendingSyncs.delete(reqId);
        pending.resolve(Number(event.dialogs ?? 0));
        break;
      }
      case 'log':
        this.logger.log(`[${runtime.session}] ${String(event.message ?? '')}`);
        break;
      case 'fatal':
        runtime.lastFatal = String(event.error ?? '');
        this.logger.error(`[${runtime.session}] fatal: ${runtime.lastFatal}`);
        break;
      default:
        break;
    }
  }

  private writeCommand(runtime: WorkerRuntime, cmd: Record<string, unknown>): void {
    if (!runtime.child.stdin.writable) {
      throw new Error('TRANSPORT_DISCONNECTED');
    }
    runtime.child.stdin.write(`${JSON.stringify(cmd)}\n`);
  }

  private rejectAllPending(runtime: WorkerRuntime, error: Error): void {
    for (const [id, pending] of runtime.pendingSends) {
      clearTimeout(pending.timer);
      pending.reject(error);
      runtime.pendingSends.delete(id);
    }
    for (const [id, pending] of runtime.pendingSyncs) {
      clearTimeout(pending.timer);
      pending.reject(error);
      runtime.pendingSyncs.delete(id);
    }
  }

  private getWorker(sessionName?: string): WorkerRuntime {
    const preferred = sessionName || this.primarySession();
    const worker = this.workers.get(preferred) ?? this.workers.get(this.primarySession());
    if (!worker || !worker.connected) {
      throw new Error(`TRANSPORT_DISCONNECTED (${preferred})`);
    }
    return worker;
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    for (const runtime of this.workers.values()) {
      if (runtime.restartTimer) clearTimeout(runtime.restartTimer);
      try {
        runtime.child.stdin.end();
      } catch {
        // ignore
      }
      runtime.child.kill('SIGTERM');
    }
    this.workers.clear();
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
    username?: string,
  ): Promise<SendMessageResult> {
    if (this.useStub()) {
      return this.sendMessageStub(conversationExternalId, text);
    }
    const runtime = this.getWorker(sessionName);
    const reqId = randomUUID();
    return new Promise<SendMessageResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        runtime.pendingSends.delete(reqId);
        reject(new Error('Telegram send timeout'));
      }, 45000);
      runtime.pendingSends.set(reqId, { resolve, reject, timer });
      try {
        this.writeCommand(runtime, {
          cmd: 'send',
          reqId,
          peerId: conversationExternalId,
          text,
          ...(username ? { username: username.replace(/^@/, '') } : {}),
        });
      } catch (error) {
        clearTimeout(timer);
        runtime.pendingSends.delete(reqId);
        reject(error as Error);
      }
    });
  }

  requestSync(
    options?: { limitDialogs?: number; limitMessages?: number; sessionName?: string },
  ): Promise<number> {
    if (this.useStub()) return Promise.resolve(0);
    const runtime = this.getWorker(options?.sessionName);
    const reqId = randomUUID();
    return new Promise<number>((resolve, reject) => {
      const timer = setTimeout(() => {
        runtime.pendingSyncs.delete(reqId);
        reject(new Error('Telegram sync timeout'));
      }, 120000);
      runtime.pendingSyncs.set(reqId, { resolve, reject, timer });
      try {
        this.writeCommand(runtime, {
          cmd: 'sync',
          reqId,
          limitDialogs: options?.limitDialogs ?? 30,
          limitMessages: options?.limitMessages ?? 40,
        });
      } catch (error) {
        clearTimeout(timer);
        runtime.pendingSyncs.delete(reqId);
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
    const primary = this.workers.get(this.primarySession());
    return {
      connected: this.connected,
      telegramUserId: primary?.meId,
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
