import { Injectable, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import * as bcrypt from 'bcrypt';
import { PrismaService } from '../prisma/prisma.service';

@Injectable()
export class BootstrapService implements OnModuleInit {
  constructor(
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  async onModuleInit(): Promise<void> {
    const email = this.config.get<string>('SEED_OPERATOR_EMAIL', 'andf1n@verdi.local');
    const password = this.config.get<string>('SEED_OPERATOR_PASSWORD', 'admin123');
    const displayName = this.config.get<string>('SEED_OPERATOR_NAME', '@andf1n');
    const passwordHash = await bcrypt.hash(password, 12);

    const existingOperator = await this.prisma.operator.findFirst();
    if (existingOperator) {
      if (
        existingOperator.email !== email ||
        existingOperator.displayName !== displayName ||
        existingOperator.passwordHash !== passwordHash
      ) {
        await this.prisma.operator.update({
          where: { id: existingOperator.id },
          data: { email, displayName, passwordHash },
        });
      }
    } else {
      await this.prisma.operator.create({
        data: {
          email,
          passwordHash,
          displayName,
          role: 'admin',
        },
      });
    }

    const sessions = this.resolveSessions();
    for (const sessionName of sessions) {
      const title =
        sessionName === 'listener_main'
          ? '@andf1n'
          : sessionName === 'tech_13309563469'
            ? '@samyi_classny_paren'
            : sessionName;
      const phoneMasked =
        sessionName === 'listener_main'
          ? 'andf1n'
          : sessionName === 'tech_13309563469'
            ? 'samyi_classny_paren'
            : sessionName;
      const telegramUserId =
        sessionName === 'listener_main' ? BigInt('8228313419') : undefined;

      const existing = await this.prisma.technicalAccount.findFirst({
        where: { sessionName },
      });
      if (existing) {
        await this.prisma.technicalAccount.update({
          where: { id: existing.id },
          data: {
            title,
            phoneMasked,
            telegramUserId: telegramUserId ?? existing.telegramUserId,
            status: 'active',
          },
        });
      } else {
        await this.prisma.technicalAccount.create({
          data: {
            title,
            sessionName,
            phoneMasked,
            telegramUserId,
            status: 'active',
            mode: 'reply_only',
          },
        });
      }
    }

    const defaultTemplates = [
      {
        title: 'Приветствие',
        category: 'onboarding',
        body: 'Здравствуйте! Я на связи, чем могу помочь?',
      },
      {
        title: 'Уточнение',
        category: 'support',
        body: 'Спасибо за сообщение, уточню детали и вернусь с ответом.',
      },
    ];

    for (const template of defaultTemplates) {
      const existing = await this.prisma.template.findFirst({
        where: { title: template.title },
        orderBy: { createdAt: 'asc' },
      });
      if (!existing) {
        await this.prisma.template.create({ data: template });
        continue;
      }
      await this.prisma.template.update({
        where: { id: existing.id },
        data: { isActive: true, body: template.body, category: template.category },
      });
      await this.prisma.template.updateMany({
        where: { title: template.title, id: { not: existing.id } },
        data: { isActive: false },
      });
    }
  }

  private resolveSessions(): string[] {
    const multi = this.config.get<string>('TELEGRAM_SESSIONS', '');
    if (multi.trim()) {
      return [...new Set(multi.split(',').map((s) => s.trim()).filter(Boolean))];
    }
    return [this.config.get<string>('TELEGRAM_SESSION', 'listener_main')];
  }
}
