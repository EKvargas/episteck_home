import type { ReactNode } from 'react';
import type { TodayPanelModel } from './today-panel-model';
import { RetryButton } from './RetryButton';
import styles from './TodayPanel.module.css';

function Frame({ role, tone, busy, children }: {
  role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children: ReactNode;
}) {
  return (
    <section
      lang="es"
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      data-testid="today-panel"
    >
      {children}
    </section>
  );
}

export function TodayPanel({ model, signInHref }: { model: TodayPanelModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame role="status" busy>
          <p className={styles.body}>Cargando tu día…</p>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'DENIED':
      return <Frame role="alert" tone="warn"><p className={styles.body}>No tienes acceso a este diario.</p></Frame>;
    case 'SESSION':
      return (
        <Frame role="alert" tone="warn">
          <p className={styles.body}>Inicia sesión para ver tu día.</p>
          <a className={styles.retry} href={signInHref}>Iniciar sesión</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame role="alert" tone="warn">
          <p className={styles.body}>El diario no responde ahora. Inténtalo de nuevo.</p>
          <RetryButton />
        </Frame>
      );
    case 'INVALID':
      return <Frame role="alert" tone="warn"><p className={styles.body}>No se pudo leer el diario.</p></Frame>;
    case 'NOT_CONFIGURED':
      return <Frame role="alert" tone="warn"><p className={styles.body}>La vista Hoy solo funciona con datos reales.</p></Frame>;
    case 'TODAY':
      return (
        <Frame>
          <div className={styles.dailyHero}>
            <div className={styles.overview}>
              <h2 className={styles.heading}>{model.heading}</h2>
              <p className={styles.big}>{model.sugarLine}</p>
              {model.meter && (
                <meter
                  className={styles.meter}
                  min={0}
                  max={model.meter.limitG}
                  value={Math.min(model.meter.valueG, model.meter.limitG)}
                  aria-label={model.sugarLine}
                />
              )}
              <p className={styles.status}>{model.statusLine}</p>
              {model.referenceLine && <p className={styles.reference}>{model.referenceLine}</p>}
            </div>
          </div>
          {model.entries.length > 0 && (
            <div className={styles.timeline}>
              <h3 className={styles.timelineTitle}>Lo que has anotado</h3>
              {model.entries.map((entry, index) => (
                <div key={index} className={styles.timelineRow}>
                  <span className={styles.time}>{entry.time}</span>
                  <ul className={styles.meal}>
                    {entry.items.map((item, i) => (
                      <li key={i} className={styles.item}>
                        <span className={styles.itemText}>{item.text}</span>
                        <span className={styles.sugar}>Azúcares libres: {item.sugar}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          {model.attribution.length > 0 && (
            <div className={styles.attribution}>
              {model.attribution.map((text, i) => <p key={i}>{text}</p>)}
            </div>
          )}
        </Frame>
      );
    default: {
      const unmapped: never = model;
      void unmapped;
      return null;
    }
  }
}
