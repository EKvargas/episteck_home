// src/domain/mocks.ts
import { Viewer, ContextOption, TodaySummary, MicronutrientCoverage } from './types';

export const viewerMock: Viewer = {
  id: 'PSN-me',
  name: 'Erick',
};

// Represents contexts the viewer is authorized to see
export const availableContextsMock: ContextOption[] = [
  { id: 'PSN-me', name: 'Erick', mode: 'PERSONAL' },
  { id: 'PSN-ana', name: 'Ana', mode: 'CARE_FOR_ANOTHER_PERSON' },
  { id: 'CIR-fam', name: 'Family', mode: 'FAMILY' },
];

export const getTodaySummaryMock = (contextId: string): TodaySummary => {
  // Shared base physical home telemetry
  const baseHome = {
    livingRoom: { temp: '21.4°C', humidity: '45% Humidity' },
    climate: { mode: 'Eco Auto', targetTemp: 'Target 21.0°' },
    door: { locked: false, label: 'Unlocked' },
    ambiance: {
      currentScene: 'Afternoon Calm',
      availableScenes: ['Afternoon Calm', 'Golden Hour', 'Focus State', 'Evening Warmth']
    }
  };

  if (contextId === 'PSN-me') {
    return {
      greeting: "Good afternoon, Erick",
      subtitle: "Friday, Sep 18 · 14:32",
      privacyTag: "Personal Space",
      privacyIcon: "user",
      scheduleTitle: "Erick's Flow",
      scheduleSubtitle: "Personal syncs & appointments",
      scheduleCountTag: "3 events",
      events: [
        {
          id: 'ev-1',
          time: "10:00",
          title: "Work Sync with Architecture Core",
          subtitle: "Virtual Room · Episteck Home Core",
          status: "Completed",
          statusColor: "emerald"
        },
        {
          id: 'ev-2',
          time: "14:00",
          title: "Doctor Appointment (Care for Ana)",
          subtitle: "Dr. Weber · Maternal & Wellness Clinic",
          status: "Now Active",
          statusColor: "amber",
          isCareLink: true
        },
        {
          id: 'ev-3',
          time: "18:30",
          title: "Family Dinner & Prep",
          subtitle: "Mealie: Baked Salmon & Asparagus",
          status: "In 4h",
          statusColor: "sky"
        }
      ],
      tasks: [
        { id: 't-1', title: "Log lunch nutrition (Mediterranean Bowl)", message: "Log lunch nutrition (Mediterranean Bowl)", done: true, tag: "Erick", priority: "medium" },
        { id: 't-2', title: "Check front door latch (Reported open 12m ago)", message: "Check front door latch (Reported open 12m ago)", done: false, tag: "Alert", priority: "high", isDoorAlert: true },
        { id: 't-3', title: "Water Monstera & living room ferns", message: "Water Monstera & living room ferns", done: false, tag: "Home", priority: "low" }
      ],
      nutrition: {
        calories: 1200,
        targetCalories: 2000,
        burnedCalories: 1840,
        hydrationLiters: 1.8,
        proteinRemainingGrams: 42,
        proteinConsumedGrams: 98,
        proteinTargetGrams: 140,
        carbsConsumedGrams: 145,
        carbsTargetGrams: 210,
        logged: true
      },
      physicalHome: baseHome,

      // Backwards compatibility
      schedule: [
        { id: 'ev-1', time: '10:00 AM', title: 'Work Sync with Architecture Core' },
        { id: 'ev-2', time: '02:00 PM', title: 'Doctor Appointment (Care for Ana)' },
        { id: 'ev-3', time: '06:30 PM', title: 'Family Dinner & Prep' }
      ],
      nutritionProgress: { calories: 1200, target: 2000, logged: true },
      hydration: { glasses: 4, target: 8 },
      deviceStatus: { activeDevices: 4, alerts: 1 },
      actionableItems: [
        { id: 't-2', message: 'Check front door latch (Reported open 12m ago)', priority: 'high' },
        { id: 't-1', message: 'Log lunch nutrition (Mediterranean Bowl)', priority: 'medium' },
        { id: 't-3', message: 'Water Monstera & living room ferns', priority: 'low' }
      ]
    };
  }

  if (contextId === 'PSN-ana') {
    return {
      greeting: "Good afternoon, Ana",
      subtitle: "Care & Support Sharing Context",
      privacyTag: "Care Circle Access",
      privacyIcon: "heart",
      scheduleTitle: "Ana's Agenda & Care",
      scheduleSubtitle: "Appointments and shared wellness",
      scheduleCountTag: "2 events",
      events: [
        {
          id: 'ev-a1',
          time: "14:00",
          title: "Doctor Appointment with Dr. Weber",
          subtitle: "Maternal & Wellness Clinic · Room 304",
          status: "In Progress",
          statusColor: "amber"
        },
        {
          id: 'ev-a2',
          time: "15:00",
          title: "Transit Return Home",
          subtitle: "Estimated arrival 15:25",
          status: "Upcoming",
          statusColor: "sky"
        }
      ],
      tasks: [
        { id: 't-a1', title: "Review prenatal vitamin schedule", message: "Review prenatal vitamin schedule", done: true, tag: "Care", priority: "medium" },
        { id: 't-a2', title: "Rest & Hydration pause at 16:00", message: "Rest & Hydration pause at 16:00", done: false, tag: "Wellness", priority: "medium" },
        { id: 't-a3', title: "Review weekend nursery checklist with Erick", message: "Review weekend nursery checklist with Erick", done: false, tag: "Shared", priority: "low" }
      ],
      care: {
        consultation: {
          time: "14:00",
          doctor: "Dr. Weber",
          clinic: "Maternal & Wellness Clinic",
          room: "Room 304",
          description: "Maternal & Wellness Clinic, Room 304. Erick authorized to receive appointment completion chimes.",
          nextCheckup: "Oct 02"
        },
        restRhythm: {
          hoursSleep: "8h 12m Quality Sleep",
          status: "Optimal Recovery"
        },
        hydration: {
          litersCurrent: 2.2,
          litersTarget: 2.5,
          percentage: 88
        }
      },
      physicalHome: baseHome,

      // Backwards compatibility
      schedule: [
        { id: 'ev-a1', time: '02:00 PM', title: 'Doctor Appointment with Dr. Weber' },
        { id: 'ev-a2', time: '03:00 PM', title: 'Transit Return Home' }
      ],
      nutritionProgress: { calories: 800, target: 1500, logged: true },
      hydration: { glasses: 6, target: 8 },
      deviceStatus: { activeDevices: 4, alerts: 0 },
      actionableItems: [
        { id: 't-a1', message: 'Review prenatal vitamin schedule', priority: 'medium' },
        { id: 't-a2', message: 'Rest & Hydration pause at 16:00', priority: 'medium' },
        { id: 't-a3', message: 'Review weekend nursery checklist with Erick', priority: 'low' }
      ]
    };
  }

  if (contextId === 'CIR-fam') {
    return {
      greeting: "Good afternoon, Vargas Household",
      subtitle: "Shared Family Surface · Living Room Glance",
      privacyTag: "Shared Household",
      privacyIcon: "users",
      scheduleTitle: "Household Agenda",
      scheduleSubtitle: "Glanceable coordination for everyone",
      scheduleCountTag: "4 events",
      events: [
        {
          id: 'ev-f1',
          time: "14:00",
          title: "Ana at Clinic (Dr. Weber)",
          subtitle: "Returning at 15:25",
          status: "Away",
          statusColor: "amber"
        },
        {
          id: 'ev-f2',
          time: "16:15",
          title: "Isabella arrives home from School",
          subtitle: "Bus 4 · Keypad PIN ready",
          status: "In 1h 45m",
          statusColor: "emerald"
        },
        {
          id: 'ev-f3',
          time: "18:30",
          title: "Family Dinner Together",
          subtitle: "Baked Salmon with lemon potatoes",
          status: "Scheduled",
          statusColor: "sky"
        },
        {
          id: 'ev-f4',
          time: "20:00",
          title: "Bedtime Story & Reading",
          subtitle: "Isabella bedroom",
          status: "Evening",
          statusColor: "slate"
        }
      ],
      tasks: [
        { id: 't-f1', title: "Front door latch check", message: "Front door latch check", done: false, tag: "Security", priority: "high", isDoorAlert: true },
        { id: 't-f2', title: "Water houseplants & living room fern", message: "Water houseplants & living room fern", done: false, tag: "Chores", priority: "low" },
        { id: 't-f3', title: "Unload dishwasher before dinner", message: "Unload dishwasher before dinner", done: false, tag: "Household", priority: "low" }
      ],
      familyMeal: {
        time: "18:30",
        timeTag: "18:30 Dinner Ready",
        dishTitle: "Wild Baked Salmon & Roasted Asparagus",
        source: "Mealie Plan",
        description: "Mealie Plan · High omega-3 · Isabella-friendly portions",
        groceryItemsCount: 3
      },
      physicalHome: baseHome,

      // Backwards compatibility
      schedule: [
        { id: 'ev-f1', time: '02:00 PM', title: 'Ana at Clinic (Dr. Weber)' },
        { id: 'ev-f2', time: '04:15 PM', title: 'Isabella arrives home from School' },
        { id: 'ev-f3', time: '06:30 PM', title: 'Family Dinner Together' },
        { id: 'ev-f4', time: '08:00 PM', title: 'Bedtime Story & Reading' }
      ],
      nutritionProgress: { calories: 0, target: 0, logged: false },
      hydration: { glasses: 0, target: 0 },
      deviceStatus: { activeDevices: 12, alerts: 1 },
      actionableItems: [
        { id: 't-f1', message: 'Front door latch check', priority: 'high' },
        { id: 't-f2', message: 'Water houseplants & living room fern', priority: 'low' },
        { id: 't-f3', message: 'Unload dishwasher before dinner', priority: 'low' }
      ]
    };
  }

  // Fallback empty
  return {
    greeting: "Good afternoon",
    subtitle: "Friday, Sep 18 · 14:32",
    privacyTag: "Personal Space",
    privacyIcon: "user",
    scheduleTitle: "Today's Flow",
    scheduleSubtitle: "Synchronized household calendar",
    scheduleCountTag: "0 events",
    events: [],
    tasks: [],
    physicalHome: baseHome,
    schedule: [],
    nutritionProgress: { calories: 0, target: 0, logged: false },
    hydration: { glasses: 0, target: 0 },
    deviceStatus: { activeDevices: 0, alerts: 0 },
    actionableItems: []
  };
};

