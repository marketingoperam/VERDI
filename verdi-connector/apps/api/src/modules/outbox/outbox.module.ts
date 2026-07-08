import { Module, forwardRef } from '@nestjs/common';
import { OutboxService } from './outbox.service';
import { OutboxProcessor } from './outbox.processor';
import { OutboxController } from './outbox.controller';
import { PolicyModule } from '../policy/policy.module';
import { AuditLogModule } from '../audit-log/audit-log.module';
import { RealtimeModule } from '../realtime/realtime.module';
import { TransportModule } from '../transport/transport.module';
import { RiskControlModule } from '../risk-control/risk-control.module';

@Module({
  imports: [
    PolicyModule,
    AuditLogModule,
    forwardRef(() => RealtimeModule),
    TransportModule,
    RiskControlModule,
  ],
  controllers: [OutboxController],
  providers: [OutboxService, OutboxProcessor],
  exports: [OutboxService, OutboxProcessor],
})
export class OutboxModule {}
