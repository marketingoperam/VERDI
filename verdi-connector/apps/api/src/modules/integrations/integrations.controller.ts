import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { ConversationService } from '../conversations/conversation.service';
import { InviteSyncGuard } from './invite-sync.guard';

class InvitingOutreachBody {
  sessionName!: string;
  peerTelegramUserId!: string;
  externalChatId?: string;
  username?: string;
  firstName?: string;
  lastName?: string;
  body!: string;
  telegramMessageId?: string;
  sentAt?: string;
}

@Controller('integrations/inviting')
export class IntegrationsController {
  constructor(private readonly conversations: ConversationService) {}

  /** Called by local inviting panel after cold outreach DM. */
  @Post('outreach')
  @UseGuards(InviteSyncGuard)
  outreach(@Body() body: InvitingOutreachBody) {
    const sentAt = body.sentAt ?? new Date().toISOString();
    const peerId = body.peerTelegramUserId;
    return this.conversations.importTelegramDialog({
      sessionName: body.sessionName,
      externalChatId: body.externalChatId ?? peerId,
      peerTelegramUserId: peerId,
      username: body.username,
      firstName: body.firstName,
      lastName: body.lastName,
      messages: [
        {
          direction: 'outbound',
          body: body.body,
          telegramMessageId:
            body.telegramMessageId ?? `invite-outreach-${body.sessionName}-${peerId}-${Date.now()}`,
          sentAt,
        },
      ],
    });
  }
}
