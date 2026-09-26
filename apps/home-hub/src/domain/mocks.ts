// src/domain/mocks.ts
import { Viewer, ContextOption, ContextMode, TodaySummary, MicronutrientCoverage } from './types';

// Temporary F2 presentation seam: the prototype's domain mocks use fixed demo
// keys. They are not authorization inputs or persisted active-context state.
export function getDemoContextId(mode: ContextMode): string {
  if (mode === 'PERSONAL') return 'PSN-me';
  if (mode === 'CARE_FOR_ANOTHER_PERSON') return 'PSN-ana';
  return 'CIR-fam';
}

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
        unit: 'mg',
        
        knownIntake: 28.5,
        knownFoodIntake: 10.5,
        knownSupplementIntake: 18,
        
        targetAmount: 27, // mg for pregnancy
        targetContext: 'Pregnancy',
        targetSource: 'Pregnancy target — UI mock',
        
        knownTargetCoveragePercent: 105,
        nutrientDataCoverage: 85,
        
        rolling7DayKnownAverage: 28,
        rolling7DayDataCoverage: 92,
        
        supplementStatus: 'LOGGED_KNOWN',
        
        contributions: [
          {
            sourceType: 'SUPPLEMENT',
            unit: 'mg',
            label: 'Prenatal Vitamin (Logged 08:00)',
            quality: 'MEASURED',
            amount: 18
          },
          {
            sourceType: 'FOOD',
            unit: 'mg',
            label: 'Spinach & Lentil Salad (Lunch)',
            quality: 'MEASURED',
            amount: 6.5
          },
          {
            sourceType: 'FOOD',
            unit: 'mg',
            label: 'Whole Wheat Toast (Breakfast)',
            quality: 'ESTIMATED',
            amount: 4
          }
        ],
        unknownItems: ['Afternoon Snack (Banana & Almonds)']
      },
      {
        id: 'calcium',
        name: 'Calcium',
        unit: 'mg',
        
        knownIntake: 850,
        knownFoodIntake: 850,
        knownSupplementIntake: 0,
        
        targetAmount: 1000,
        targetContext: 'Pregnancy',
        targetSource: 'Pregnancy target — UI mock',
        
        knownTargetCoveragePercent: 85,
        nutrientDataCoverage: 100,
        
        rolling7DayKnownAverage: 950,
        rolling7DayDataCoverage: 100,
        
        supplementStatus: 'EXPLICITLY_NOT_CONSUMED',
        
        contributions: [
          { sourceType: 'FOOD', unit: 'mg', label: 'Greek Yogurt', quality: 'ESTIMATED', amount: 500 },
          { sourceType: 'FOOD', unit: 'mg', label: 'Almond Milk', quality: 'MEASURED', amount: 350 }
        ],
        unknownItems: []
      },
      {
        id: 'folate',
        name: 'Folate',
        unit: 'mcg',
        
        knownIntake: 400,
        knownFoodIntake: 0,
        knownSupplementIntake: 400,
        
        targetAmount: 600,
        targetContext: 'Pregnancy',
        targetSource: 'Pregnancy target — UI mock',
        
        knownTargetCoveragePercent: 67,
        nutrientDataCoverage: 60,
        
        rolling7DayKnownAverage: 450,
        rolling7DayDataCoverage: 80,
        
        supplementStatus: 'LOGGED_KNOWN',
        
        contributions: [
          { sourceType: 'SUPPLEMENT', unit: 'mcg', label: 'Prenatal Vitamin', quality: 'MEASURED', amount: 400 }
        ],
        unknownItems: ['Breakfast', 'Lunch']
      },
      {
        id: 'vitd',
        name: 'Vitamin D',
        unit: 'mcg',
        
        knownIntake: 15,
        knownFoodIntake: 0,
        knownSupplementIntake: 15,
        
        targetAmount: 15,
        targetContext: 'Pregnancy',
        targetSource: 'Pregnancy target — UI mock',
        
        knownTargetCoveragePercent: 100,
        nutrientDataCoverage: 100,
        
        rolling7DayKnownAverage: 15,
        rolling7DayDataCoverage: 100,
        
        supplementStatus: 'LOGGED_KNOWN',
        
        contributions: [
          { sourceType: 'SUPPLEMENT', unit: 'mcg', label: 'Prenatal Vitamin', quality: 'MEASURED', amount: 15 }
        ],
        unknownItems: []
      }
    ];
  }

  // Scenario 2: Erick (Personal context) - Partial Data, Unknowns
  if (contextId === 'PSN-me') {
    return [
      {
        id: 'iron',
        name: 'Iron',
        unit: 'mg',
        
        knownIntake: 3.5,
        knownFoodIntake: 3.5,
        knownSupplementIntake: null,
        
        targetAmount: 8, // mg for men
        targetContext: 'Adult Male',
        targetSource: 'Standard adult target — UI mock',
        
        knownTargetCoveragePercent: 43,
        nutrientDataCoverage: 40,
        
        rolling7DayKnownAverage: 6.2,
        rolling7DayDataCoverage: 75,
        
        supplementStatus: 'NOT_LOGGED_UNKNOWN',
        
        contributions: [
          {
            sourceType: 'FOOD',
            unit: 'mg',
            label: 'Oatmeal & Berries (Breakfast)',
            quality: 'MEASURED',
            amount: 3.5
          },
          {
            sourceType: 'FOOD',
            unit: 'mg',
            label: 'Unlogged Lunch (Mediterranean Bowl)',
            quality: 'UNKNOWN',
            amount: null // Replaced 0 with null according to new data model
          }
        ],
        unknownItems: ['Unlogged Lunch (Mediterranean Bowl)']
      }
    ];
  }

  // Scenario 3: Family or Fallback - No Supplement Data
  return [
    {
      id: 'iron',
      name: 'Iron',
      unit: 'mg',
      
      knownIntake: 0,
      knownFoodIntake: 0,
      knownSupplementIntake: null,
      
      targetAmount: 27,
      targetContext: 'Pregnancy',
      targetSource: 'Pregnancy target — UI mock',
      
      knownTargetCoveragePercent: 0,
      nutrientDataCoverage: 0,
      
      rolling7DayKnownAverage: null,
      rolling7DayDataCoverage: null,
      
      supplementStatus: 'NOT_LOGGED_UNKNOWN',
      
      contributions: [],
      unknownItems: ['No data logged']
    }
  ];
};
