import { Body, Controller, Get, Post, Query, UseGuards } from '@nestjs/common';
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

  @Get('workers')
  @Roles('admin', 'supervisor', 'operator')
  workers() {
    return {
      workers: this.adapter.getWorkerStatuses(),
    };
  }

  @Post('sync')
  @Roles('admin', 'supervisor', 'operator')
  async sync(
    @Query('sessionName') sessionName?: string,
    @Query('limitDialogs') limitDialogs?: string,
    @Query('limitMessages') limitMessages?: string,
  ) {
    const sessions = sessionName
      ? [sessionName]
      : this.adapter.configuredSessions();
    const results: Array<{ session: string; dialogs?: number; error?: string }> = [];
    for (const session of sessions) {
      try {
        const dialogs = await this.adapter.requestSync({
          sessionName: session,
          limitDialogs: limitDialogs ? Number(limitDialogs) : 40,
          limitMessages: limitMessages ? Number(limitMessages) : 50,
        });
        results.push({ session, dialogs });
      } catch (error) {
        results.push({ session, error: (error as Error).message });
      }
    }
    return { ok: true, results };
  }

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
