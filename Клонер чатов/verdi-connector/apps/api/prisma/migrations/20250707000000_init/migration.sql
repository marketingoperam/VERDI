-- CreateEnum
CREATE TYPE "OperatorRole" AS ENUM ('admin', 'operator', 'supervisor');
CREATE TYPE "TechnicalAccountStatus" AS ENUM ('active', 'paused', 'limited', 'banned');
CREATE TYPE "TechnicalAccountMode" AS ENUM ('reply_only', 'controlled_initiation', 'full_manual');
CREATE TYPE "ConversationState" AS ENUM ('new', 'active', 'awaiting_operator', 'awaiting_user', 'moderation', 'transferred', 'closed');
CREATE TYPE "FirstContactType" AS ENUM ('none', 'manual', 'template', 'automation');
CREATE TYPE "MessageDirection" AS ENUM ('inbound', 'outbound', 'internal_note', 'system');
CREATE TYPE "SenderType" AS ENUM ('lead', 'operator', 'system', 'technical_account');
CREATE TYPE "DeliveryStatus" AS ENUM ('received', 'pending', 'sent', 'failed', 'blocked');
CREATE TYPE "OutboxMessageType" AS ENUM ('reply', 'initiation', 'template_reply', 'command_reply');
CREATE TYPE "PolicyDecision" AS ENUM ('pending', 'allowed', 'blocked');
CREATE TYPE "OutboxSendStatus" AS ENUM ('pending', 'queued', 'sent', 'failed');
CREATE TYPE "ModerationStatus" AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE "RiskEventType" AS ENUM ('spam_report_risk', 'duplicate_pattern', 'high_outbound_ratio', 'stop_request', 'delivery_failure', 'account_pause');
CREATE TYPE "RiskSeverity" AS ENUM ('low', 'medium', 'high');
CREATE TYPE "AuditActorType" AS ENUM ('operator', 'system');
CREATE TYPE "StopListSource" AS ENUM ('manual', 'user_request', 'policy');

