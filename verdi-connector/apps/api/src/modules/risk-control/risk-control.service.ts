import { Injectable } from '@nestjs/common';
import { RiskEventType, RiskSeverity, Prisma } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';

@Injectable()
export class RiskControlService {
  constructor(private readonly prisma: PrismaService) {}

  async recordEvent(params: {
    technicalAccountId: string;
    conversationId?: string;
    type: RiskEventType;
    severity: RiskSeverity;
    delta: number;
    meta?: Record<string, unknown>;
  }): Promise<void> {
    await this.prisma.$transaction([
      this.prisma.riskEvent.create({
        data: {
          technicalAccountId: params.technicalAccountId,
          conversationId: params.conversationId,
          type: params.type,
          severity: params.severity,
          meta: (params.meta ?? {}) as Prisma.InputJsonValue,
        },
      }),
      this.prisma.technicalAccount.update({
        where: { id: params.technicalAccountId },
        data: {
          riskScore: {
            increment: params.delta,
          },
        },
      }),
    ]);
  }

  async onDeliveryFailure(technicalAccountId: string, conversationId: string): Promise<void> {
    await this.recordEvent({
      technicalAccountId,
      conversationId,
      type: 'delivery_failure',
      severity: 'medium',
      delta: 8,
    });
  }

  async onStopRequest(technicalAccountId: string, conversationId: string): Promise<void> {
    await this.recordEvent({
      technicalAccountId,
      conversationId,
      type: 'stop_request',
      severity: 'high',
      delta: 25,
    });
  }

  async onHealthyReplyExchange(technicalAccountId: string): Promise<void> {
    const account = await this.prisma.technicalAccount.findUnique({
      where: { id: technicalAccountId },
    });
    if (!account || account.riskScore <= 0) return;
    await this.prisma.technicalAccount.update({
      where: { id: technicalAccountId },
      data: { riskScore: Math.max(0, account.riskScore - 2) },
    });
  }
}
