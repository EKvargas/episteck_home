// src/domain/calendarMocks.ts

export type CalendarSourceId = 
  | 'erick-work' 
  | 'erick-personal' 
  | 'ana-google' 
  | 'ana-icloud' 
  | 'household';

export type CalendarProvider = 'google' | 'apple' | 'microsoft' | 'olin';

export interface CalendarAccount {
  id: CalendarSourceId;
  name: string;
  owner: 'Erick' | 'Ana' | 'Family';
  provider: CalendarProvider;
  accountEmail: string;
  color: string;
  badgeBg: string;
  badgeBorder: string;
  lastSynced: string;
  privacyDefault: 'FULL_DETAILS' | 'BUSY_ONLY';
  description: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  maskedTitle?: string;
  startTime: string; // e.g. "09:00"
  endTime: string;   // e.g. "10:30"
  durationMinutes: number;
  date: string;      // e.g. "2026-09-18"
  sourceId: CalendarSourceId;
  owner: 'Erick' | 'Ana' | 'Joint';
  location?: string;
  attendees?: string[];
  notes?: string;
  isCareLink?: boolean;
  isConflict?: boolean;
  category: 'work' | 'personal' | 'care' | 'family' | 'wellness';
}

export interface CalendarInsight {
  id: string;
  type: 'CONFLICT' | 'SYNERGY' | 'REMINDER';
  title: string;
  message: string;
  affectedEventIds: string[];
  actionLabel?: string;
}

export const calendarAccountsMock: Record<CalendarSourceId, CalendarAccount> = {
  'erick-work': {
    id: 'erick-work',
    name: "Erick's Work Calendar",
    owner: 'Erick',
    provider: 'microsoft',
    accountEmail: 'erick.vargas@episteck.com',
    color: '#3b82f6', // blue
    badgeBg: 'rgba(59, 130, 246, 0.12)',
    badgeBorder: 'rgba(59, 130, 246, 0.3)',
    lastSynced: '2 minutes ago',
    privacyDefault: 'BUSY_ONLY',
    description: 'Corporate Exchange / Google Workspace with sprint planning & client syncs',
  },
  'erick-personal': {
    id: 'erick-personal',
    name: "Erick's Gmail",
    owner: 'Erick',
    provider: 'google',
    accountEmail: 'erick.personal@gmail.com',
    color: '#f97316', // orange
    badgeBg: 'rgba(249, 115, 22, 0.12)',
    badgeBorder: 'rgba(249, 115, 22, 0.3)',
    lastSynced: '5 minutes ago',
    privacyDefault: 'FULL_DETAILS',
    description: 'Personal Google Calendar for training, health, and personal errands',
  },
  'ana-google': {
    id: 'ana-google',
    name: "Ana's Gmail",
    owner: 'Ana',
    provider: 'google',
    accountEmail: 'ana.vargas.design@gmail.com',
    color: '#a855f7', // purple
    badgeBg: 'rgba(168, 85, 247, 0.12)',
    badgeBorder: 'rgba(168, 85, 247, 0.3)',
    lastSynced: 'Just now',
    privacyDefault: 'FULL_DETAILS',
    description: 'Design consulting projects, student reviews, and personal schedule',
  },
  'ana-icloud': {
    id: 'ana-icloud',
    name: "Ana's iPhone (iCloud)",
    owner: 'Ana',
    provider: 'apple',
    accountEmail: 'ana.vargas@icloud.com',
    color: '#10b981', // emerald
    badgeBg: 'rgba(16, 185, 129, 0.12)',
    badgeBorder: 'rgba(16, 185, 129, 0.3)',
    lastSynced: '8 minutes ago',
    privacyDefault: 'FULL_DETAILS',
    description: 'Apple CalDAV calendar synced with iOS Reminders and Clinic passes',
  },
  'household': {
    id: 'household',
    name: 'Vargas Household (Circle)',
    owner: 'Family',
    provider: 'olin',
    accountEmail: 'vargas-home@olin.local',
    color: '#c4643c', // olin terracotta
    badgeBg: 'rgba(196, 100, 60, 0.12)',
    badgeBorder: 'rgba(196, 100, 60, 0.3)',
    lastSynced: 'Realtime internal ledger',
    privacyDefault: 'FULL_DETAILS',
    description: 'Shared family dinners, home maintenance, trips, and visitor access',
  },
};

