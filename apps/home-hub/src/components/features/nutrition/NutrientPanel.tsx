import type { ReactNode } from 'react';
import type { NutrientDetailModel } from './nutrient-detail-model';
import { RetryButton } from './RetryButton';
import { StatusBar } from './StatusBar';
import styles from './NutrientPanel.module.css';

function Frame({ role, tone, busy, children }: {
  role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children: ReactNode;
}) {
  return (
    <section
      lang="es"
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      data-testid="nutrient-panel"
    >
      {children}
    </section>
  );
}

export function NutrientPanel({ model, signInHref }: { model: NutrientDetailModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame role="status" busy>
          <p className={styles.body}>Cargando el nutriente…</p>
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
      return <Frame role="alert" tone="warn"><p className={styles.body}>La vista de nutriente solo funciona con datos reales.</p></Frame>;
    case 'DETAIL':
      return (
        <Frame>
          <section className={styles.top} aria-labelledby="nutrient-name">
            <h2 id="nutrient-name" className={styles.name}>{model.name}</h2>
            <p className={styles.summary}>
              <span className={styles.average}>Media {model.average}</span>
              {model.target !== null && <span> · objetivo {model.target}</span>}
            </p>
            {model.state.word !== null && (
              <p className={styles.state} data-tone={model.state.tone} data-testid="detail-state">
                <span className={styles.mark} aria-hidden="true" />
                <span>
                  {model.state.word}
                  {model.state.detail !== null && <span className={styles.stateDetail}> · {model.state.detail}</span>}
                </span>
              </p>
            )}
          </section>
          <ol className={styles.days} aria-label="Un día por fila">
            {model.days.map((d) => (
              <li key={d.day} className={styles.day} data-testid="detail-day" data-tone={d.tone}>
                <span className={styles.dayName}>{d.day}</span>
                <span className={styles.dayBody}>
                  {d.bar !== null && <StatusBar bar={d.bar} tone={d.tone} />}
                  <span className={styles.dayText}>
                    {d.value !== null && <span className={styles.value}>{d.value}</span>}
                    {d.word !== null && <span className={styles.word} data-tone={d.tone}>{d.word}</span>}
                    {d.note !== null && <span className={styles.note}>{d.note}</span>}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <div className={styles.about}>
            {model.targetLine !== null && <p className={styles.targetLine}>{model.targetLine}</p>}
            <a className={styles.profileLink} href={model.profileLink.href}>{model.profileLink.text}</a>
          </div>
        </Frame>
      );
  }
}
