import { Inject, Injectable, Logger } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { TELEGRAM_TRANSPORT, TelegramTransport } from '../transport/telegram-transport.interface';
import { RiskControlService } from '../risk-control/risk-control.service';
import { RealtimeGateway } from '../realtime/realtime.gateway';
import { normalizeBody, resolveTelegramPeerId } from '../../common/utils/text.util';

@Injectable()
export class OutboxProcessor {
  private readonly logger = new Logger(OutboxProcessor.name);

  constructor(
    private readonly prisma: PrismaService,
    @Inject(TELEGRAM_TRANSPORT) private readonly transport: TelegramTransport,
    private readonly riskControl: RiskControlService,
    private readonly realtime: RealtimeGateway,
  ) {}

  async process(job: { data: { outboxId: string } }): Promise<void> {
    const outbox = await this.prisma.outboxMessage.findUnique({
      where: { id: job.data.outboxId },
      include: { conversation: { include: { lead: true, technicalAccount: true } } },
    });
    if (!outbox || outbox.policyDecision !== 'allowed') return;

    const externalChatId = resolveTelegramPeerId(
      outbox.conversation.externalChatId,
      outbox.conversation.lead.telegramUserId,
    );
    if (externalChatId !== outbox.conversation.externalChatId) {
      await this.prisma.conversation.update({
        where: { id: outbox.conversationId },
        data: { externalChatId },
      });
    }
    if (!externalChatId) {
      await this.fail(outbox.id, 'Missing externalChatId');
      return;
    }

    try {
      const result = await this.transport.sendMessage(
        externalChatId,
        outbox.body,
        outbox.conversation.technicalAccount.sessionName ?? undefined,
        outbox.conversation.lead.username ?? undefined,
      );
      const message = await this.prisma.message.create({
        data: {
          conversationId: outbox.conversationId,
          direction: 'outbound',
          senderType: 'technical_account',
          senderId: outbox.technicalAccountId,
          body: outbox.body,
          normalizedBody: normalizeBody(outbox.body),
          telegramMessageId: result.telegramMessageId,
          deliveryStatus: 'sent',
        },
      });

      const updatedOutbox = await this.prisma.outboxMessage.update({
        where: { id: outbox.id },
        data: { sendStatus: 'sent', sentAt: result.sentAt },
      });

      await this.prisma.conversation.update({
        where: { id: outbox.conversationId },
        data: { lastOutboundAt: result.sentAt, state: 'awaiting_user' },
      });

      this.realtime.emitMessageCreated(outbox.conversationId, message);
      this.realtime.emitOutboxUpdated(updatedOutbox);
    } catch (error) {
      this.logger.error(`Outbox send failed: ${outbox.id}`, error as Error);
      await this.riskControl.onDeliveryFailure(outbox.technicalAccountId, outbox.conversationId);
      await this.fail(outbox.id, (error as Error).message);
    }
  }

  private async fail(outboxId: string, reason: string): Promise<void> {
    const updated = await this.prisma.outboxMessage.update({
      where: { id: outboxId },
      data: {
        sendStatus: 'failed',
        blockReason: reason,
        retryCount: { increment: 1 },
      },
    });
    this.realtime.emitOutboxUpdated(updated);
  }
}
