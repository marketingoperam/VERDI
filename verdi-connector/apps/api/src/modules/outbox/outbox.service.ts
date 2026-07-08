import { Injectable, NotFoundException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { OutboxMessageType } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { PolicyEngineService } from '../policy/policy-engine.service';
import { AuditLogService } from '../audit-log/audit-log.service';
import { RealtimeGateway } from '../realtime/realtime.gateway';
import { normalizeBody, randomDelay } from '../../common/utils/text.util';
import { OutboxProcessor } from './outbox.processor';

export const OUTBOX_QUEUE = 'outbox-send';

export interface CreateOutboxInput {
  conversationId: string;
  operatorId?: string;
  body: string;
  messageType: OutboxMessageType;
}

@Injectable()
export class OutboxService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly policy: PolicyEngineService,
    private readonly audit: AuditLogService,
    private readonly realtime: RealtimeGateway,
    private readonly config: ConfigService,
    private readonly processor: OutboxProcessor,
  ) {}

  async createOutboxMessage(input: CreateOutboxInput) {
    const conversation = await this.prisma.conversation.findUnique({
      where: { id: input.conversationId },
      include: { lead: true, technicalAccount: true },
    });
    if (!conversation) throw new NotFoundException('Conversation not found');

    const normalizedBody = this.policy.normalize(input.body);
    const decision = await this.policy.evaluate({
      conversationId: conversation.id,
      technicalAccountId: conversation.technicalAccountId,
      messageType: input.messageType,
      body: input.body,
      normalizedBody,
      leadExpectedContact: conversation.lead.expectedContact,
      isStopListed: conversation.isStopListed,
      account: conversation.technicalAccount,
    });

    const delayMin = this.config.get<number>('policy.sendDelayMinMs', 800);
    const delayMax = this.config.get<number>('policy.sendDelayMaxMs', 3500);
    const scheduledAt = new Date(Date.now() + randomDelay(delayMin, delayMax));

    const outbox = await this.prisma.outboxMessage.create({
      data: {
        conversationId: conversation.id,
        operatorId: input.operatorId,
        technicalAccountId: conversation.technicalAccountId,
        body: input.body,
        normalizedBody,
        messageType: input.messageType,
        policyDecision: decision.allowed ? 'allowed' : 'blocked',
        blockReason: decision.reason,
        sendStatus: decision.allowed ? 'pending' : 'failed',
        scheduledAt,
      },
    });

    await this.audit.log({
      actorType: input.operatorId ? 'operator' : 'system',
      actorId: input.operatorId,
      action: decision.allowed ? 'outbox.queued' : 'outbox.blocked',
      entityType: 'OutboxMessage',
      entityId: outbox.id,
      meta: { reason: decision.reason, messageType: input.messageType },
    });

    this.realtime.emitOutboxUpdated(outbox);

    if (decision.allowed) {
      const delayMs = Math.max(0, scheduledAt.getTime() - Date.now());
      await this.prisma.outboxMessage.update({
        where: { id: outbox.id },
        data: { sendStatus: 'queued' },
      });
      setTimeout(() => {
        void this.processor.process({ data: { outboxId: outbox.id } });
      }, delayMs);
    }

    return outbox;
  }
}
