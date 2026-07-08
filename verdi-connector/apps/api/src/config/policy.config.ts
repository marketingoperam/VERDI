import { registerAs } from '@nestjs/config';

export default registerAs('policy', () => ({
  replyOnly: process.env.REPLY_ONLY === 'true',
  maxInitiationsPerHour: Number(process.env.MAX_INITIATIONS_PER_HOUR ?? 5),
  maxInitiationsPerDay: Number(process.env.MAX_INITIATIONS_PER_DAY ?? 20),
  maxRepliesPerHour: Number(process.env.MAX_REPLIES_PER_HOUR ?? 60),
  maxDuplicateTemplateRatio: Number(process.env.MAX_DUPLICATE_TEMPLATE_RATIO ?? 0.4),
  outboundInboundRiskThreshold: Number(process.env.OUTBOUND_INBOUND_RISK_THRESHOLD ?? 3),
  riskScoreInitiationBlockThreshold: Number(
    process.env.RISK_SCORE_INITIATION_BLOCK_THRESHOLD ?? 70,
  ),
  sendDelayMinMs: Number(process.env.SEND_DELAY_MIN_MS ?? 800),
  sendDelayMaxMs: Number(process.env.SEND_DELAY_MAX_MS ?? 3500),
}));
