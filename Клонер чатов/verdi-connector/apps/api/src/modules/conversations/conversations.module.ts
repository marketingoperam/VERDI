import { Module, forwardRef } from '@nestjs/common';
import { ConversationService } from './conversation.service';
import { ConversationsController } from './conversations.controller';
import { RealtimeModule } from '../realtime/realtime.module';
import { RiskControlModule } from '../risk-control/risk-control.module';

@Module({
  imports: [forwardRef(() => RealtimeModule), RiskControlModule],
  controllers: [ConversationsController],
  providers: [ConversationService],
  exports: [ConversationService],
})
export class ConversationsModule {}
