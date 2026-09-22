// src/domain/memoryMocks.ts

export type MemoryStatus = 'ACTIVE' | 'PROPOSED' | 'SUPERSEDED' | 'EXPIRED' | 'FORGOTTEN';
export type MemoryProvenance = 'USER_EXPLICIT' | 'USER_CONFIRMED' | 'AI_HYPOTHESIS' | 'SYSTEM_OBSERVED';
export type MemoryCategory = 'PREFERENCE' | 'GOAL' | 'ROUTINE' | 'DECISION';
export type MemorySubject = 'Erick' | 'Ana' | 'Erick + Ana' | 'Household';
export type MemoryVisibility = 'PERSONAL' | 'HOUSEHOLD';
export type HistoryReason = 'UPDATED' | 'EXPIRED' | 'FORGOTTEN';

export interface MemoryClaim {
  id: string;
  statement: string;
  category: MemoryCategory;
  status: MemoryStatus;
  provenance: MemoryProvenance;
  sourceContext: string;
  createdAt: string;
  subjectLabel: MemorySubject;
  visibility: MemoryVisibility;
  supersededBy?: string;
  supersededByStatement?: string;
  replaces?: string;
  replacesStatement?: string;
  historyReason?: HistoryReason;
  historyReasonText?: string;
  inferredConfidence?: string;
}

export const memoryMocks: MemoryClaim[] = [
  // 1. Active Confirmed Preference (Personal)
  {
    id: 'm-1',
    statement: 'I prefer Mediterranean and Latin food.',
    category: 'PREFERENCE',
    status: 'ACTIVE',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Sep 10, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
  },

  // 2. Active Updated Preference (Personal)
  {
    id: 'm-3',
    statement: 'I only dislike canned tuna. Fresh tuna is fine.',
    category: 'PREFERENCE',
    status: 'ACTIVE',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Sep 15, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    replaces: 'm-2',
    replacesStatement: 'I dislike all tuna.',
  },

  // 3. Active Goal (Personal)
  {
    id: 'm-4',
    statement: 'I want to exercise three times per week.',
    category: 'GOAL',
    status: 'ACTIVE',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Aug 20, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
  },

  // 4. Active Routine (Personal)
  {
    id: 'm-5',
    statement: 'I usually train Tuesday and Thursday evenings.',
    category: 'ROUTINE',
    status: 'ACTIVE',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Aug 20, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
  },

  // 5. Suggested (AI Hypothesis - Needs Confirmation)
  {
    id: 'm-6',
    statement: 'You often choose vegetarian dinners.',
    category: 'PREFERENCE',
    status: 'PROPOSED',
    provenance: 'AI_HYPOTHESIS',
    sourceContext: 'Observed from 6 recent dinner logs in Mealie',
    createdAt: 'Sep 18, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    inferredConfidence: 'High (85%)',
  },

  // 6. Active Shared Routine (Household)
  {
    id: 'm-7',
    statement: 'Our family normally eats dinner around 19:00.',
    category: 'ROUTINE',
    status: 'ACTIVE',
    provenance: 'SYSTEM_OBSERVED',
    sourceContext: 'Household routine & dining room presence',
    createdAt: 'Jul 10, 2026',
    subjectLabel: 'Household',
    visibility: 'HOUSEHOLD',
  },

  // 7. Active Shared Decision (Household)
  {
    id: 'm-8',
    statement: 'Erick and Ana decided not to move house this year.',
    category: 'DECISION',
    status: 'ACTIVE',
    provenance: 'USER_CONFIRMED',
    sourceContext: 'Shared Family Planning conversation',
    createdAt: 'Jun 15, 2026',
    subjectLabel: 'Erick + Ana',
    visibility: 'HOUSEHOLD',
  },

  // --- HISTORY / NO LONGER USED WITH CLEAR SEMANTICS ---

  // 8. Superseded / Replaced Memory
  {
    id: 'm-2',
    statement: 'I dislike all tuna.',
    category: 'PREFERENCE',
    status: 'SUPERSEDED',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Sep 10, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    supersededBy: 'm-3',
    supersededByStatement: 'I only dislike canned tuna. Fresh tuna is fine.',
    historyReason: 'UPDATED',
    historyReasonText: 'Replaced on Sep 15 with a more specific preference for fresh vs canned tuna.',
  },

  // 9. Expired Memory (Time-bound routine)
  {
    id: 'm-9',
    statement: 'Summer outdoor running schedule on Monday mornings at 06:30.',
    category: 'ROUTINE',
    status: 'EXPIRED',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Seasonal Training Routine',
    createdAt: 'Jun 01, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    historyReason: 'EXPIRED',
    historyReasonText: 'Expired on Aug 31 at the end of summer training cycle.',
  },

  // 10. Explicitly Forgotten Memory
  {
    id: 'm-10',
    statement: 'Avoid all caffeine after 14:00.',
    category: 'PREFERENCE',
    status: 'FORGOTTEN',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Conversation with Olin',
    createdAt: 'Jul 14, 2026',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    historyReason: 'FORGOTTEN',
    historyReasonText: 'Forgotten on Sep 12 by Erick.',
  },
];

// Today Attention Scenarios for interactive demonstration & validation
export type TodayAttentionScenarioId = 'QUIET' | 'SUGGESTION' | 'CORRECTION' | 'SHARED';

export interface TodayAttentionItem {
  id: string;
  type: 'SUGGESTION' | 'CORRECTION' | 'SHARED';
  badgeLabel: string;
  title: string;
  statement: string;
  explanation: string;
  previousStatement?: string;
  subjectLabel: MemorySubject;
  visibility: MemoryVisibility;
  provenance: MemoryProvenance;
  sourceContext: string;
  suggestedActionLabel?: string;
}

export const todayAttentionMocks: Record<Exclude<TodayAttentionScenarioId, 'QUIET'>, TodayAttentionItem> = {
  SUGGESTION: {
    id: 'att-sug-1',
    type: 'SUGGESTION',
    badgeLabel: 'Olin noticed',
    title: 'New pattern detected',
    statement: "You've been choosing vegetarian dinners more often.",
    explanation: 'Based on your last 6 meal logs in Mealie.',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    provenance: 'AI_HYPOTHESIS',
    sourceContext: 'Meal logs & dining choices',
    suggestedActionLabel: 'Remember this',
  },
  CORRECTION: {
    id: 'att-corr-1',
    type: 'CORRECTION',
    badgeLabel: 'Update a preference?',
    title: 'Preference nuance detected',
    statement: 'Fresh tuna is fine. I only dislike canned tuna.',
    previousStatement: 'I dislike all tuna.',
    explanation: 'Olin noticed you mentioned enjoying seared tuna steak yesterday.',
    subjectLabel: 'Erick',
    visibility: 'PERSONAL',
    provenance: 'USER_EXPLICIT',
    sourceContext: 'Yesterday evening conversation',
    suggestedActionLabel: 'Accept update',
  },
  SHARED: {
    id: 'att-shared-1',
    type: 'SHARED',
    badgeLabel: 'Shared family memory',
    title: 'Waiting for Ana',
    statement: 'Erick and Ana decided not to move this year.',
    explanation: 'Shared decision recorded by Erick. Awaiting Ana’s review before confirming household context.',
    subjectLabel: 'Erick + Ana',
    visibility: 'HOUSEHOLD',
    provenance: 'USER_CONFIRMED',
    sourceContext: 'Shared Family Planning',
    suggestedActionLabel: 'Review decision',
  },
};
