import type { ReactNode } from 'react';
import { HUB_BASE_PATH } from '@/integration/basePath';
import type { RangeDays } from '@/integration/nutrition/period-range';
import { shortDate } from '@/integration/nutrition/nutrition-format';
import { ChatPrompt } from './ChatPrompt';
import type { Grid, PeriodPanelModel } from './period-panel-model';
import { RetryButton } from './RetryButton';
import { WeeklyStatus } from './WeeklyStatus';
import styles from './PeriodPanel.module.css';

const RANGES: RangeDays[] = [3, 7, 14];

function Frame({ role, tone, busy, children }: {
  role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children: ReactNode;
}) {
  return (
    <section
      lang="es"
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      data-testid="period-panel"
    >
      {children}
    </section>
  );
}

/** Links `?<param>=<n>` on `path`; keeps `person` only when it is in the URL. */
export function RangeLinks({ range, path, param, person }: {
  range: RangeDays; path: string; param: 'dias' | 'rango'; person: string | null;
}) {
  return (
    <nav lang="es" aria-label="Rango de días" className={styles.range}>
      {RANGES.map((n) => {
        const query = new URLSearchParams();
        if (person !== null) query.set('person', person);
        query.set(param, String(n));
        return (
          <a
            key={n}
            href={`${HUB_BASE_PATH}${path}?${query.toString()}`}
            aria-current={n === range ? 'page' : undefined}
            className={n === range ? styles.rangeActive : undefined}
          >
            {n} días
          </a>
        );
      })}
    </nav>
  );
}

function GridView({ grid, many }: { grid: Grid; many: boolean }) {
  const hasAverage = grid.rows[0]?.average !== null;
  const first = grid.columns[0];
  const last = grid.columns[grid.columns.length - 1];
  return (
    <table className={styles.table}>
      <caption className={many ? styles.caption : 'visually-hidden'}>
        {first.date === last.date ? shortDate(first.date) : `${shortDate(first.date)} – ${shortDate(last.date)}`}
      </caption>
      {/* Both grids reserve the Media column, so the days line up when two are stacked. */}
      <colgroup>
        <col className={styles.nameCol} />
        {grid.columns.map((c) => <col key={c.date} />)}
        <col className={styles.averageCol} />
      </colgroup>
      <thead>
        <tr>
          <th scope="col"><span className="visually-hidden">Nutriente</span></th>
          {grid.columns.map((c) => (
            <th key={c.date} scope="col" className={styles.dayHead}>
              <span className={styles.initial}>{c.initial}</span>
              <span className={styles.number}>{c.day}</span>
            </th>
          ))}
          {hasAverage && <th scope="col" className={styles.averageHead}>Media</th>}
        </tr>
      </thead>
      <tbody>
        {grid.rows.map((row) => (
          <tr key={row.code} className={styles.row}>
            <th scope="row" className={styles.name}>
              <a href={row.href} className={styles.link}>{row.name}</a>
            </th>
            {row.cells.map((cell, i) => (
              <td key={grid.columns[i].date} className={styles.cell}>
                <span
                  role="img"
                  className={styles.dot}
                  data-tone={cell.tone}
                  aria-label={`${row.name}, ${shortDate(grid.columns[i].date)}: ${cell.text}`}
                />
              </td>
            ))}
            {row.average !== null && <td className={styles.average}>{row.average}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PeriodPanel({ model, signInHref }: { model: PeriodPanelModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame role="status" busy>
          <p className={styles.body}>Cargando los últimos días…</p>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'DENIED':
      return <Frame role="alert" tone="warn"><p className={styles.body}>No tienes acceso a este historial de días.</p></Frame>;
    case 'SESSION':
      return (
        <Frame role="alert" tone="warn">
          <p className={styles.body}>Inicia sesión para ver tus días.</p>
          <a className={styles.retry} href={signInHref}>Iniciar sesión</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame role="alert" tone="warn">
          <p className={styles.body}>El historial de días no responde ahora. Inténtalo de nuevo.</p>
          <RetryButton className={styles.retry} />
        </Frame>
      );
    case 'INVALID':
      return <Frame role="alert" tone="warn"><p className={styles.body}>No se pudo leer el historial de días.</p></Frame>;
    case 'NOT_CONFIGURED':
      return <Frame role="alert" tone="warn"><p className={styles.body}>La vista Días solo funciona con datos reales.</p></Frame>;
    case 'PERIOD':
      return (
        <Frame>
          <div className={styles.card}>
            <h2 className={styles.heading}>{model.title}</h2>
            {model.grids.map((grid) => <GridView key={grid.columns[0].date} grid={grid} many={model.grids.length > 1} />)}
            <ul className={styles.legend} aria-label="Leyenda">
              {model.legend.map((item) => (
                <li key={item.tone} className={styles.legendItem} data-testid="legend-item">
                  <span className={styles.dot} data-tone={item.tone} aria-hidden="true" />
                  {item.words}
                </li>
              ))}
            </ul>
            <p className={styles.note}>La media usa solo días cerrados y completos.</p>
            {model.profileHint && (
              <div className={styles.hint}>
                <p className={styles.note}>Sin perfil completo no hay objetivos de energía ni proteína con que comparar.</p>
                <ChatPrompt label="Copiar «Quiero crear mi perfil»" prompt="Quiero crear mi perfil" />
              </div>
            )}
          </div>
          <section className={styles.card} aria-labelledby="micro-title">
            <h2 id="micro-title" className={styles.heading}>Vitaminas y minerales{' '}· media</h2>
            <WeeklyStatus groups={model.micro} />
          </section>
        </Frame>
      );
  }
}
