import { Module } from '@nestjs/common';
import { BootstrapService } from './bootstrap.service';
import { PrismaModule } from '../prisma/prisma.module';

@Module({
  imports: [PrismaModule],
  providers: [BootstrapService],
})
export class BootstrapModule {}
