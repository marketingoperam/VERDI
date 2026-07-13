import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { normalizeBody, resolveTelegramPeerId } from '../../common/utils/text.util';
import { RealtimeGateway } from '../realtime/realtime.gateway';
import { RiskControlService } from '../risk-control/risk-control.service';

export interface InboundEvent {
  externalChatId: string;
  telegramMessageId: string;
  senderTelegramUserId: string;
  senderUsername?: string;
  senderFirstName?: string;
  senderLastName?: string;
  body: string;
  receivedAt: Date;
  sessionName?: string;
}

export interface OutboundEvent {
  externalChatId: string;
  telegramMessageId: string;
  peerTelegramUserId: string;
  peerUsername?: string;
  peerFirstName?: string;
  peerLastName?: string;
  body: string;
  sentAt: Date;
  sessionName?: string;
}

export interface TelegramDialogImport {
  /** ShadowChat/Telethon session name, e.g. tech_13309563469 */
  sessionName?: string;
  externalChatId: string;
  peerTelegramUserId: string;
  username?: string;
  firstName?: string;
  lastName?: string;
  source?: string;
  invitedAt?: string;
  messages: Array<{
    direction: 'inbound' | 'outbound';
    body: string;
    telegramMessageId: string;
    sentAt: string;
  }>;
}

