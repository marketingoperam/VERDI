import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PrismaService } from '../../prisma/prisma.service';
import { OutboxService } from '../outbox/outbox.service';
import { ConversationService } from '../conversations/conversation.service';
import { AuditLogService } from '../audit-log/audit-log.service';
import { RiskControlService } from '../risk-control/risk-control.service';

@Injectable()
export class TelegramCommandRelayService {
  private readonly logger = new Logger(TelegramCommandRelayService.name);

  constructor(
    private readonly config: ConfigService,
    private readonly prisma: PrismaService,
    private readonly outbox: OutboxService,
    private readonly conversations: ConversationService,
    private readonly audit: AuditLogService,
    private readonly riskControl: RiskControlService,
  ) {}

  async handleCommand(raw: string, telegramUserId: string): Promise<string> {
    if (!this.isAllowedSender(telegramUserId)) {
      return 'Access denied';
    }

    const [command, ...rest] = raw.trim().split(/\s+/);
    const args = rest.join(' ');

    switch (command) {
      case '/reply': {
        const [conversationId, ...textParts] = args.split(' ');
        const text = textParts.join(' ').trim();
        if (!conversationId || !text) return 'Usage: /reply <conversationId> <text>';
        const outbox = await this.outbox.createOutboxMessage({
          conversationId,
          body: text,
          messageType: 'command_reply',
        });
        return outbox.policyDecision === 'blocked'
          ? `Blocked: ${outbox.blockReason}`
          : `Queued outbox ${outbox.id}`;
      }
      case '/note': {
        const [conversationId, ...textParts] = args.split(' ');
        const text = textParts.join(' ').trim();
        if (!conversationId || !text) return 'Usage: /note <conversationId> <text>';
        await this.conversations.addInternalNote(conversationId, 'system', text);
        return 'Note saved';
      }
      case '/assign': {
        const [conversationId, operatorId] = args.split(' ');
        if (!conversationId || !operatorId) return 'Usage: /assign <conversationId> <operatorId>';
        await this.conversations.assignOperator(conversationId, operatorId);
        return 'Assigned';
      }
      case '/pause_account': {
        const [technicalAccountId] = args.split(' ');
        if (!technicalAccountId) return 'Usage: /pause_account <technicalAccountId>';
        await this.prisma.technicalAccount.update({
          where: { id: technicalAccountId },
          data: { status: 'paused' },
        });
        await this.riskControl.recordEvent({
          technicalAccountId,
          type: 'account_pause',
          severity: 'medium',
          delta: 5,
        });
        return 'Account paused';
      }
      case '/resume_account': {
        const [technicalAccountId] = args.split(' ');
        if (!technicalAccountId) return 'Usage: /resume_account <technicalAccountId>';
        await this.prisma.technicalAccount.update({
          where: { id: technicalAccountId },
          data: { status: 'active' },
        });
        return 'Account resumed';
      }
      case '/stoplist': {
        const [conversationId, ...reasonParts] = args.split(' ');
        const reason = reasonParts.join(' ').trim() || 'manual';
        if (!conversationId) return 'Usage: /stoplist <conversationId> <reason>';
        const conversation = await this.prisma.conversation.findUnique({
          where: { id: conversationId },
        });
        if (!conversation) return 'Conversation not found';
        await this.prisma.stopListEntry.upsert({
          where: { leadId: conversation.leadId },
          create: {
            leadId: conversation.leadId,
            reason,
            source: 'manual',
          },
          update: { reason },
        });
        await this.prisma.conversation.update({
          where: { id: conversationId },
          data: { isStopListed: true, state: 'closed' },
        });
        await this.riskControl.onStopRequest(
          conversation.technicalAccountId,
          conversation.id,
        );
        return 'Added to stop-list';
      }
      default:
        return 'Unknown command';
    }
  }

  private isAllowedSender(telegramUserId: string): boolean {
    const allowed = this.config.get<string>('COMMAND_RELAY_ALLOWED_USER_IDS', '');
    if (!allowed.trim()) return true;
    return allowed.split(',').map((v) => v.trim()).includes(telegramUserId);
  }

  /** TODO: wire to dedicated service Telegram chat listener */
  async ingestServiceChatMessage(body: string, senderTelegramUserId: string): Promise<string> {
    this.logger.log(`Command from ${senderTelegramUserId}: ${body}`);
    const response = await this.handleCommand(body, senderTelegramUserId);
    await this.audit.log({
      actorType: 'operator',
      action: 'telegram.command',
      entityType: 'CommandRelay',
      entityId: senderTelegramUserId,
      meta: { body, response },
    });
    return response;
  }
}
