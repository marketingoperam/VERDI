import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PrismaService } from '../../prisma/prisma.service';

export type InvitedAnalyticsItem = {
  leadId: string;
  conversationId: string;
  username: string | null;
  firstName: string | null;
  telegramUserId: string;
  invitedAt: string | null;
  source: string | null;
  sessionName: string | null;
  techTitle: string;
  conversationState: string;
  inboxInbound: number;
  inboxOutbound: number;
  inboxTotal: number;
  chatMessages: number;
  chatReactions: number;
  chatTotal: number;
  lastInboxAt: string | null;
  lastChatAt: string | null;
  hasChatActivity: boolean;
};

export type InvitedAnalyticsResponse = {
  total: number;
  withInboxActivity: number;
  withChatActivity: number;
  inboxMessagesTotal: number;
  chatMessagesTotal: number;
  shadowchatReachable: boolean;
  invitingReachable: boolean;
  mirrorUsername: string | null;
  items: InvitedAnalyticsItem[];
};

function normalizeUsername(raw?: string | null): string | null {
  if (!raw) return null;
  const username = raw.trim().replace(/^@/, '').toLowerCase();
  return username || null;
}

@Injectable()
export class AnalyticsService {
  private readonly logger = new Logger(AnalyticsService.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly config: ConfigService,
  ) {}

  private shadowchatBase(): string {
    return (this.config.get<string>('SHADOWCHAT_API_URL') ?? '').trim().replace(/\/$/, '');
  }

  private invitingBase(): string {
    return (this.config.get<string>('INVITING_API_URL') ?? '').trim().replace(/\/$/, '');
  }

