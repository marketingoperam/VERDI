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

    // Ensure technical account exists even if DB already has an operator.
    const technicalAccounts = [
      {
        title: 'tech_13309563469',
        sessionName: 'tech_13309563469',
        phoneMasked: '+1330***3469',
        status: 'active' as const,
        mode: 'reply_only' as const,
      },
    ];

    for (const acc of technicalAccounts) {
      const existing = await this.prisma.technicalAccount.findFirst({
        where: { sessionName: acc.sessionName },
      });
      if (existing) continue;
      await this.prisma.technicalAccount.create({ data: acc });
    }

    await this.prisma.template.createMany({
      data: [
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
      ],
    });
  }
}