-- CreateTable
CREATE TABLE "Operator" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "role" "OperatorRole" NOT NULL DEFAULT 'operator',
    "displayName" TEXT NOT NULL,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Operator_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "TechnicalAccount" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "phoneMasked" TEXT,
    "telegramUserId" BIGINT,
    "status" "TechnicalAccountStatus" NOT NULL DEFAULT 'active',
    "mode" "TechnicalAccountMode" NOT NULL DEFAULT 'reply_only',
    "warmupScore" INTEGER NOT NULL DEFAULT 0,
    "riskScore" INTEGER NOT NULL DEFAULT 0,
    "dailyInitiationLimit" INTEGER NOT NULL DEFAULT 20,
    "hourlyInitiationLimit" INTEGER NOT NULL DEFAULT 5,
    "dailyReplyLimit" INTEGER NOT NULL DEFAULT 200,
    "sessionEncrypted" TEXT,
    "lastActiveAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "TechnicalAccount_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Lead" (
    "id" TEXT NOT NULL,
    "telegramUserId" BIGINT NOT NULL,
    "username" TEXT,
    "firstName" TEXT,
    "lastName" TEXT,
    "source" TEXT,
    "expectedContact" BOOLEAN NOT NULL DEFAULT false,
    "invitedAt" TIMESTAMP(3),
    "activatedAt" TIMESTAMP(3),
    "tags" JSONB NOT NULL DEFAULT '[]',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Lead_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Conversation" (
    "id" TEXT NOT NULL,
    "leadId" TEXT NOT NULL,
    "technicalAccountId" TEXT NOT NULL,
    "assignedOperatorId" TEXT,
    "state" "ConversationState" NOT NULL DEFAULT 'new',
    "firstContactType" "FirstContactType" NOT NULL DEFAULT 'none',
    "externalChatId" TEXT,
    "lastInboundAt" TIMESTAMP(3),
    "lastOutboundAt" TIMESTAMP(3),
    "unreadCount" INTEGER NOT NULL DEFAULT 0,
    "isStopListed" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Conversation_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Message" (
    "id" TEXT NOT NULL,
    "conversationId" TEXT NOT NULL,
    "direction" "MessageDirection" NOT NULL,
    "senderType" "SenderType" NOT NULL,
    "senderId" TEXT,
    "body" TEXT NOT NULL,
    "normalizedBody" TEXT NOT NULL,
    "telegramMessageId" TEXT,
    "deliveryStatus" "DeliveryStatus" NOT NULL DEFAULT 'received',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Message_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "OutboxMessage" (
    "id" TEXT NOT NULL,
    "conversationId" TEXT NOT NULL,
    "operatorId" TEXT,
    "technicalAccountId" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "normalizedBody" TEXT NOT NULL,
    "messageType" "OutboxMessageType" NOT NULL,
    "policyDecision" "PolicyDecision" NOT NULL DEFAULT 'pending',
    "blockReason" TEXT,
    "sendStatus" "OutboxSendStatus" NOT NULL DEFAULT 'pending',
    "retryCount" INTEGER NOT NULL DEFAULT 0,
    "scheduledAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "sentAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "OutboxMessage_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "Template" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "Template_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "ModerationCase" (
    "id" TEXT NOT NULL,
    "conversationId" TEXT NOT NULL,
    "status" "ModerationStatus" NOT NULL DEFAULT 'pending',
    "reason" TEXT,
    "reviewedById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "ModerationCase_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "RiskEvent" (
    "id" TEXT NOT NULL,
    "technicalAccountId" TEXT NOT NULL,
    "conversationId" TEXT,
    "type" "RiskEventType" NOT NULL,
    "severity" "RiskSeverity" NOT NULL,
    "meta" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "RiskEvent_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuditLog" (
    "id" TEXT NOT NULL,
    "actorType" "AuditActorType" NOT NULL,
    "actorId" TEXT,
    "action" TEXT NOT NULL,
    "entityType" TEXT NOT NULL,
    "entityId" TEXT NOT NULL,
    "meta" JSONB NOT NULL DEFAULT '{}',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AuditLog_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "StopListEntry" (
    "id" TEXT NOT NULL,
    "leadId" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "source" "StopListSource" NOT NULL,
    "createdById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "StopListEntry_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Operator_email_key" ON "Operator"("email");
CREATE UNIQUE INDEX "TechnicalAccount_telegramUserId_key" ON "TechnicalAccount"("telegramUserId");
CREATE UNIQUE INDEX "Lead_telegramUserId_key" ON "Lead"("telegramUserId");
CREATE UNIQUE INDEX "Conversation_leadId_technicalAccountId_key" ON "Conversation"("leadId", "technicalAccountId");
CREATE INDEX "Conversation_state_idx" ON "Conversation"("state");
CREATE INDEX "Conversation_assignedOperatorId_idx" ON "Conversation"("assignedOperatorId");
CREATE INDEX "Message_conversationId_createdAt_idx" ON "Message"("conversationId", "createdAt");
CREATE INDEX "OutboxMessage_sendStatus_scheduledAt_idx" ON "OutboxMessage"("sendStatus", "scheduledAt");
CREATE INDEX "AuditLog_entityType_entityId_idx" ON "AuditLog"("entityType", "entityId");
CREATE INDEX "AuditLog_createdAt_idx" ON "AuditLog"("createdAt");
CREATE UNIQUE INDEX "StopListEntry_leadId_key" ON "StopListEntry"("leadId");

-- AddForeignKey
ALTER TABLE "Conversation" ADD CONSTRAINT "Conversation_leadId_fkey" FOREIGN KEY ("leadId") REFERENCES "Lead"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "Conversation" ADD CONSTRAINT "Conversation_technicalAccountId_fkey" FOREIGN KEY ("technicalAccountId") REFERENCES "TechnicalAccount"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "Conversation" ADD CONSTRAINT "Conversation_assignedOperatorId_fkey" FOREIGN KEY ("assignedOperatorId") REFERENCES "Operator"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "Message" ADD CONSTRAINT "Message_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "OutboxMessage" ADD CONSTRAINT "OutboxMessage_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "OutboxMessage" ADD CONSTRAINT "OutboxMessage_operatorId_fkey" FOREIGN KEY ("operatorId") REFERENCES "Operator"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "OutboxMessage" ADD CONSTRAINT "OutboxMessage_technicalAccountId_fkey" FOREIGN KEY ("technicalAccountId") REFERENCES "TechnicalAccount"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "ModerationCase" ADD CONSTRAINT "ModerationCase_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "ModerationCase" ADD CONSTRAINT "ModerationCase_reviewedById_fkey" FOREIGN KEY ("reviewedById") REFERENCES "Operator"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "RiskEvent" ADD CONSTRAINT "RiskEvent_technicalAccountId_fkey" FOREIGN KEY ("technicalAccountId") REFERENCES "TechnicalAccount"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "RiskEvent" ADD CONSTRAINT "RiskEvent_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "Conversation"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "StopListEntry" ADD CONSTRAINT "StopListEntry_leadId_fkey" FOREIGN KEY ("leadId") REFERENCES "Lead"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "StopListEntry" ADD CONSTRAINT "StopListEntry_createdById_fkey" FOREIGN KEY ("createdById") REFERENCES "Operator"("id") ON DELETE SET NULL ON UPDATE CASCADE;
