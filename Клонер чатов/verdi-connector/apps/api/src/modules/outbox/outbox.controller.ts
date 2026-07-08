import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { OutboxMessageType } from '@prisma/client';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { CurrentUser } from '../auth/current-user.decorator';
import { OutboxService } from './outbox.service';

@Controller('outbox')
@UseGuards(JwtAuthGuard)
export class OutboxController {
  constructor(private readonly outbox: OutboxService) {}

  @Post()
  create(
    @CurrentUser() user: { sub: string },
    @Body() body: { conversationId: string; text: string; messageType?: OutboxMessageType },
  ) {
    return this.outbox.createOutboxMessage({
      conversationId: body.conversationId,
      operatorId: user.sub,
      body: body.text,
      messageType: body.messageType ?? 'reply',
    });
  }
}
