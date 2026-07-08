import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { Roles } from '../auth/roles.decorator';
import { RolesGuard } from '../auth/roles.guard';
import { TelegramCommandRelayService } from './telegram-command-relay.service';

@Controller('telegram-commands')
@UseGuards(JwtAuthGuard, RolesGuard)
export class TelegramCommandRelayController {
  constructor(private readonly relay: TelegramCommandRelayService) {}

  @Post('simulate')
  @Roles('admin', 'supervisor')
  simulate(@Body() body: { command: string; senderTelegramUserId: string }) {
    return this.relay.ingestServiceChatMessage(body.command, body.senderTelegramUserId);
  }
}
