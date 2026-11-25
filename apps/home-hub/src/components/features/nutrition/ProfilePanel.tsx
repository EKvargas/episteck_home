import type { ReactNode } from 'react';
import { CaretRight, Info } from '@phosphor-icons/react/ssr';
import type { ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { ChatPrompt } from './ChatPrompt';
import { RetryButton } from './RetryButton';
import styles from './ProfilePanel.module.css';

const CREATE_PROMPT = { label: 'Copiar «Quiero crear mi perfil»', prompt: 'Quiero crear mi perfil' };
const BOT_LEAD = 'Tu bot te hace unas ocho preguntas y calcula tus objetivos.';
// Like Hoy's prompt: the label names the copy action and quotes the start of the message.
const CHANGE_LABEL = 'Copiar «Quiero cambiar mi perfil»';
const CHANGE_LEAD = 'Los cambios del perfil se hacen en el chat.';
const CHANGE_PROMPT = 'Quiero cambiar mi perfil: [dato] ahora es [valor]. Si es sobre la comida: [lo que me gusta, lo que no me gusta o intolerancias]. Muéstrame los objetivos nuevos antes de guardar.';

/** Error and empty states keep today's framed panel; the profile itself is an open page with one surface per group. */
function Frame({ title, role, tone, busy, children }: {
  title: string; role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children?: ReactNode;
}) {
  return (
    <section
      className={`${styles.panel} ${styles.framed} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      lang="es"
      data-testid="profile-panel"
    >
      <h2 className={styles.title}>{title}</h2>
      {children}
    </section>
  );
}

function Group({ id, title, aside, children }: { id: string; title: string; aside?: string; children: ReactNode }) {
  return (
    <section className={styles.group} aria-labelledby={id}>
      <div className={styles.groupHead}>
        <h3 id={id} className={styles.groupTitle}>{title}</h3>
        {aside && <span className={styles.aside}>{aside}</span>}
      </div>
      {children}
    </section>
  );
}

export function ProfilePanel({ model, signInHref }: { model: ProfilePanelModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame title="Cargando el perfil…" role="status" busy>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'PROFILE':
      return (
        <section className={styles.panel} lang="es" data-testid="profile-panel">
          <header className={styles.top}>
            <h2 className={styles.name}>{model.subjectName ? `Perfil de ${model.subjectName}` : 'Perfil'}</h2>
            {model.dueDate && (
              <p className={styles.due}>
                <span className={styles.dueLabel}>Fecha prevista de parto</span>
                <span className={styles.dueValue}>{model.dueDate}</span>
              </p>
            )}
          </header>
          {!model.onboarded && (
            <div className={styles.offer}>
              <p className={styles.body}>Todavía no hay perfil completo.</p>
              <ChatPrompt {...CREATE_PROMPT} lead={BOT_LEAD} />
            </div>
          )}
          <Group id="perfil-objetivos" title="Objetivos diarios" aside={model.targetsSince}>
            {model.targets.length > 0 && (
              <ul className={`${styles.surface} ${styles.targets}`}>
                {model.targets.map((t) => (
                  <li key={t.label} className={styles.target}>
                    <span className={styles.targetLabel}>{t.label}</span>
                    <span className={styles.targetValue}>{t.value}</span>
                    <details className={styles.why}>
                      <summary className={styles.whySummary} aria-label={`De dónde sale: ${t.label}`}>
                        <Info className={styles.whyIcon} weight="bold" aria-hidden="true" />
                      </summary>
                      <p className={styles.whyBody}>{t.source}</p>
                    </details>
                  </li>
                ))}
              </ul>
            )}
            {model.missing.length > 0 && (
              <div className={styles.missing}>
                <p className={styles.missingTitle}>Faltan datos para…</p>
                <ul className={styles.missingList}>
                  {model.missing.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </div>
            )}
            <p className={styles.note}>{model.note}</p>
          </Group>
          <Group id="perfil-datos" title="Datos">
            <dl className={`${styles.surface} ${styles.facts}`}>
              {model.basics.map((row) => (
                <div key={row.label} className={styles.fact}><dt>{row.label}</dt><dd>{row.value}</dd></div>
              ))}
            </dl>
          </Group>
          <Group id="perfil-comida" title="Comida">
            <div className={`${styles.surface} ${styles.food}`}>
              {model.food.map((row) => (
                <div key={row.label} className={styles.foodRow}>
                  <p className={styles.foodLabel}>{row.label}</p>
                  {row.chips.length === 0 ? <p className={styles.none}>—</p> : (
                    <ul className={styles.chips}>
                      {row.chips.map((chip, index) => <li key={`${index}-${chip}`} className={styles.chip}>{chip}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </Group>
          <details className={styles.history}>
            <summary className={styles.historySummary}>
              <CaretRight className={styles.caret} weight="bold" aria-hidden="true" />
              Historial
            </summary>
            <ul className={styles.historyList}>
              {model.history.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}
            </ul>
          </details>
          <ChatPrompt label={CHANGE_LABEL} prompt={CHANGE_PROMPT} lead={CHANGE_LEAD} />
        </section>
      );
    case 'ABSENT':
      return (
        <Frame title="Sin perfil de nutrición" role="status">
          <ChatPrompt {...CREATE_PROMPT} lead={BOT_LEAD} />
        </Frame>
      );
    case 'DENIED':
      return (
        <Frame title="Acceso restringido" role="alert" tone="warn">
          <p className={styles.body}>No tienes acceso al perfil de nutrición de {model.subjectName ?? 'esta persona'}.</p>
        </Frame>
      );
    case 'SESSION':
      return (
        <Frame title="Tu sesión ha caducado" role="alert" tone="warn">
          <a className={styles.retry} href={signInHref}>Iniciar sesión</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame title="Nutrición no responde ahora" role="alert" tone="warn">
          <p className={styles.body}>No se muestra nada antes que adivinar.</p>
          <RetryButton />
        </Frame>
      );
    case 'INVALID':
      return (
        <Frame title="No se pudo mostrar el perfil con seguridad" role="alert" tone="warn">
          <RetryButton />
        </Frame>
      );
    case 'NOT_CONFIGURED':
      return (
        <Frame title="Nutrición no está configurada en este Hub" role="alert" tone="warn" />
      );
    default: {
      const unmapped: never = model;
      void unmapped;
      return null;
    }
  }
}
