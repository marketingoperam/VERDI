import { Module } from '@nestjs/common';
import { TelegramCommandRelayService } from './telegram-command-relay.service';
import { TelegramCommandRelayController } from './telegram-command-relay.controller';
import { OutboxModule } from '../outbox/outbox.module';
import { ConversationsModule } from '../conversations/conversations.module';
import { AuditLogModule } from '../audit-log/audit-log.module';
import { RiskControlModule } from '../risk-control/risk-control.module';

@Module({
  imports: [OutboxModule, ConversationsModule, AuditLogModule, RiskControlModule],
  controllers: [TelegramCommandRelayController],
  providers: [TelegramCommandRelayService],
  exports: [TelegramCommandRelayService],
})
export class TelegramCommandRelayModule {}
