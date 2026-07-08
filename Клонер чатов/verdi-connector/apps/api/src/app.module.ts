import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { PrismaModule } from './prisma/prisma.module';
import { BootstrapModule } from './bootstrap/bootstrap.module';
import policyConfig from './config/policy.config';
import { AuthModule } from './modules/auth/auth.module';
import { ConversationsModule } from './modules/conversations/conversations.module';
import { OutboxModule } from './modules/outbox/outbox.module';
import { TransportModule } from './modules/transport/transport.module';
import { PolicyModule } from './modules/policy/policy.module';
import { RiskControlModule } from './modules/risk-control/risk-control.module';
import { AuditLogModule } from './modules/audit-log/audit-log.module';
import { RealtimeModule } from './modules/realtime/realtime.module';
import { TelegramCommandRelayModule } from './modules/telegram-command-relay/telegram-command-relay.module';
import { CatalogModule } from './modules/catalog/catalog.module';
import { HealthController } from './modules/health/health.controller';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, load: [policyConfig] }),
    PrismaModule,
    BootstrapModule,
    AuthModule,
    ConversationsModule,
    OutboxModule,
    TransportModule,
    PolicyModule,
    RiskControlModule,
    AuditLogModule,
    RealtimeModule,
    TelegramCommandRelayModule,
    CatalogModule,
  ],
  controllers: [HealthController],
})
export class AppModule {}
