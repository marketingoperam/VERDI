import { Module, forwardRef } from '@nestjs/common';
import { TelegramUserSessionAdapter } from './telegram-user-session.adapter';
import { TELEGRAM_TRANSPORT } from './telegram-transport.interface';
import { TransportIngressService } from './transport-ingress.service';
import { TransportController } from './transport.controller';
import { ConversationsModule } from '../conversations/conversations.module';

@Module({
  imports: [forwardRef(() => ConversationsModule)],
  controllers: [TransportController],
  providers: [
    TelegramUserSessionAdapter,
    TransportIngressService,
    {
      provide: TELEGRAM_TRANSPORT,
      useExisting: TelegramUserSessionAdapter,
    },
  ],
  exports: [TELEGRAM_TRANSPORT, TelegramUserSessionAdapter, TransportIngressService],
})
export class TransportModule {}
