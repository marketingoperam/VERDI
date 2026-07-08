import { Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as bcrypt from 'bcrypt';
import { PrismaService } from '../../prisma/prisma.service';

@Injectable()
export class AuthService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly jwt: JwtService,
  ) {}

  async login(email: string, password: string) {
    const operator = await this.prisma.operator.findUnique({ where: { email } });
    if (!operator || !operator.isActive) {
      throw new UnauthorizedException('Invalid credentials');
    }
    const ok = await bcrypt.compare(password, operator.passwordHash);
    if (!ok) throw new UnauthorizedException('Invalid credentials');

    const token = await this.jwt.signAsync({
      sub: operator.id,
      email: operator.email,
      role: operator.role,
    });

    return {
      accessToken: token,
      operator: {
        id: operator.id,
        email: operator.email,
        role: operator.role,
        displayName: operator.displayName,
      },
    };
  }
}
