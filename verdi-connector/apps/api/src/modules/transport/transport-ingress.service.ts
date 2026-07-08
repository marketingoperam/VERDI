import { Injectable, Logger, OnApplicationBootstrap, OnModuleInit } from '@nestjs/common';
import { Inject } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TelegramUserSessionAdapter } from './telegram-user-session.adapter';
import { TELEGRAM_TRANSPORT, TelegramTransport } from './telegram-transport.interface';
import { ConversationService, TelegramDialogImport } from '../conversations/conversation.service';
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
    this.adapter.on('worker-ready', (payload: Record<string, unknown>) => {
      void this.persistTechnicalAccountIdentity(payload);
    });
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
        sessionName: this.config.get<string>('TELEGRAM_SESSION', 'listener_main'),
      });
    });
    this.adapter.on('sync-dialog', (payload: Record<string, unknown>) => {
      const dialog: TelegramDialogImport = {
        sessionName: payload.sessionName ? String(payload.sessionName) : undefined,
        externalChatId: String(payload.externalChatId ?? ''),
        peerTelegramUserId: String(payload.peerTelegramUserId ?? ''),
        username: payload.username ? String(payload.username) : undefined,
        firstName: payload.firstName ? String(payload.firstName) : undefined,
        lastName: payload.lastName ? String(payload.lastName) : undefined,
        messages: (payload.messages as TelegramDialogImport['messages']) ?? [],
      };
      void this.conversations
        .importTelegramDialog(dialog)
        .catch((err) => this.logger.warn(`sync-dialog import failed: ${(err as Error).message}`));
    });
  }

  private async persistTechnicalAccountIdentity(payload: Record<string, unknown>): Promise<void> {
    const sessionName = this.config.get<string>('TELEGRAM_SESSION', 'listener_main');
    const meId = payload.meId ? BigInt(String(payload.meId)) : null;
    const username = payload.username ? String(payload.username) : null;
    if (!meId) return;
    const account = await this.prisma.technicalAccount.findFirst({ where: { sessionName } });
    if (!account) return;
    await this.prisma.technicalAccount.update({
      where: { id: account.id },
      data: {
        telegramUserId: meId,
        title: username ? `@${username}` : account.title,
        phoneMasked: username ?? account.phoneMasked,
      },
    });
    // Hide Saved Messages / self-chat that may already be in DB.
    const selfLeads = await this.prisma.lead.findMany({
      where: {
        OR: [
          { telegramUserId: meId },
          ...(username ? [{ username: { equals: username, mode: 'insensitive' as const } }] : []),
          { username: { equals: 'telegram', mode: 'insensitive' } },
          { telegramUserId: BigInt(777000) },
        ],
      },
      select: { id: true },
    });
    if (selfLeads.length === 0) return;
    const deleted = await this.prisma.conversation.deleteMany({
      where: {
        technicalAccountId: account.id,
        leadId: { in: selfLeads.map((l) => l.id) },
      },
    });
    if (deleted.count > 0) {
      this.logger.log(`Removed ${deleted.count} non-client conversation(s) (self/service)`);
    }
  }

  async onApplicationBootstrap(): Promise<void> {
    if (this.config.get<string>('TELEGRAM_USE_STUB', 'false') === 'true') return;
    if (this.config.get<string>('TELEGRAM_SYNC_ON_START', 'true') !== 'true') return;

    const count = await this.prisma.conversation.count();
    if (count > 0) {
      this.logger.log(`Conversations already present (${count}) — skip startup sync`);
      return;
    }

    this.logger.log('No conversations in DB — requesting Telegram dialog sync...');
    try {
      const dialogs = await this.adapter.requestSync({ limitDialogs: 40, limitMessages: 50 });
      this.logger.log(`Telegram inbox sync requested/completed: ${dialogs} dialogs`);
    } catch (err) {
      this.logger.warn(`Telegram inbox sync failed: ${(err as Error).message}`);
    }
  }
}
