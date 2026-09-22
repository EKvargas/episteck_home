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

export interface NutrientContribution {
  sourceType: NutrientSourceType;
  amount: number;
  unit: string;
  quality: DataQualityState;
  label: string; // e.g. "Prenatal Vitamin", "Spinach"
}

export interface MicronutrientCoverage {
  id: string; // e.g., 'iron', 'calcium'
  name: string; // e.g. "Iron"
  targetAmount: number;
  currentAmount: number;
  unit: string;
  dataCompletenessPercentage: number; // 0-100 indicating how much of the day's meals are logged
  contributions: NutrientContribution[];
  trendSummary?: string; // e.g. "On track based on weekly average"
}

