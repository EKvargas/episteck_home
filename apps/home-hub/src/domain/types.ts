// src/domain/types.ts

// Viewer identity derived independently (not mutable by UI)
export interface Viewer {
  id: string;
  name: string;
}

// Concept: Person vs. Circle vs. Care
export type ContextMode = 'PERSONAL' | 'FAMILY' | 'CARE_FOR_ANOTHER_PERSON';

export interface ContextOption {
  id: string; // The canonical ID (e.g. PSN-123 or CIR-456)
  name: string;
  mode: ContextMode;
  avatarUrl?: string;
}

export interface PersonSummary {
  id: string;
  name: string;
  avatarUrl?: string;
  contextMode: 'PERSONAL' | 'CARE_FOR_ANOTHER_PERSON';
}

export interface CircleSummary {
  id: string;
  name: string;
  contextMode: 'FAMILY';
  memberCount: number;
}

export type PermissionState = 'ALLOW' | 'DENY' | 'INDETERMINATE';
export type DataFreshness = 'FRESH' | 'STALE' | 'OFFLINE';

export interface ScheduleEvent {
  id: string;
  time: string;
  title: string;
  subtitle?: string;
  status?: string;
  statusColor?: 'emerald' | 'amber' | 'sky' | 'slate';
  isCareLink?: boolean;
}

export interface ActionableTask {
  id: string;
  title: string;
  message?: string; // Backwards compatibility with old mocks
  done: boolean;
  tag: string;
  priority?: 'high' | 'medium' | 'low';
  isDoorAlert?: boolean;
}

export interface NutritionData {
  calories: number;
  targetCalories: number;
  burnedCalories: number;
  hydrationLiters: number;
  proteinRemainingGrams: number;
  proteinConsumedGrams: number;
  proteinTargetGrams: number;
  carbsConsumedGrams: number;
  carbsTargetGrams: number;
  logged: boolean;
}

export interface CareData {
  consultation: {
    time: string;
    doctor: string;
    clinic: string;
    room: string;
    description: string;
    nextCheckup: string;
  };
  restRhythm: {
    hoursSleep: string;
    status: string;
  };
  hydration: {
    litersCurrent: number;
    litersTarget: number;
    percentage: number;
  };
}

export interface FamilyMealData {
  time: string;
  timeTag: string;
  dishTitle: string;
  source: string;
  description: string;
  groceryItemsCount: number;
}

export interface PhysicalHomeTelemetry {
  livingRoom: {
    temp: string;
    humidity: string;
  };
  climate: {
    mode: string;
    targetTemp: string;
  };
  door: {
    locked: boolean;
    label: string;
  };
  ambiance: {
    currentScene: string;
    availableScenes: string[];
  };
}

export interface TodaySummary {
  greeting: string;
  subtitle: string;
  privacyTag: string;
  privacyIcon: 'user' | 'heart' | 'users' | 'shield';
  scheduleTitle: string;
  scheduleSubtitle: string;
  scheduleCountTag: string;
  events: ScheduleEvent[];
  tasks: ActionableTask[];
  // Nutrition & Care modes
  nutrition?: NutritionData;
  care?: CareData;
  familyMeal?: FamilyMealData;
  // Physical Home
  physicalHome: PhysicalHomeTelemetry;

  // Backwards compatibility fields
  schedule: Array<{ id: string; time: string; title: string }>;
  nutritionProgress: { calories: number; target: number; logged: boolean };
  hydration: { glasses: number; target: number };
  deviceStatus: { activeDevices: number; alerts: number };
  actionableItems: Array<{ id: string; message: string; priority?: 'high' | 'medium' | 'low' }>;
}

export type DataQualityState = 'MEASURED' | 'ESTIMATED' | 'UNKNOWN';
export type NutrientSourceType = 'FOOD' | 'SUPPLEMENT';

// Point 5: Unknown != Zero. Use discriminated union for amount.
export type NutrientContribution = {
  sourceType: NutrientSourceType;
  unit: string;
  label: string; // e.g. "Prenatal Vitamin", "Spinach"
} & (
  | { quality: 'MEASURED' | 'ESTIMATED'; amount: number }
  | { quality: 'UNKNOWN'; amount: null }
);

// Point 10: Supplement status must have 3 states
export type SupplementStatus = 'LOGGED_KNOWN' | 'EXPLICITLY_NOT_CONSUMED' | 'NOT_LOGGED_UNKNOWN';

// Point 7 & 11: Structure the coverage contract better
export interface MicronutrientCoverage {
  id: string; // e.g., 'iron', 'calcium'
  name: string; // e.g. "Iron"
  unit: string;
  
  // Point 6: Do not present partial data as precise total
  knownIntake: number;
  knownFoodIntake: number;
  knownSupplementIntake: number | null;
  
  // Point 11: Target provenance
  targetAmount: number;
  targetContext: string;
  targetSource: string; // e.g. "Pregnancy target — UI mock"
  
  // Point 13: Data completeness language
  todayCoveragePercent: number | null;
  nutrientDataCoverage: number; // 0-100 indicating how much of the day's meals are covered
  
  // Point 8: Structured 7-day data
  rolling7DayKnownAverage: number | null;
  rolling7DayDataCoverage: number | null;
  
  supplementStatus: SupplementStatus;
  
  contributions: NutrientContribution[];
  unknownItems: string[]; // e.g. ["Unlogged Lunch", "Restaurant Dinner"]
}

