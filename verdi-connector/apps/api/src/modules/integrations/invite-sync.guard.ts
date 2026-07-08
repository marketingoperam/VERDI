import {
  CanActivate,
  ExecutionContext,
  Injectable,
  UnauthorizedException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Request } from 'express';

@Injectable()
export class InviteSyncGuard implements CanActivate {
  constructor(private readonly config: ConfigService) {}

  canActivate(context: ExecutionContext): boolean {
    const expected = this.config.get<string>('INVITE_SYNC_SECRET', '').trim();
    if (!expected) {
      throw new UnauthorizedException('Invite sync is not configured');
    }
    const req = context.switchToHttp().getRequest<Request>();
    const provided = String(req.headers['x-invite-sync-secret'] ?? '').trim();
    if (!provided || provided !== expected) {
      throw new UnauthorizedException('Invalid invite sync secret');
    }
    return true;
  }
}
