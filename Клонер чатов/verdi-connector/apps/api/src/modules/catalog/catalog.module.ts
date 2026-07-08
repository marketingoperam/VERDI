import { Module } from '@nestjs/common';
import {
  AuditLogController,
  OperatorsController,
  TechnicalAccountsController,
  TemplatesController,
} from './catalog.controller';
import { RiskControlModule } from '../risk-control/risk-control.module';

@Module({
  imports: [RiskControlModule],
  controllers: [
    TemplatesController,
    TechnicalAccountsController,
    OperatorsController,
    AuditLogController,
  ],
})
export class CatalogModule {}
