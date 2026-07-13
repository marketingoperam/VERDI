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
    this.adapter.on('inbound', async (payload: Record<string, unknown> & {
      externalChatId: string;
      telegramMessageId: string;
      senderTelegramUserId: string;
      senderUsername?: string;
      senderFirstName?: string;
      senderLastName?: string;
      body: string;
      receivedAt: Date;
      sessionName?: string;
    }) => {
      await this.conversations.handleInbound({
        externalChatId: payload.externalChatId,
        telegramMessageId: payload.telegramMessageId,
        senderTelegramUserId: payload.senderTelegramUserId,
        senderUsername: payload.senderUsername,
        senderFirstName: payload.senderFirstName,
        senderLastName: payload.senderLastName,
        body: payload.body,
        receivedAt: payload.receivedAt,
        sessionName:
          payload.sessionName ??
          this.config.get<string>('TELEGRAM_SESSION', 'listener_main'),
      });
    });
    this.adapter.on('outbound', async (payload: Record<string, unknown> & {
      externalChatId: string;
      telegramMessageId: string;
      peerTelegramUserId: string;
      peerUsername?: string;
      peerFirstName?: string;
      peerLastName?: string;
      body: string;
      sentAt: Date;
      sessionName?: string;
    }) => {
      await this.conversations.handleOutbound({
        externalChatId: payload.externalChatId,
        telegramMessageId: payload.telegramMessageId,
        peerTelegramUserId: payload.peerTelegramUserId,
        peerUsername: payload.peerUsername,
        peerFirstName: payload.peerFirstName,
        peerLastName: payload.peerLastName,
        body: payload.body,
        sentAt: payload.sentAt,
        sessionName:
          payload.sessionName ??
          this.config.get<string>('TELEGRAM_SESSION', 'listener_main'),
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
    const sessionName = String(payload.sessionName ?? payload.session ?? '');
    if (!sessionName) return;
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
    const selfLeads = (
      await this.prisma.lead.findMany({
        where: {
          OR: [
            { telegramUserId: meId },
            { telegramUserId: BigInt(777000) },
            ...(username ? [{ username }] : []),
            { username: 'telegram' },
          ],
        },
        select: { id: true, username: true, telegramUserId: true },
      })
    ).filter((lead) => {
      if (lead.telegramUserId === meId || lead.telegramUserId === BigInt(777000)) return true;
      if (!username) return false;
      const stored = (lead.username ?? '').replace(/^@/, '').toLowerCase();
      return stored === username.toLowerCase() || stored === 'telegram';
    });
    if (selfLeads.length === 0) return;
    const deleted = await this.prisma.conversation.deleteMany({
      where: {
        technicalAccountId: account.id,
        leadId: { in: selfLeads.map((l) => l.id) },
      },
    });
    if (deleted.count > 0) {
      this.logger.log(`Removed ${deleted.count} non-client conversation(s) for ${sessionName}`);
    }
  }

  async onApplicationBootstrap(): Promise<void> {
    if (this.config.get<string>('TELEGRAM_USE_STUB', 'false') === 'true') return;
    if (this.config.get<string>('TELEGRAM_SYNC_ON_START', 'true') !== 'true') return;

    for (const sessionName of this.adapter.configuredSessions()) {
      const account = await this.prisma.technicalAccount.findFirst({ where: { sessionName } });
      if (!account) continue;
      const count = await this.prisma.conversation.count({
        where: { technicalAccountId: account.id },
      });
      if (count > 0) {
        this.logger.log(`[${sessionName}] conversations present (${count}) — skip startup sync`);
        continue;
      }
      this.logger.log(`[${sessionName}] syncing private dialogs...`);
      try {
        const dialogs = await this.adapter.requestSync({
          limitDialogs: 40,
          limitMessages: 50,
          sessionName,
        });
        this.logger.log(`[${sessionName}] sync completed: ${dialogs} dialogs`);
      } catch (err) {
        this.logger.warn(`[${sessionName}] sync failed: ${(err as Error).message}`);
      }
    }
  }
}
