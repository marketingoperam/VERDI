import { Module } from '@nestjs/common';
import { ConversationsModule } from '../conversations/conversations.module';
import { IntegrationsController } from './integrations.controller';
import { InviteSyncGuard } from './invite-sync.guard';

@Module({
  imports: [ConversationsModule],
  controllers: [IntegrationsController],
  providers: [InviteSyncGuard],
})
export class IntegrationsModule {}
