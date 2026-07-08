import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { Roles } from '../auth/roles.decorator';
import { RolesGuard } from '../auth/roles.guard';
import { ConversationService, TelegramDialogImport } from '../conversations/conversation.service';
import { TelegramUserSessionAdapter } from './telegram-user-session.adapter';

@Controller('transport')
@UseGuards(JwtAuthGuard, RolesGuard)
export class TransportController {
  constructor(
    private readonly adapter: TelegramUserSessionAdapter,
    private readonly conversations: ConversationService,
  ) {}

  /** Dev endpoint: simulate inbound Telegram DM for local testing */
  @Post('simulate-inbound')
  @Roles('admin', 'supervisor')
  simulateInbound(
    @Body()
    body: {
      externalChatId: string;
      senderTelegramUserId: string;
      senderUsername?: string;
      senderFirstName?: string;
      body: string;
    },
  ) {
    const receivedAt = new Date();
    this.adapter.simulateInbound({
      externalChatId: body.externalChatId,
      telegramMessageId: `sim-${Date.now()}`,
      senderTelegramUserId: body.senderTelegramUserId,
      senderUsername: body.senderUsername,
      senderFirstName: body.senderFirstName,
      body: body.body,
      receivedAt,
    });
    return { ok: true };
  }

  @Post('import-dialog')
  @Roles('admin', 'supervisor')
  importDialog(@Body() body: TelegramDialogImport) {
    return this.conversations.importTelegramDialog(body);
  }
}
