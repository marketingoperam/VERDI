import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { OutboxMessageType, TechnicalAccount, TechnicalAccountStatus } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { normalizeBody } from '../../common/utils/text.util';

export interface PolicyEvaluationInput {
  conversationId: string;
  technicalAccountId: string;
  messageType: OutboxMessageType;
  body: string;
  normalizedBody: string;
  leadExpectedContact: boolean;
  isStopListed: boolean;
  account: Pick<
    TechnicalAccount,
    | 'status'
    | 'mode'
    | 'riskScore'
    | 'hourlyInitiationLimit'
    | 'dailyInitiationLimit'
    | 'dailyReplyLimit'
  >;
}

export interface PolicyEvaluationResult {
  allowed: boolean;
  reason?: string;
}

@Injectable()
export class PolicyEngineService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  async evaluate(input: PolicyEvaluationInput): Promise<PolicyEvaluationResult> {
    if (input.isStopListed) {
      return { allowed: false, reason: 'Lead is on stop-list' };
    }

    if (input.account.status === 'paused' || input.account.status === 'banned') {
      return { allowed: false, reason: `Technical account is ${input.account.status}` };
    }

    const replyOnly = this.config.get<boolean>('policy.replyOnly', true);
    const isInitiation =
      input.messageType === 'initiation' || input.messageType === 'template_reply';

    if (isInitiation) {
      if (replyOnly || input.account.mode === 'reply_only') {
        return { allowed: false, reason: 'First-contact initiation is disabled (REPLY_ONLY)' };
      }

      const riskThreshold = this.config.get<number>(
        'policy.riskScoreInitiationBlockThreshold',
        70,
      );
      if (input.account.riskScore >= riskThreshold) {
        return { allowed: false, reason: 'Account risk score too high for initiation' };
      }

      if (!input.leadExpectedContact) {
        return { allowed: false, reason: 'Lead is not marked as expectedContact' };
      }

      const hourly = await this.countRecentOutbox(
        input.technicalAccountId,
        'initiation',
        60 * 60 * 1000,
      );
      if (hourly >= input.account.hourlyInitiationLimit) {
        return { allowed: false, reason: 'Hourly initiation limit reached' };
      }

      const daily = await this.countRecentOutbox(
        input.technicalAccountId,
        'initiation',
        24 * 60 * 60 * 1000,
      );
      if (daily >= input.account.dailyInitiationLimit) {
        return { allowed: false, reason: 'Daily initiation limit reached' };
      }
    } else {
      const maxRepliesPerHour = this.config.get<number>('policy.maxRepliesPerHour', 60);
      const hourlyReplies = await this.countRecentOutbox(
        input.technicalAccountId,
        'reply',
        60 * 60 * 1000,
      );
      if (hourlyReplies >= maxRepliesPerHour) {
        return { allowed: false, reason: 'Hourly reply limit reached' };
      }
    }

    const duplicate = await this.detectDuplicateTemplate(
      input.technicalAccountId,
      input.normalizedBody,
    );
    if (duplicate) {
      return { allowed: false, reason: 'Duplicate template pattern detected' };
    }

    const burst = await this.detectBurst(input.technicalAccountId);
    if (burst) {
      return { allowed: false, reason: 'Anti-burst cooldown active' };
    }

    return { allowed: true };
  }

  private async countRecentOutbox(
    technicalAccountId: string,
    messageType: OutboxMessageType | 'initiation',
    windowMs: number,
  ): Promise<number> {
    const since = new Date(Date.now() - windowMs);
    const types: OutboxMessageType[] =
      messageType === 'initiation'
        ? ['initiation', 'template_reply']
        : ['reply', 'command_reply', 'template_reply'];

    return this.prisma.outboxMessage.count({
      where: {
        technicalAccountId,
        messageType: { in: types },
        createdAt: { gte: since },
        sendStatus: { in: ['pending', 'queued', 'sent'] },
      },
    });
  }

  private async detectDuplicateTemplate(
    technicalAccountId: string,
    normalizedBody: string,
  ): Promise<boolean> {
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000);
    const recent = await this.prisma.outboxMessage.findMany({
      where: {
        technicalAccountId,
        createdAt: { gte: since },
        sendStatus: { in: ['pending', 'queued', 'sent'] },
      },
      select: { normalizedBody: true },
      take: 50,
    });
    if (recent.length < 5) return false;

    const duplicates = recent.filter((m) => m.normalizedBody === normalizedBody).length;
    const ratio = duplicates / recent.length;
    const maxRatio = this.config.get<number>('policy.maxDuplicateTemplateRatio', 0.4);
    return ratio >= maxRatio;
  }

  private async detectBurst(technicalAccountId: string): Promise<boolean> {
    const since = new Date(Date.now() - 60 * 1000);
    const count = await this.prisma.outboxMessage.count({
      where: {
        technicalAccountId,
        createdAt: { gte: since },
        sendStatus: { in: ['pending', 'queued', 'sent'] },
      },
    });
    return count >= 8;
  }

  normalize(text: string): string {
    return normalizeBody(text);
  }
}
