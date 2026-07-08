import { Test } from '@nestjs/testing';
import { ConfigService } from '@nestjs/config';
import { OutboxService } from '../src/modules/outbox/outbox.service';
import { OutboxProcessor } from '../src/modules/outbox/outbox.processor';
import { PrismaService } from '../src/prisma/prisma.service';
import { PolicyEngineService } from '../src/modules/policy/policy-engine.service';
import { AuditLogService } from '../src/modules/audit-log/audit-log.service';
import { RealtimeGateway } from '../src/modules/realtime/realtime.gateway';

describe('OutboxService', () => {
  let service: OutboxService;
  const prisma = {
    conversation: { findUnique: jest.fn() },
    outboxMessage: { create: jest.fn(), update: jest.fn() },
  };
  const policy = { normalize: jest.fn((v: string) => v), evaluate: jest.fn() };
  const audit = { log: jest.fn() };
  const realtime = { emitOutboxUpdated: jest.fn() };
  const processor = { process: jest.fn() };

  beforeEach(async () => {
    const moduleRef = await Test.createTestingModule({
      providers: [
        OutboxService,
        { provide: PrismaService, useValue: prisma },
        { provide: PolicyEngineService, useValue: policy },
        { provide: AuditLogService, useValue: audit },
        { provide: RealtimeGateway, useValue: realtime },
        {
          provide: ConfigService,
          useValue: { get: (_: string, fallback?: unknown) => fallback },
        },
        { provide: OutboxProcessor, useValue: processor },
      ],
    }).compile();

    service = moduleRef.get(OutboxService);
    jest.clearAllMocks();
  });

  it('creates blocked outbox when policy rejects', async () => {
    prisma.conversation.findUnique.mockResolvedValue({
      id: 'c1',
      technicalAccountId: 't1',
      isStopListed: true,
      lead: { expectedContact: false },
      technicalAccount: {
        status: 'active',
        mode: 'reply_only',
        riskScore: 0,
        hourlyInitiationLimit: 5,
        dailyInitiationLimit: 20,
        dailyReplyLimit: 200,
      },
    });
    policy.evaluate.mockResolvedValue({ allowed: false, reason: 'stop-list' });
    prisma.outboxMessage.create.mockResolvedValue({
      id: 'o1',
      policyDecision: 'blocked',
      blockReason: 'stop-list',
      sendStatus: 'failed',
    });

    const result = await service.createOutboxMessage({
      conversationId: 'c1',
      operatorId: 'op1',
      body: 'hello',
      messageType: 'reply',
    });

    expect(result.policyDecision).toBe('blocked');
    expect(processor.process).not.toHaveBeenCalled();
    expect(audit.log).toHaveBeenCalled();
  });
});