@Injectable()
export class ConversationService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly realtime: RealtimeGateway,
    private readonly riskControl: RiskControlService,
  ) {}

  async importTelegramDialog(payload: TelegramDialogImport): Promise<{ conversationId: string; imported: number }> {
    const sessionName = payload.sessionName ?? 'tech_13309563469';
    const account =
      (await this.prisma.technicalAccount.findFirst({
        where: { sessionName },
      })) ??
      (await this.prisma.technicalAccount.create({
        data: {
          title: sessionName,
          sessionName,
          status: 'active',
          mode: 'reply_only',
        },
      }));

    const lead = await this.prisma.lead.upsert({
      where: { telegramUserId: BigInt(payload.peerTelegramUserId) },
      create: {
        telegramUserId: BigInt(payload.peerTelegramUserId),
        username: payload.username,
        firstName: payload.firstName,
        lastName: payload.lastName,
        source: payload.source ?? 'telegram_dm',
        invitedAt: payload.invitedAt ? new Date(payload.invitedAt) : undefined,
        tags: [],
      },
      update: {
        username: payload.username,
        firstName: payload.firstName,
        lastName: payload.lastName,
        ...(payload.source ? { source: payload.source } : {}),
        ...(payload.invitedAt ? { invitedAt: new Date(payload.invitedAt) } : {}),
      },
    });

    let conversation = await this.prisma.conversation.findUnique({
      where: {
        leadId_technicalAccountId: {
          leadId: lead.id,
          technicalAccountId: account.id,
        },
      },
    });

    if (!conversation) {
      conversation = await this.prisma.conversation.create({
        data: {
          leadId: lead.id,
          technicalAccountId: account.id,
          externalChatId: resolveTelegramPeerId(payload.externalChatId, lead.telegramUserId),
          state: 'new',
          firstContactType: 'none',
        },
      });
    }

    let imported = 0;
    let lastInboundAt = conversation.lastInboundAt;
    let lastOutboundAt = conversation.lastOutboundAt;
    let unreadDelta = 0;

    const sorted = [...payload.messages].sort(
      (a, b) => new Date(a.sentAt).getTime() - new Date(b.sentAt).getTime(),
    );

    for (const item of sorted) {
      const exists = await this.prisma.message.findFirst({
        where: {
          conversationId: conversation.id,
          telegramMessageId: item.telegramMessageId,
        },
      });
      if (exists) continue;

      const sentAt = new Date(item.sentAt);
      await this.prisma.message.create({
        data: {
          conversationId: conversation.id,
          direction: item.direction,
          senderType: item.direction === 'inbound' ? 'lead' : 'technical_account',
          senderId: item.direction === 'inbound' ? lead.id : account.id,
          body: item.body,
          normalizedBody: normalizeBody(item.body),
          telegramMessageId: item.telegramMessageId,
          deliveryStatus: 'received',
          createdAt: sentAt,
        },
      });
      imported += 1;

      if (item.direction === 'inbound') {
        lastInboundAt = sentAt;
        unreadDelta += 1;
      } else {
        lastOutboundAt = sentAt;
      }
    }

    if (imported === 0) {
      return { conversationId: conversation.id, imported: 0 };
    }

    const hasInbound = sorted.some((m) => m.direction === 'inbound');
    const nextState =
      conversation.state === 'closed'
        ? 'active'
        : hasInbound
          ? 'active'
          : conversation.state === 'new'
            ? 'new'
            : conversation.state;

    const updated = await this.prisma.conversation.update({
      where: { id: conversation.id },
      data: {
        externalChatId: resolveTelegramPeerId(payload.externalChatId, lead.telegramUserId),
        lastInboundAt: lastInboundAt ?? conversation.lastInboundAt,
        lastOutboundAt: lastOutboundAt ?? conversation.lastOutboundAt,
        unreadCount: { increment: unreadDelta },
        state: nextState,
        firstContactType: hasInbound ? conversation.firstContactType : 'automation',
      },
      include: { lead: true, technicalAccount: true, assignedOperator: true },
    });

    this.realtime.emitConversationUpdated(updated);
    return { conversationId: conversation.id, imported };
  }

  async handleInbound(event: InboundEvent): Promise<void> {
    const sessionName = event.sessionName;
    const account = sessionName
      ? ((await this.prisma.technicalAccount.findFirst({
          where: { sessionName, status: { in: ['active', 'limited'] } },
        })) ??
        (await this.prisma.technicalAccount.create({
          data: {
            title: sessionName === 'listener_main' ? '@andf1n' : sessionName,
            sessionName,
            status: 'active',
            mode: 'reply_only',
          },
        })))
      : await this.prisma.technicalAccount.findFirst({
          where: { status: { in: ['active', 'limited'] } },
          orderBy: { createdAt: 'asc' },
        });
    if (!account) return;

    const lead = await this.prisma.lead.upsert({
      where: { telegramUserId: BigInt(event.senderTelegramUserId) },
      create: {
        telegramUserId: BigInt(event.senderTelegramUserId),
        username: event.senderUsername,
        firstName: event.senderFirstName,
        lastName: event.senderLastName,
        source: 'telegram_dm',
        activatedAt: event.receivedAt,
        tags: [],
      },
      update: {
        username: event.senderUsername,
        firstName: event.senderFirstName,
        lastName: event.senderLastName,
      },
    });

    let conversation = await this.prisma.conversation.findUnique({
      where: {
        leadId_technicalAccountId: {
          leadId: lead.id,
          technicalAccountId: account.id,
        },
      },
    });

    if (!conversation) {
      conversation = await this.prisma.conversation.create({
        data: {
          leadId: lead.id,
          technicalAccountId: account.id,
          externalChatId: resolveTelegramPeerId(event.externalChatId, lead.telegramUserId),
          state: 'new',
          firstContactType: 'none',
        },
      });
    }

    const existing = await this.prisma.message.findFirst({
      where: {
        conversationId: conversation.id,
        telegramMessageId: event.telegramMessageId,
      },
    });
    if (existing) return;

    const message = await this.prisma.message.create({
      data: {
        conversationId: conversation.id,
        direction: 'inbound',
        senderType: 'lead',
        senderId: lead.id,
        body: event.body,
        normalizedBody: normalizeBody(event.body),
        telegramMessageId: event.telegramMessageId,
        deliveryStatus: 'received',
        createdAt: event.receivedAt,
      },
    });

    const updated = await this.prisma.conversation.update({
      where: { id: conversation.id },
      data: {
        externalChatId: resolveTelegramPeerId(event.externalChatId, lead.telegramUserId),
        lastInboundAt: event.receivedAt,
        unreadCount: { increment: 1 },
        state: conversation.state === 'closed' ? 'active' : conversation.state,
      },
      include: { lead: true, technicalAccount: true, assignedOperator: true },
    });

    await this.riskControl.onHealthyReplyExchange(account.id);
    this.realtime.emitConversationUpdated(updated);
    this.realtime.emitMessageCreated(conversation.id, message);
  }

  async handleOutbound(event: OutboundEvent): Promise<void> {
    const sessionName = event.sessionName;
    const account = sessionName
      ? ((await this.prisma.technicalAccount.findFirst({
          where: { sessionName, status: { in: ['active', 'limited'] } },
        })) ??
        (await this.prisma.technicalAccount.create({
          data: {
            title: sessionName === 'listener_main' ? '@andf1n' : sessionName,
            sessionName,
            status: 'active',
            mode: 'reply_only',
          },
        })))
      : await this.prisma.technicalAccount.findFirst({
          where: { status: { in: ['active', 'limited'] } },
          orderBy: { createdAt: 'asc' },
        });
    if (!account) return;

    const lead = await this.prisma.lead.upsert({
      where: { telegramUserId: BigInt(event.peerTelegramUserId) },
      create: {
        telegramUserId: BigInt(event.peerTelegramUserId),
        username: event.peerUsername,
        firstName: event.peerFirstName,
        lastName: event.peerLastName,
        source: 'telegram_dm',
        tags: [],
      },
      update: {
        username: event.peerUsername,
        firstName: event.peerFirstName,
        lastName: event.peerLastName,
      },
    });

    let conversation = await this.prisma.conversation.findUnique({
      where: {
        leadId_technicalAccountId: {
          leadId: lead.id,
          technicalAccountId: account.id,
        },
      },
    });

    if (!conversation) {
      conversation = await this.prisma.conversation.create({
        data: {
          leadId: lead.id,
          technicalAccountId: account.id,
          externalChatId: resolveTelegramPeerId(event.externalChatId, lead.telegramUserId),
          state: 'active',
          firstContactType: 'manual',
        },
      });
    }

    const existing = await this.prisma.message.findFirst({
      where: {
        conversationId: conversation.id,
        telegramMessageId: event.telegramMessageId,
      },
    });
    if (existing) return;

    const message = await this.prisma.message.create({
      data: {
        conversationId: conversation.id,
        direction: 'outbound',
        senderType: 'technical_account',
        senderId: account.id,
        body: event.body,
        normalizedBody: normalizeBody(event.body),
        telegramMessageId: event.telegramMessageId,
        deliveryStatus: 'sent',
        createdAt: event.sentAt,
      },
    });

    const updated = await this.prisma.conversation.update({
      where: { id: conversation.id },
      data: {
        externalChatId: resolveTelegramPeerId(event.externalChatId, lead.telegramUserId),
        lastOutboundAt: event.sentAt,
        state: 'awaiting_user',
      },
      include: { lead: true, technicalAccount: true, assignedOperator: true },
    });

    this.realtime.emitConversationUpdated(updated);
    this.realtime.emitMessageCreated(conversation.id, message);
  }

  async listConversations(filter?: {
    state?: string;
    search?: string;
    stopListed?: boolean;
    technicalAccountId?: string;
    sessionName?: string;
  }) {
    const where: Record<string, unknown> = {};
    if (filter?.state) where.state = filter.state;
    if (filter?.stopListed !== undefined) where.isStopListed = filter.stopListed;
    if (filter?.technicalAccountId) where.technicalAccountId = filter.technicalAccountId;
    if (filter?.sessionName) where.technicalAccount = { sessionName: filter.sessionName };
    if (filter?.search) {
      where.OR = [
        { lead: { username: { contains: filter.search, mode: 'insensitive' } } },
        { lead: { firstName: { contains: filter.search, mode: 'insensitive' } } },
      ];
    }

    const techAccounts = await this.prisma.technicalAccount.findMany();
    const excludeTelegramIds = new Set<string>(['777000', '42777']);
    const excludeUsernames = new Set<string>(['telegram']);
    for (const account of techAccounts) {
      if (account.telegramUserId != null) {
        excludeTelegramIds.add(account.telegramUserId.toString());
      }
      for (const raw of [account.title, account.phoneMasked, account.sessionName]) {
        if (!raw) continue;
        const cleaned = raw.replace(/^@/, '').trim().toLowerCase();
        if (cleaned && !cleaned.startsWith('tech_') && !cleaned.startsWith('listener_')) {
          excludeUsernames.add(cleaned);
        }
        if (cleaned === 'andf1n' || cleaned === 'listener_main') {
          excludeUsernames.add('andf1n');
        }
      }
    }

    const rows = await this.prisma.conversation.findMany({
      where,
      include: {
        lead: true,
        technicalAccount: true,
        assignedOperator: true,
      },
      orderBy: [{ lastInboundAt: 'desc' }, { lastOutboundAt: 'desc' }, { updatedAt: 'desc' }],
    });

    // Client inbox only — hide Saved Messages / self chat / service chats / tech accounts.
    return rows.filter((row) => {
      const leadId = row.lead.telegramUserId.toString();
      const leadUsername = (row.lead.username ?? '').toLowerCase();
      if (excludeTelegramIds.has(leadId)) return false;
      if (leadUsername && excludeUsernames.has(leadUsername)) return false;
      if (row.technicalAccount.telegramUserId != null) {
        if (row.technicalAccount.telegramUserId.toString() === leadId) return false;
      }
      return true;
    });
  }

  async getConversation(id: string) {
    const conversation = await this.prisma.conversation.findUnique({
      where: { id },
      include: {
        lead: true,
        technicalAccount: true,
        assignedOperator: true,
        messages: { orderBy: { createdAt: 'asc' }, take: 200 },
      },
    });
    if (!conversation) throw new NotFoundException('Conversation not found');
    return conversation;
  }

  async assignOperator(conversationId: string, operatorId: string) {
    return this.prisma.conversation.update({
      where: { id: conversationId },
      data: { assignedOperatorId: operatorId, state: 'active' },
      include: { lead: true, assignedOperator: true },
    });
  }

  async markRead(conversationId: string) {
    const conversation = await this.prisma.conversation.findUnique({
      where: { id: conversationId },
    });
    if (!conversation) throw new NotFoundException('Conversation not found');

    const updated = await this.prisma.conversation.update({
      where: { id: conversationId },
      data: {
        unreadCount: 0,
        state: conversation.state === 'new' ? 'active' : conversation.state,
      },
      include: { lead: true, technicalAccount: true, assignedOperator: true },
    });
    this.realtime.emitConversationUpdated(updated);
    return updated;
  }

  async addInternalNote(conversationId: string, operatorId: string, body: string) {
    return this.prisma.message.create({
      data: {
        conversationId,
        direction: 'internal_note',
        senderType: 'operator',
        senderId: operatorId,
        body,
        normalizedBody: normalizeBody(body),
        deliveryStatus: 'received',
      },
    });
  }

  async addToStopList(conversationId: string, reason: string) {
    const conversation = await this.prisma.conversation.findUnique({
      where: { id: conversationId },
    });
    if (!conversation) throw new NotFoundException('Conversation not found');

    await this.prisma.stopListEntry.upsert({
      where: { leadId: conversation.leadId },
      create: {
        leadId: conversation.leadId,
        reason,
        source: 'manual',
      },
      update: { reason },
    });

    return this.prisma.conversation.update({
      where: { id: conversationId },
      data: { isStopListed: true, state: 'closed' },
    });
  }
}