export const getMicronutrientCoverageMock = (contextId: string): MicronutrientCoverage[] => {
  // Scenario 1: Ana (Pregnancy context) - Good Data Completeness
  if (contextId === 'PSN-ana') {
    return [
      {
      id: 'iron',
      name: 'Iron',
      targetAmount: 27, // mg for pregnancy
      currentAmount: 28.5,
      unit: 'mg',
      dataCompletenessPercentage: 85,
      contributions: [
        {
          sourceType: 'SUPPLEMENT',
          amount: 18,
          unit: 'mg',
          quality: 'MEASURED',
          label: 'Prenatal Vitamin (Logged 08:00)'
        },
        {
          sourceType: 'FOOD',
          amount: 6.5,
          unit: 'mg',
          quality: 'MEASURED',
          label: 'Spinach & Lentil Salad (Lunch)'
        },
        {
          sourceType: 'FOOD',
          amount: 4,
          unit: 'mg',
          quality: 'ESTIMATED',
          label: 'Whole Wheat Toast (Breakfast)'
        }
      ],
      trendSummary: 'On track based on weekly average (28mg/day)'
      },
      {
        id: 'calcium',
        name: 'Calcium',
        targetAmount: 1000,
        currentAmount: 850,
        unit: 'mg',
        dataCompletenessPercentage: 100,
        contributions: [
          { sourceType: 'FOOD', amount: 500, unit: 'mg', quality: 'ESTIMATED', label: 'Greek Yogurt' },
          { sourceType: 'FOOD', amount: 350, unit: 'mg', quality: 'MEASURED', label: 'Almond Milk' }
        ],
        trendSummary: 'Close to daily goal'
      },
      {
        id: 'folate',
        name: 'Folate',
        targetAmount: 600,
        currentAmount: 400,
        unit: 'mcg',
        dataCompletenessPercentage: 60,
        contributions: [
          { sourceType: 'SUPPLEMENT', amount: 400, unit: 'mcg', quality: 'MEASURED', label: 'Prenatal Vitamin' }
        ],
        trendSummary: 'Needs more dietary folate'
      },
      {
        id: 'vitd',
        name: 'Vitamin D',
        targetAmount: 15,
        currentAmount: 15,
        unit: 'mcg',
        dataCompletenessPercentage: 100,
        contributions: [
          { sourceType: 'SUPPLEMENT', amount: 15, unit: 'mcg', quality: 'MEASURED', label: 'Prenatal Vitamin' }
        ],
        trendSummary: 'Daily goal met'
      }
    ];
  }

  // Scenario 2: Erick (Personal context) - Partial Data, Unknowns
  if (contextId === 'PSN-me') {
    return [
      {
      id: 'iron',
      name: 'Iron',
      targetAmount: 8, // mg for men
      currentAmount: 3.5,
      unit: 'mg',
      dataCompletenessPercentage: 40,
      contributions: [
        {
          sourceType: 'FOOD',
          amount: 3.5,
          unit: 'mg',
          quality: 'MEASURED',
          label: 'Oatmeal & Berries (Breakfast)'
        },
        {
          sourceType: 'FOOD',
          amount: 0, // Should not be rendered as 0 but visualized as unknown
          unit: 'mg',
          quality: 'UNKNOWN',
          label: 'Unlogged Lunch (Mediterranean Bowl)'
        }
      ],
      trendSummary: 'Insufficient data for today'
      }
    ];
  }

  // Scenario 3: Family or Fallback - No Supplement Data
  return [
    {
    id: 'iron',
    name: 'Iron',
    targetAmount: 27,
    currentAmount: 0,
    unit: 'mg',
    dataCompletenessPercentage: 0,
    contributions: [],
      trendSummary: 'No data logged for today'
    }
  ];
};