export const calendarEventsMock: CalendarEvent[] = [
  // ─── ERICK'S WORK (Google Workspace / Exchange) ───
  {
    id: 'cal-ev-1',
    title: 'Work Sync with Architecture Core',
    maskedTitle: 'Erick · Busy (Work Meeting)',
    startTime: '10:00',
    endTime: '11:15',
    durationMinutes: 75,
    date: '2026-09-18',
    sourceId: 'erick-work',
    owner: 'Erick',
    location: 'Virtual Room #4 · Episteck Core',
    attendees: ['Architecture Team (4)', 'Platform Lead'],
    notes: 'Q4 deployment roadmap & memory infrastructure review.',
    category: 'work',
  },
  {
    id: 'cal-ev-2',
    title: 'Client Technical Debrief',
    maskedTitle: 'Erick · Busy (Confidential Call)',
    startTime: '14:00',
    endTime: '14:45',
    durationMinutes: 45,
    date: '2026-09-18',
    sourceId: 'erick-work',
    owner: 'Erick',
    location: 'Teams Call',
    attendees: ['Enterprise Delivery Partner'],
    notes: 'Confidential client session.',
    isConflict: true, // Overlaps with escorting Ana to clinic!
    category: 'work',
  },
  {
    id: 'cal-ev-3',
    title: 'Sprint Wrap & Async Retro',
    maskedTitle: 'Erick · Busy (Work)',
    startTime: '16:30',
    endTime: '17:15',
    durationMinutes: 45,
    date: '2026-09-18',
    sourceId: 'erick-work',
    owner: 'Erick',
    location: 'Slack Huddle',
    category: 'work',
  },

  // ─── ERICK'S PERSONAL GMAIL ───
  {
    id: 'cal-ev-4',
    title: 'Morning Mobility & Cardio',
    startTime: '07:00',
    endTime: '08:00',
    durationMinutes: 60,
    date: '2026-09-18',
    sourceId: 'erick-personal',
    owner: 'Erick',
    location: 'Home Gym / Garden',
    notes: 'Zone 2 running + shoulder stability circuit.',
    category: 'wellness',
  },
  {
    id: 'cal-ev-5',
    title: 'Drop off car for seasonal service',
    startTime: '12:00',
    endTime: '12:30',
    durationMinutes: 30,
    date: '2026-09-18',
    sourceId: 'erick-personal',
    owner: 'Erick',
    location: 'AutoCare Center Ashburn',
    category: 'personal',
  },

  // ─── ANA'S GMAIL ───
  {
    id: 'cal-ev-6',
    title: 'Design Studio Consultation',
    startTime: '09:30',
    endTime: '11:00',
    durationMinutes: 90,
    date: '2026-09-18',
    sourceId: 'ana-google',
    owner: 'Ana',
    location: 'Studio Loft / Zoom',
    attendees: ['Elena Rostova', 'Interior Collective'],
    notes: 'Reviewing Scandinavian minimalist finishes for residential project.',
    category: 'work',
  },
  {
    id: 'cal-ev-7',
    title: 'Ceramic Glazing Workshop',
    startTime: '16:00',
    endTime: '17:30',
    durationMinutes: 90,
    date: '2026-09-18',
    sourceId: 'ana-google',
    owner: 'Ana',
    location: 'Pottery Guild Center',
    category: 'personal',
  },

  // ─── ANA'S IPHONE (iCloud / Apple CalDAV) ───
  {
    id: 'cal-ev-8',
    title: 'Dr. Weber Consultation & Ultrasound',
    startTime: '14:00',
    endTime: '15:15',
    durationMinutes: 75,
    date: '2026-09-18',
    sourceId: 'ana-icloud',
    owner: 'Ana',
    location: 'Maternal & Wellness Clinic, Room 302',
    attendees: ['Dr. Weber', 'Erick (Care Escort)'],
    notes: 'Active care consent link active. Ultrasound checkup.',
    isCareLink: true,
    isConflict: true,
    category: 'care',
  },
  {
    id: 'cal-ev-9',
    title: 'Prescription pickup at Ashburn Pharmacy',
    startTime: '15:30',
    endTime: '15:45',
    durationMinutes: 15,
    date: '2026-09-18',
    sourceId: 'ana-icloud',
    owner: 'Ana',
    location: 'Ashburn Pharmacy Drive-thru',
    category: 'care',
  },

  // ─── VARGAS HOUSEHOLD SHARED (Olin Circle Calendar) ───
  {
    id: 'cal-ev-10',
    title: 'Family Dinner: Wild Baked Salmon & Asparagus',
    startTime: '18:30',
    endTime: '19:45',
    durationMinutes: 75,
    date: '2026-09-18',
    sourceId: 'household',
    owner: 'Joint',
    location: 'Dining Room',
    attendees: ['Erick', 'Ana'],
    notes: 'Mealie recipe synchronized. Oven preheats at 17:45.',
    category: 'family',
  },
  {
    id: 'cal-ev-11',
    title: 'Saturday Farmers Market & Produce Restock',
    startTime: '09:00',
    endTime: '10:30',
    durationMinutes: 90,
    date: '2026-09-19',
    sourceId: 'household',
    owner: 'Joint',
    location: 'Town Square Market',
    attendees: ['Erick', 'Ana'],
    notes: 'Organic greens, Meyer lemons, fresh bread.',
    category: 'family',
  },
  {
    id: 'cal-ev-12',
    title: 'Neighborhood Solar Microgrid Discussion',
    startTime: '11:00',
    endTime: '12:00',
    durationMinutes: 60,
    date: '2026-09-19',
    sourceId: 'household',
    owner: 'Joint',
    location: 'Community Center',
    category: 'family',
  },
];

export const calendarInsightsMock: CalendarInsight[] = [
  {
    id: 'ins-conflict-1',
    type: 'CONFLICT',
    title: 'Schedule Conflict Detected at 14:00',
    message: "Ana's clinic appointment with Dr. Weber overlaps with Erick's Client Technical Debrief. Erick is listed as care escort.",
    affectedEventIds: ['cal-ev-2', 'cal-ev-8'],
    actionLabel: 'Propose 15m shift for Client Call',
  },
  {
    id: 'ins-synergy-1',
    type: 'SYNERGY',
    title: 'Household Free Window: 12:30 – 13:45',
    message: 'Both Erick and Ana have an open gap before afternoon commitments. Good opportunity for a quiet lunch together.',
    affectedEventIds: [],
    actionLabel: 'Suggest quick lunch',
  },
];
