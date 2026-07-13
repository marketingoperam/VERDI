import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { IsOptional, IsString } from 'class-validator';
import { ConversationService } from '../conversations/conversation.service';
import { InviteSyncGuard } from './invite-sync.guard';

class InvitingOutreachBody {
  @IsString()
  sessionName!: string;

  @IsString()
  peerTelegramUserId!: string;

  @IsOptional()
  @IsString()
  externalChatId?: string;

  @IsOptional()
  @IsString()
  username?: string;

  @IsOptional()
  @IsString()
  firstName?: string;

  @IsOptional()
  @IsString()
  lastName?: string;

  @IsString()
  body!: string;

  @IsOptional()
  @IsString()
  telegramMessageId?: string;

  @IsOptional()
  @IsString()
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
      source: 'inviting',
      invitedAt: sentAt,
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
