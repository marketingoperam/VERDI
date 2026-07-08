import { Module } from '@nestjs/common';
import { PolicyEngineService } from './policy-engine.service';

@Module({
  providers: [PolicyEngineService],
  exports: [PolicyEngineService],
})
export class PolicyModule {}
