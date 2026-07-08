import { Injectable, Logger, OnApplicationBootstrap, OnModuleInit } from '@nestjs/common';
import { Inject } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { spawn } from 'child_process';
import * as path from 'path';
import { TelegramUserSessionAdapter } from './telegram-user-session.adapter';
import { TELEGRAM_TRANSPORT, TelegramTransport } from './telegram-transport.interface';
import { ConversationService } from '../conversations/conversation.service';
import { PrismaService } from '../../prisma/prisma.service';

@Injectable()
export class TransportIngressService implements OnModuleInit, OnApplicationBootstrap {
  private readonly logger = new Logger(TransportIngressService.name);

  constructor(
    @Inject(TELEGRAM_TRANSPORT) private readonly transport: TelegramTransport,
    private readonly adapter: TelegramUserSessionAdapter,
    private readonly conversations: ConversationService,
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  async onModuleInit(): Promise<void> {
    await this.transport.connectSession();
    this.adapter.on('inbound', async (payload) => {
      await this.conversations.handleInbound({
        externalChatId: payload.externalChatId,
        telegramMessageId: payload.telegramMessageId,
        senderTelegramUserId: payload.senderTelegramUserId,
        senderUsername: payload.senderUsername,
        senderFirstName: payload.senderFirstName,
        senderLastName: payload.senderLastName,
        body: payload.body,
        receivedAt: payload.receivedAt,
      });
    });
  }

  async onApplicationBootstrap(): Promise<void> {
    if (this.config.get<string>('TELEGRAM_SYNC_ON_START', 'true') !== 'true') return;

    const count = await this.prisma.conversation.count();
    if (count > 0) return;

    this.logger.log('No conversations in DB — syncing private dialogs from Telegram session...');
    this.runTelegramSync();
  }

  private runTelegramSync(): void {
    const script = path.resolve(process.cwd(), '../../scripts/sync_telegram_inbox.py');
    const apiUrl = `http://127.0.0.1:${this.config.get<string>('PORT', '3001')}`;
    const child = spawn('python', [script, '--api', apiUrl], {
      cwd: path.resolve(process.cwd(), '../..'),
      stdio: 'inherit',
    });
    child.on('error', (err) => this.logger.warn(`Telegram sync failed to start: ${err.message}`));
    child.on('exit', (code) => {
      if (code === 0) this.logger.log('Telegram inbox sync completed');
      else this.logger.warn(`Telegram inbox sync exited with code ${code ?? 'unknown'}`);
    });
  }
}
