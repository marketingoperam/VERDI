import { Body, Controller, Get, HttpCode, Post, Query, UseGuards } from '@nestjs/common';
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
  @HttpCode(200)
  @Roles('admin', 'supervisor', 'operator')
  async sync(
    @Query('sessionName') sessionName?: string,
    @Query('limitDialogs') limitDialogs?: string,
    @Query('limitMessages') limitMessages?: string,
    @Query('connectedOnly') connectedOnly?: string,
  ) {
    const onlyConnected = connectedOnly !== '0' && connectedOnly !== 'false';
    const dialogLimit = limitDialogs ? Number(limitDialogs) : 20;
    const messageLimit = limitMessages ? Number(limitMessages) : 30;

    const configured = sessionName
      ? [sessionName]
      : this.adapter.configuredSessions();
    const statuses = this.adapter.getWorkerStatuses();
    const connected = new Set(
      statuses.filter((w) => w.connected).map((w) => w.session),
    );

    const results: Array<{ session: string; dialogs?: number; error?: string }> = [];
    const toSync: string[] = [];

    for (const session of configured) {
      if (onlyConnected && !connected.has(session)) {
        results.push({
          session,
          error: `TRANSPORT_DISCONNECTED (${session})`,
        });
        continue;
      }
      toSync.push(session);
    }

    // Parallel per-session sync keeps wall-clock under Render's ~100s proxy timeout.
    const synced = await Promise.all(
      toSync.map(async (session) => {
        try {
          const dialogs = await this.adapter.requestSync({
            sessionName: session,
            limitDialogs: dialogLimit,
            limitMessages: messageLimit,
          });
          return { session, dialogs };
        } catch (error) {
          return { session, error: (error as Error).message };
        }
      }),
    );
    results.push(...synced);

    // Preserve configured session order in the response.
    const order = new Map(configured.map((s, i) => [s, i]));
    results.sort(
      (a, b) => (order.get(a.session) ?? 999) - (order.get(b.session) ?? 999),
    );

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
