import type { ReactNode } from 'react';
import { RetryButton } from './RetryButton';
import { WeeklyStatus } from './WeeklyStatus';
import type { WeeklyPanelModel } from './weekly-model';
import styles from './WeeklyPanel.module.css';

function Frame({ title, role, busy, children }: {
  title: string; role?: 'status' | 'alert'; busy?: boolean; children: ReactNode;
}) {
  return (
    <section
      lang="es"
      className={styles.panel}
      role={role}
      aria-busy={busy || undefined}
      aria-labelledby="weekly-title"
      data-testid="weekly-panel"
    >
      <h2 id="weekly-title" className={styles.title}>{title}</h2>
      {children}
    </section>
  );
}

/** Renders alone: it needs nothing from the day panel, and a failure here stays inside this section. */
export function WeeklyPanel({ model, title }: { model: WeeklyPanelModel; title: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame title={title} role="status" busy>
          <p className={styles.body}>Cargando la semana…</p>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'DENIED':
      return <Frame title={title} role="alert"><p className={styles.body}>No tienes acceso a este resumen.</p></Frame>;
    case 'SESSION':
      return <Frame title={title} role="alert"><p className={styles.body}>Inicia sesión para ver el resumen.</p></Frame>;
    case 'UNAVAILABLE':
      return (
        <Frame title={title} role="alert">
          <p className={styles.body}>El resumen de la semana no responde ahora.</p>
          <RetryButton />
        </Frame>
      );
    case 'INVALID':
      return <Frame title={title} role="alert"><p className={styles.body}>No se pudo leer el resumen de la semana.</p></Frame>;
    case 'NOT_CONFIGURED':
      return <Frame title={title} role="alert"><p className={styles.body}>El resumen solo funciona con datos reales.</p></Frame>;
    case 'WEEK':
      return <Frame title={title}><WeeklyStatus groups={model.groups} /></Frame>;
    default: {
      const unmapped: never = model;
      void unmapped;
      return null;
    }
  }
}
