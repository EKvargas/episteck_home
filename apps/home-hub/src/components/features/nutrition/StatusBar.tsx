import type { CSSProperties } from 'react';
import type { Bar, Tone } from '../../../integration/nutrition/nutrient-status';
import styles from './StatusBar.module.css';

type BarStyle = CSSProperties & { '--bar-scale': string; '--bar-value'?: string };

/**
 * One nutrient's track, 0–150 % of its target, with the target's tick, band or cap. The fill width
 * is a CSS ratio of the two raw wire decimals, so no percentage is computed here. Decorative: the
 * row around it carries the amount and the state word.
 */
export function StatusBar({ bar, tone }: { bar: Bar; tone: Tone }) {
  // An unknown value draws no fill; a scale that is not above zero has nothing to measure against.
  const value = bar.value !== null && Number(bar.scale) > 0 ? bar.value : null;
  const style: BarStyle = { '--bar-scale': bar.scale };
  if (value !== null) style['--bar-value'] = value;
  return (
    <span className={styles.bar} data-tone={tone} data-mark={bar.mark} style={style} aria-hidden="true">
      {value !== null && <span className={styles.fill} />}
      <span className={styles.mark} />
    </span>
  );
}
