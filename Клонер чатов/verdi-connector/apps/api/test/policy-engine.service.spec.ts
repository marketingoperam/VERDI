import { Test } from '@nestjs/testing';
import { ConfigService } from '@nestjs/config';
import { PolicyEngineService } from '../src/modules/policy/policy-engine.service';
import { PrismaService } from '../src/prisma/prisma.service';

describe('PolicyEngineService', () => {
  let service: PolicyEngineService;
  const prisma = {
    outboxMessage: {
      count: jest.fn(),
      findMany: jest.fn(),
    },
  };

  beforeEach(async () => {
    const moduleRef = await Test.createTestingModule({
      providers: [
        PolicyEngineService,
        {
          provide: PrismaService,
          useValue: prisma,
        },
        {
          provide: ConfigService,
          useValue: {
            get: (key: string, fallback?: unknown) => {
              const map: Record<string, unknown> = {
                'policy.replyOnly': true,
                'policy.riskScoreInitiationBlockThreshold': 70,
                'policy.maxDuplicateTemplateRatio': 0.4,
              };
              return map[key] ?? fallback;
            },
          },
        },
      ],
    }).compile();

    service = moduleRef.get(PolicyEngineService);
    jest.clearAllMocks();
  });

  it('blocks initiation when REPLY_ONLY is enabled', async () => {
    const result = await service.evaluate({
      conversationId: 'c1',
      technicalAccountId: 't1',
      messageType: 'initiation',
      body: 'hello',
      normalizedBody: 'hello',
      leadExpectedContact: true,
      isStopListed: false,
      account: {
        status: 'active',
        mode: 'reply_only',
        riskScore: 0,
        hourlyInitiationLimit: 5,
        dailyInitiationLimit: 20,
        dailyReplyLimit: 200,
      },
    });

    expect(result.allowed).toBe(false);
    expect(result.reason).toContain('REPLY_ONLY');
  });

  it('allows reply when not stop-listed', async () => {
    prisma.outboxMessage.count.mockResolvedValue(0);
    prisma.outboxMessage.findMany.mockResolvedValue([]);

    const result = await service.evaluate({
      conversationId: 'c1',
      technicalAccountId: 't1',
      messageType: 'reply',
      body: 'ok',
      normalizedBody: 'ok',
      leadExpectedContact: false,
      isStopListed: false,
      account: {
        status: 'active',
        mode: 'reply_only',
        riskScore: 0,
        hourlyInitiationLimit: 5,
        dailyInitiationLimit: 20,
        dailyReplyLimit: 200,
      },
    });

    expect(result.allowed).toBe(true);
  });
});
