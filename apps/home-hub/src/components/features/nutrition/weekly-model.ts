import { MICRONUTRIENTS, type Micronutrient } from '../../../integration/nutrition/diary-contract.ts';
import { amount, nutrientLabel, targetValue, unitLabel, unitOf } from '../../../integration/nutrition/nutrition-format.ts';
import { nutritionHref } from '../../../integration/nutrition/nutrition-href.ts';
import {
  groupWeekly, latestTarget, weeklyState, type NutrientState, type WeeklyGroup,
} from '../../../integration/nutrition/nutrient-status.ts';
import type { PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import type { RangeDays } from '../../../integration/nutrition/period-range.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { panelError, type PanelErrorKind } from './panel-error.ts';

/** Hoy's heading for the grouped weekly status; the panel reads 7 days. The no-break space keeps "·" off a line start. */
export const WEEKLY_TITLE = 'Vitaminas y minerales\u00a0· últimos 7 días';

export interface WeeklyRow {
  code: Micronutrient;
  name: string;
  average: string;
  target: string | null;
  state: NutrientState;
  href: string;
}

export type WeeklyPanelModel =
  | { kind: 'LOADING' | PanelErrorKind }
  | { kind: 'WEEK'; groups: WeeklyGroup<WeeklyRow>[] };

/** The ten vitamins and minerals as grouped rows; formats the backend's averages, never calculates them. */
export function microGroups(summary: PeriodSummary, range: RangeDays, person: string | null): WeeklyGroup<WeeklyRow>[] {
  const rows = MICRONUTRIENTS.map((code): WeeklyRow => {
    const average = summary.averages[code];
    const target = latestTarget(summary.days, code);
    const unit = target?.unit ?? unitOf(code);
    return {
      code,
      name: nutrientLabel(code),
      average: average.averageKnown === null ? 'sin dato' : `${amount(average.averageKnown, unit)} ${unitLabel(unit)}`,
      target: target === null ? null : targetValue(target.kind, target.displayValue, target.unit),
      state: weeklyState(average, target),
      href: nutritionHref(`/nutrition/nutriente/${code}`, person, { rango: String(range) }),
    };
  });
  return groupWeekly(rows);
}

/** Fixed-vocabulary label for the one log line per read. */
export function weeklyOutcome(model: WeeklyPanelModel): string {
  return model.kind;
}

/** Map one adapter envelope to exactly one deliberate panel. The weekly status always reads 7 days. */
export function toWeeklyPanelModel(envelope: DataEnvelope<PeriodSummary>, person: string | null): WeeklyPanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return { kind: panelError(envelope.errorCode) };
    case 'READY':
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return { kind: 'WEEK', groups: microGroups(envelope.data, 7, person) };
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
