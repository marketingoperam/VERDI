import { Body, Controller, Get, Param, Patch, Post, Query, UseGuards } from '@nestjs/common';
import { ConversationService } from './conversation.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { serializeBigInt } from '../../common/utils/text.util';

@Controller('conversations')
@UseGuards(JwtAuthGuard)
export class ConversationsController {
  constructor(private readonly conversations: ConversationService) {}

  @Get()
  async list(
    @Query('state') state?: string,
    @Query('search') search?: string,
    @Query('stopListed') stopListed?: string,
  ) {
    const rows = await this.conversations.listConversations({
      state,
      search,
      stopListed: stopListed === undefined ? undefined : stopListed === 'true',
    });
    return serializeBigInt(rows);
  }

  @Get(':id')
  async get(@Param('id') id: string) {
    return serializeBigInt(await this.conversations.getConversation(id));
  }

  @Patch(':id/read')
  markRead(@Param('id') id: string) {
    return this.conversations.markRead(id);
  }

  @Patch(':id/assign')
  assign(@Param('id') id: string, @Body() body: { operatorId: string }) {
    return this.conversations.assignOperator(id, body.operatorId);
  }

  @Post(':id/notes')
  addNote(@Param('id') id: string, @Body() body: { operatorId: string; body: string }) {
    return this.conversations.addInternalNote(id, body.operatorId, body.body);
  }

  @Post(':id/stop-list')
  stopList(@Param('id') id: string, @Body() body: { reason?: string }) {
    return this.conversations.addToStopList(id, body.reason ?? 'manual');
  }
}
