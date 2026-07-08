import { WebSocketGateway, WebSocketServer } from '@nestjs/websockets';
import { Server } from 'socket.io';
import { Message, OutboxMessage } from '@prisma/client';
import { serializeBigInt } from '../../common/utils/text.util';

@WebSocketGateway({
  cors: { origin: process.env.CORS_ORIGIN ?? 'http://localhost:3000' },
})
export class RealtimeGateway {
  @WebSocketServer()
  server!: Server;

  emitConversationUpdated(conversation: unknown): void {
    this.server?.emit('conversation.updated', serializeBigInt(conversation));
  }

  emitMessageCreated(conversationId: string, message: Message): void {
    this.server?.emit('message.created', {
      conversationId,
      message: serializeBigInt(message),
    });
  }

  emitOutboxUpdated(outbox: OutboxMessage): void {
    this.server?.emit('outbox.updated', serializeBigInt(outbox));
  }
}
