// src/components/slots/types.ts
import { 
  ContextOption, 
  ScheduleEvent, 
  ActionableTask, 
  NutritionData, 
  CareData, 
  FamilyMealData, 
  PhysicalHomeTelemetry 
} from '@/domain/types';

export interface RelationshipSwitcherProps {
  contexts: ContextOption[];
  activeContextId: string;
  onSelectContext: (contextId: string) => void;
}

export interface TodayScheduleProps {
  title: string;
  subtitle: string;
  countTag: string;
  events: ScheduleEvent[];
}

export interface AttentionTasksProps {
  title: string;
  pendingCountTag: string;
  tasks: ActionableTask[];
  onToggleTask: (taskId: string) => void;
}

export interface WellbeingNutritionProps {
  personContext: 'erick' | 'ana' | 'family';
  title: string;
  subtitle: string;
  targetTag: string;
  nutrition?: NutritionData;
  care?: CareData;
  familyMeal?: FamilyMealData;
  onOpenAskOlin: (prompt?: string) => void;
}

export interface PhysicalHomeProps {
  telemetry: PhysicalHomeTelemetry;
  doorLocked: boolean;
  onToggleDoorLock: () => void;
  ambianceScene: string;
  onCycleAmbianceScene: () => void;
}

export interface AskOlinTriggerProps {
  isOpen: boolean;
  onToggleModal: () => void;
}

export interface TodayHeaderProps {
  timeIndicator: string;
  greetingText: string;
  homeStatusText: string;
  privacyTag: string;
  privacyIcon: 'user' | 'heart' | 'users' | 'shield';
}

export interface ThemeSlots {
  RelationshipSwitcher: React.ComponentType<RelationshipSwitcherProps>;
  TodaySchedule: React.ComponentType<TodayScheduleProps>;
  AttentionTasks: React.ComponentType<AttentionTasksProps>;
  WellbeingNutrition: React.ComponentType<WellbeingNutritionProps>;
  PhysicalHome: React.ComponentType<PhysicalHomeProps>;
  AskOlinTrigger: React.ComponentType<AskOlinTriggerProps>;
  TodayHeader: React.ComponentType<TodayHeaderProps>;
}
