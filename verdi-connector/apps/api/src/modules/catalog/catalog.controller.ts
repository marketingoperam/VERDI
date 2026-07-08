import { Body, Controller, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { JwtAuthGuard } from '../auth/jwt-auth.guard';
import { serializeBigInt } from '../../common/utils/text.util';
import { RiskControlService } from '../risk-control/risk-control.service';

@Controller('templates')
@UseGuards(JwtAuthGuard)
export class TemplatesController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async list() {
    const rows = await this.prisma.template.findMany({
      where: { isActive: true },
      orderBy: { createdAt: 'asc' },
    });
    // One chip per title (dedupe legacy seeded duplicates).
    const seen = new Set<string>();
    return rows.filter((row) => {
      const key = row.title.trim().toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
}

@Controller('technical-accounts')
@UseGuards(JwtAuthGuard)
export class TechnicalAccountsController {
  constructor(
    private readonly prisma: PrismaService,
    private readonly riskControl: RiskControlService,
  ) {}

  @Get()
  async list() {
    return serializeBigInt(await this.prisma.technicalAccount.findMany());
  }

  @Patch(':id/pause')
  async pause(@Param('id') id: string) {
    await this.prisma.technicalAccount.update({
      where: { id },
      data: { status: 'paused' },
    });
    await this.riskControl.recordEvent({
      technicalAccountId: id,
      type: 'account_pause',
      severity: 'medium',
      delta: 5,
    });
    return { ok: true };
  }

  @Patch(':id/resume')
  async resume(@Param('id') id: string) {
    await this.prisma.technicalAccount.update({
      where: { id },
      data: { status: 'active' },
    });
    return { ok: true };
  }
}

@Controller('operators')
@UseGuards(JwtAuthGuard)
export class OperatorsController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async list() {
    return this.prisma.operator.findMany({
      where: { isActive: true },
      select: { id: true, email: true, role: true, displayName: true },
    });
  }
}

@Controller('audit-log')
@UseGuards(JwtAuthGuard)
export class AuditLogController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async list() {
    return this.prisma.auditLog.findMany({ orderBy: { createdAt: 'desc' }, take: 100 });
  }
}
