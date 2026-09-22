// src/components/slots/resolver.ts
import { OlinThemeId } from '@/theme/types';
import { ThemeSlots } from './types';

// 1. Ambient Future components
import { AmbientRelationshipSwitcher } from './ambient/AmbientRelationshipSwitcher';
import { AmbientTodaySchedule } from './ambient/AmbientTodaySchedule';
import { AmbientAttentionTasks } from './ambient/AmbientAttentionTasks';
import { AmbientWellbeingNutrition } from './ambient/AmbientWellbeingNutrition';
import { AmbientPhysicalHome } from './ambient/AmbientPhysicalHome';
import { AmbientAskOlinTrigger } from './ambient/AmbientAskOlinTrigger';
import { AmbientTodayHeader } from './ambient/AmbientTodayHeader';

// 2. Warm Household components
import { WarmRelationshipSwitcher } from './warm/WarmRelationshipSwitcher';
import { WarmTodaySchedule } from './warm/WarmTodaySchedule';
import { WarmAttentionTasks } from './warm/WarmAttentionTasks';
import { WarmWellbeingNutrition } from './warm/WarmWellbeingNutrition';
import { WarmPhysicalHome } from './warm/WarmPhysicalHome';
import { WarmAskOlinTrigger } from './warm/WarmAskOlinTrigger';
import { WarmTodayHeader } from './warm/WarmTodayHeader';

// 3. Nordic Premium Hardware components
import { HardwareRelationshipSwitcher } from './hardware/HardwareRelationshipSwitcher';
import { HardwareTodaySchedule } from './hardware/HardwareTodaySchedule';
import { HardwareAttentionTasks } from './hardware/HardwareAttentionTasks';
import { HardwareWellbeingNutrition } from './hardware/HardwareWellbeingNutrition';
import { HardwarePhysicalHome } from './hardware/HardwarePhysicalHome';
import { HardwareAskOlinTrigger } from './hardware/HardwareAskOlinTrigger';
import { HardwareTodayHeader } from './hardware/HardwareTodayHeader';

// 4. Editorial Life Ledger components
import { EditorialRelationshipSwitcher } from './editorial/EditorialRelationshipSwitcher';
import { EditorialTodaySchedule } from './editorial/EditorialTodaySchedule';
import { EditorialAttentionTasks } from './editorial/EditorialAttentionTasks';
import { EditorialWellbeingNutrition } from './editorial/EditorialWellbeingNutrition';
import { EditorialPhysicalHome } from './editorial/EditorialPhysicalHome';
import { EditorialAskOlinTrigger } from './editorial/EditorialAskOlinTrigger';
import { EditorialTodayHeader } from './editorial/EditorialTodayHeader';

// 5. Colorful Family Canvas components
import { CanvasRelationshipSwitcher } from './canvas/CanvasRelationshipSwitcher';
import { CanvasTodaySchedule } from './canvas/CanvasTodaySchedule';
import { CanvasAttentionTasks } from './canvas/CanvasAttentionTasks';
import { CanvasWellbeingNutrition } from './canvas/CanvasWellbeingNutrition';
import { CanvasPhysicalHome } from './canvas/CanvasPhysicalHome';
import { CanvasAskOlinTrigger } from './canvas/CanvasAskOlinTrigger';
import { CanvasTodayHeader } from './canvas/CanvasTodayHeader';

// 6. Organic Calm components
import { OrganicRelationshipSwitcher } from './organic/OrganicRelationshipSwitcher';
import { OrganicTodaySchedule } from './organic/OrganicTodaySchedule';
import { OrganicAttentionTasks } from './organic/OrganicAttentionTasks';
import { OrganicWellbeingNutrition } from './organic/OrganicWellbeingNutrition';
import { OrganicPhysicalHome } from './organic/OrganicPhysicalHome';
import { OrganicAskOlinTrigger } from './organic/OrganicAskOlinTrigger';
import { OrganicTodayHeader } from './organic/OrganicTodayHeader';

export const ambientFutureSlots: ThemeSlots = {
  RelationshipSwitcher: AmbientRelationshipSwitcher,
  TodaySchedule: AmbientTodaySchedule,
  AttentionTasks: AmbientAttentionTasks,
  WellbeingNutrition: AmbientWellbeingNutrition,
  PhysicalHome: AmbientPhysicalHome,
  AskOlinTrigger: AmbientAskOlinTrigger,
  TodayHeader: AmbientTodayHeader,
};

export const warmHouseholdSlots: ThemeSlots = {
  RelationshipSwitcher: WarmRelationshipSwitcher,
  TodaySchedule: WarmTodaySchedule,
  AttentionTasks: WarmAttentionTasks,
  WellbeingNutrition: WarmWellbeingNutrition,
  PhysicalHome: WarmPhysicalHome,
  AskOlinTrigger: WarmAskOlinTrigger,
  TodayHeader: WarmTodayHeader,
};

export const premiumHardwareSlots: ThemeSlots = {
  RelationshipSwitcher: HardwareRelationshipSwitcher,
  TodaySchedule: HardwareTodaySchedule,
  AttentionTasks: HardwareAttentionTasks,
  WellbeingNutrition: HardwareWellbeingNutrition,
  PhysicalHome: HardwarePhysicalHome,
  AskOlinTrigger: HardwareAskOlinTrigger,
  TodayHeader: HardwareTodayHeader,
};

export const editorialLedgerSlots: ThemeSlots = {
  RelationshipSwitcher: EditorialRelationshipSwitcher,
  TodaySchedule: EditorialTodaySchedule,
  AttentionTasks: EditorialAttentionTasks,
  WellbeingNutrition: EditorialWellbeingNutrition,
  PhysicalHome: EditorialPhysicalHome,
  AskOlinTrigger: EditorialAskOlinTrigger,
  TodayHeader: EditorialTodayHeader,
};

export const colorfulCanvasSlots: ThemeSlots = {
  RelationshipSwitcher: CanvasRelationshipSwitcher,
  TodaySchedule: CanvasTodaySchedule,
  AttentionTasks: CanvasAttentionTasks,
  WellbeingNutrition: CanvasWellbeingNutrition,
  PhysicalHome: CanvasPhysicalHome,
  AskOlinTrigger: CanvasAskOlinTrigger,
  TodayHeader: CanvasTodayHeader,
};

export const organicCalmSlots: ThemeSlots = {
  RelationshipSwitcher: OrganicRelationshipSwitcher,
  TodaySchedule: OrganicTodaySchedule,
  AttentionTasks: OrganicAttentionTasks,
  WellbeingNutrition: OrganicWellbeingNutrition,
  PhysicalHome: OrganicPhysicalHome,
  AskOlinTrigger: OrganicAskOlinTrigger,
  TodayHeader: OrganicTodayHeader,
};

export function getThemeSlots(themeId: OlinThemeId): ThemeSlots {
  switch (themeId) {
    case 'ambient-future':
      return ambientFutureSlots;
    case 'warm-household':
      return warmHouseholdSlots;
    case 'premium-hardware':
      return premiumHardwareSlots;
    case 'editorial-ledger':
      return editorialLedgerSlots;
    case 'colorful-canvas':
      return colorfulCanvasSlots;
    case 'organic-calm':
      return organicCalmSlots;
    default:
      return warmHouseholdSlots;
  }
}