  private async fetchJson<T>(url: string): Promise<T | null> {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(12000) });
      if (!res.ok) return null;
      return (await res.json()) as T;
    } catch (error) {
      this.logger.debug(`fetch failed ${url}: ${String(error)}`);
      return null;
    }
  }

  private async loadChatActivity(): Promise<{
    reachable: boolean;
    mirrorUsername: string | null;
    byUsername: Map<string, { messages: number; reactions: number; lastActiveAt: string | null }>;
    byUserId: Map<string, { messages: number; reactions: number; lastActiveAt: string | null }>;
  }> {
    const base = this.shadowchatBase();
    const empty = {
      reachable: false,
      mirrorUsername: null,
      byUsername: new Map(),
      byUserId: new Map(),
    };
    if (!base) return empty;

    type SummaryRow = { mirror_chat_id: number; mirror_username?: string };
    const summary = await this.fetchJson<SummaryRow[]>(`${base}/api/v1/activity/summary`);
    if (!summary?.length) return { ...empty, reachable: false };

    const preferred =
      summary.find((row) => (row.mirror_username ?? '').toLowerCase() === 'verdi114') ?? summary[0];
    const mirrorChatId = preferred.mirror_chat_id;
    const mirrorUsername = preferred.mirror_username ?? null;

    type ActivityRow = {
      telegram_user_id: number | string;
      username?: string;
      message_count?: number;
      reaction_count?: number;
      last_active_at?: string | null;
    };
    const rows = await this.fetchJson<ActivityRow[]>(
      `${base}/api/v1/activity?mirror_chat_id=${mirrorChatId}&sort=total`,
    );

    const byUsername = new Map<string, { messages: number; reactions: number; lastActiveAt: string | null }>();
    const byUserId = new Map<string, { messages: number; reactions: number; lastActiveAt: string | null }>();

    for (const row of rows ?? []) {
      const payload = {
        messages: Number(row.message_count ?? 0),
        reactions: Number(row.reaction_count ?? 0),
        lastActiveAt: row.last_active_at ?? null,
      };
      const username = normalizeUsername(row.username);
      if (username) byUsername.set(username, payload);
      if (row.telegram_user_id != null) byUserId.set(String(row.telegram_user_id), payload);
    }

    return { reachable: true, mirrorUsername, byUsername, byUserId };
  }

  async invitedActivity(sort = 'total'): Promise<InvitedAnalyticsResponse> {
    const chatActivity = await this.loadChatActivity();

    const techAccounts = await this.prisma.technicalAccount.findMany({
      select: { telegramUserId: true, sessionName: true, title: true, phoneMasked: true },
    });
    const selfUserIds = new Set(
      techAccounts
        .map((a) => (a.telegramUserId != null ? String(a.telegramUserId) : null))
        .filter(Boolean) as string[],
    );
    const selfUsernames = new Set(
      techAccounts
        .flatMap((a) => [a.sessionName, a.title, a.phoneMasked])
        .map((v) => normalizeUsername(v))
        .filter(Boolean) as string[],
    );
    // account title like @andf1n
    for (const a of techAccounts) {
      const fromTitle = normalizeUsername(a.title?.replace(/^@/, ''));
      if (fromTitle) selfUsernames.add(fromTitle);
    }
    selfUserIds.add('777000');
    selfUsernames.add('telegram');
    selfUsernames.add('andf1n');

    const conversations = await this.prisma.conversation.findMany({
      include: {
        lead: true,
        technicalAccount: true,
        messages: {
          select: { direction: true, createdAt: true },
        },
      },
      orderBy: [{ updatedAt: 'desc' }],
    });

    const items: InvitedAnalyticsItem[] = conversations
      .filter((conversation) => {
        const lead = conversation.lead;
        const uid = String(lead.telegramUserId);
        const uname = normalizeUsername(lead.username);
        if (selfUserIds.has(uid)) return false;
        if (uname && selfUsernames.has(uname)) return false;
        return true;
      })
      .map((conversation) => {
      const lead = conversation.lead;
      const inboxInbound = conversation.messages.filter((m) => m.direction === 'inbound').length;
      const inboxOutbound = conversation.messages.filter((m) => m.direction === 'outbound').length;
      const inboxTotal = inboxInbound + inboxOutbound;

      const lastInbound = conversation.lastInboundAt ?? conversation.messages
        .filter((m) => m.direction === 'inbound')
        .map((m) => m.createdAt)
        .sort((a, b) => b.getTime() - a.getTime())[0];
      const lastOutbound = conversation.lastOutboundAt ?? conversation.messages
        .filter((m) => m.direction === 'outbound')
        .map((m) => m.createdAt)
        .sort((a, b) => b.getTime() - a.getTime())[0];
      const lastInboxAt = [lastInbound, lastOutbound].filter(Boolean).sort(
        (a, b) => (b as Date).getTime() - (a as Date).getTime(),
      )[0];

      const username = normalizeUsername(lead.username);
      const chat =
        (username && chatActivity.byUsername.get(username)) ||
        chatActivity.byUserId.get(String(lead.telegramUserId)) ||
        null;

      const chatMessages = chat?.messages ?? 0;
      const chatReactions = chat?.reactions ?? 0;
      const chatTotal = chatMessages + chatReactions;

      return {
        leadId: lead.id,
        conversationId: conversation.id,
        username: lead.username,
        firstName: lead.firstName,
        telegramUserId: String(lead.telegramUserId),
        invitedAt: lead.invitedAt?.toISOString() ?? null,
        source: lead.source,
        sessionName: conversation.technicalAccount.sessionName,
        techTitle: conversation.technicalAccount.title,
        conversationState: conversation.state,
        inboxInbound,
        inboxOutbound,
        inboxTotal,
        chatMessages,
        chatReactions,
        chatTotal,
        lastInboxAt: lastInboxAt ? lastInboxAt.toISOString() : null,
        lastChatAt: chat?.lastActiveAt ?? null,
        hasChatActivity: chatTotal > 0,
      };
    });

    const sorters: Record<string, (a: InvitedAnalyticsItem, b: InvitedAnalyticsItem) => number> = {
      username: (a, b) => (a.username ?? '').localeCompare(b.username ?? ''),
      invited_at: (a, b) => (b.invitedAt ?? '').localeCompare(a.invitedAt ?? ''),
      inbox: (a, b) => b.inboxTotal - a.inboxTotal || (a.username ?? '').localeCompare(b.username ?? ''),
      chat: (a, b) => b.chatTotal - a.chatTotal || (a.username ?? '').localeCompare(b.username ?? ''),
      total: (a, b) =>
        b.inboxTotal + b.chatTotal - (a.inboxTotal + a.chatTotal) ||
        (a.username ?? '').localeCompare(b.username ?? ''),
    };
    items.sort(sorters[sort] ?? sorters.total);

    return {
      total: items.length,
      withInboxActivity: items.filter((i) => i.inboxTotal > 0).length,
      withChatActivity: items.filter((i) => i.hasChatActivity).length,
      inboxMessagesTotal: items.reduce((sum, i) => sum + i.inboxTotal, 0),
      chatMessagesTotal: items.reduce((sum, i) => sum + i.chatMessages, 0),
      shadowchatReachable: chatActivity.reachable,
      invitingReachable: Boolean(this.invitingBase()),
      mirrorUsername: chatActivity.mirrorUsername,
      items,
    };
  }
}
