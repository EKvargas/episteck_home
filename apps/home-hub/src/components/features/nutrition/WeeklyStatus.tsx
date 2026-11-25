import { CaretRight } from '@phosphor-icons/react/ssr';
import type { WeeklyGroup } from '../../../integration/nutrition/nutrient-status';
import type { WeeklyRow } from './weekly-model';
import styles from './WeeklyPanel.module.css';

/** Server-rendered: each group is a native <details>, so opening it needs no client code. */
export function WeeklyStatus({ groups }: { groups: WeeklyGroup<WeeklyRow>[] }) {
  return (
    <div className={styles.groups}>
      {groups.map((group) => (
        <details key={group.key} className={styles.group} data-group={group.key}>
          <summary className={styles.summary}>
            <span className={styles.dot} aria-hidden="true" />
            <span className={styles.summaryText}>{group.summary}</span>
            <CaretRight className={styles.caret} weight="bold" aria-hidden="true" />
          </summary>
          <ul className={styles.rows}>
            {group.items.map((row) => (
              <li key={row.code}>
                <a className={styles.row} href={row.href} data-tone={row.state.tone}>
                  <span className={styles.name}>{row.name}</span>
                  {row.state.word !== null && (
                    <span className={styles.state}>
                      <span className={styles.dot} aria-hidden="true" />
                      {row.state.word}
                      {row.state.detail !== null && <span className={styles.detail}> · {row.state.detail}</span>}
                    </span>
                  )}
                  <span className={styles.figures}>
                    media {row.average}
                    {row.target !== null && <> · objetivo {row.target}</>}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}
