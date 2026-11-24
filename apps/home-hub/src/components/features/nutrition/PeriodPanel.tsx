import type { ReactNode } from 'react';
import { HUB_BASE_PATH } from '@/integration/basePath';
import type { RangeDays } from '@/integration/nutrition/period-range';
import { ChatPrompt } from './ChatPrompt';
import type { Cell, PeriodPanelModel, PeriodRow } from './period-panel-model';
import { RetryButton } from './RetryButton';
import styles from './PeriodPanel.module.css';

const COLUMNS = ['Energía', 'Prot.', 'Fibra', 'Azúcares'];
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

/** Links `?dias=<n>`; keeps `person` only when it is in the URL. */
export function RangeLinks({ range, person }: { range: RangeDays; person: string | null }) {
  return (
    <nav lang="es" aria-label="Rango de días" className={styles.range}>
      {RANGES.map((n) => {
        const query = new URLSearchParams();
        if (person !== null) query.set('person', person);
        query.set('dias', String(n));
        return (
          <a
            key={n}
            href={`${HUB_BASE_PATH}/nutrition/dias?${query.toString()}`}
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

function CellView({ cell }: { cell: Cell }) {
  return (
    <td className={cell.unknown ? styles.unknown : undefined}>
      <span className={styles.value}>{cell.value}</span>
      {cell.detail && <span className={styles.detail}>{cell.detail}</span>}
    </td>
  );
}

function RowView({ row, average }: { row: PeriodRow; average?: boolean }) {
  return (
    <tr className={average ? styles.average : undefined}>
      <th scope="row">
        <span className={styles.day}>{row.day}</span>
        {row.status && row.tone && (
          <span className={`${styles.pill} ${styles[row.tone]}`}>{row.status}</span>
        )}
      </th>
      {row.cells.map((cell, i) => <CellView key={i} cell={cell} />)}
    </tr>
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
          <RetryButton label="Reintentar" pendingLabel="Reintentando…" className={styles.retry} />
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
            <div className={styles.scroller} role="region" aria-label={model.title} tabIndex={0}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Día</th>
                    {COLUMNS.map((c) => <th key={c} scope="col">{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {model.rows.map((row, i) => <RowView key={i} row={row} />)}
                  <RowView row={model.average} average />
                </tbody>
              </table>
            </div>
            <p className={styles.note}>
              La media usa solo días cerrados y completos. Un día abierto o un dato que falta se muestra tal cual, nunca como 0.
            </p>
            {model.profileHint && (
              <div className={styles.hint}>
                <p className={styles.note}>Sin perfil no hay objetivos con que comparar.</p>
                <ChatPrompt label="Copiar «Quiero crear mi perfil»" prompt="Quiero crear mi perfil" />
              </div>
            )}
          </div>
          <div className={styles.placeholders}>
            <div className={styles.placeholder}>
              <h3 className={styles.placeholderTitle}>Actividad y partidos</h3>
              <p className={styles.note}>Llega con el registro de salud (proyecto 2).</p>
            </div>
            <div className={styles.placeholder}>
              <h3 className={styles.placeholderTitle}>Patrones</h3>
              <p className={styles.note}>Llega en el proyecto 3, para que los confirmes o descartes.</p>
            </div>
          </div>
        </Frame>
      );
  }
}
