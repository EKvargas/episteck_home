import { Fragment, type ReactNode } from 'react';
import type { ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { ChatPrompt } from './ChatPrompt';
import { RetryButton } from './RetryButton';
import styles from './ProfilePanel.module.css';

const CREATE_PROMPT = { label: 'Copiar «Quiero crear mi perfil»', prompt: 'Quiero crear mi perfil' };
const BOT_LEAD = 'Tu bot te hace unas ocho preguntas y calcula tus objetivos.';
const CHANGE_LABEL = 'Cambiar en el chat';
const CHANGE_BASICS = 'Quiero cambiar mi perfil: [dato] ahora es [valor]. Muéstrame los objetivos nuevos antes de guardar.';
const CHANGE_FOOD = 'Quiero cambiar mis preferencias de comida: [lo que me gusta, lo que no me gusta o intolerancias]. Muéstramelo antes de guardar.';

function Frame({ title, pill, role, tone, busy, children }: {
  title: string; pill?: string | null; role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children?: ReactNode;
}) {
  return (
    <section
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      lang="es"
      data-testid="profile-panel"
    >
      <h2 className={styles.title}>
        {title}
        {pill && <span className={styles.pill}>{pill}</span>}
      </h2>
      {children}
    </section>
  );
}

function Card({ id, title, aside, children }: { id: string; title: string; aside?: string; children: ReactNode }) {
  return (
    <section className={styles.card} aria-labelledby={id}>
      <div className={styles.cardHead}>
        <h3 id={id} className={styles.cardTitle}>{title}</h3>
        {aside && <span className={styles.aside}>{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: { label: string; value: string }[] }) {
  return (
    <dl className={styles.facts}>
      {rows.map((row) => (
        <Fragment key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></Fragment>
      ))}
    </dl>
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
        <Frame title={model.subjectName ? `Perfil de ${model.subjectName}` : 'Perfil'} pill={model.modePill}>
          {!model.onboarded && (
            <div className={styles.offer}>
              <p className={styles.body}>Todavía no hay perfil completo.</p>
              <ChatPrompt {...CREATE_PROMPT} lead={BOT_LEAD} />
            </div>
          )}
          <Card id="perfil-basicos" title="Datos básicos">
            <Facts rows={model.basics} />
            <ChatPrompt label={CHANGE_LABEL} prompt={CHANGE_BASICS} />
          </Card>
          <Card id="perfil-comida" title="Comida">
            <Facts rows={model.food} />
            <ChatPrompt label={CHANGE_LABEL} prompt={CHANGE_FOOD} />
          </Card>
          <Card id="perfil-objetivos" title="Objetivos diarios" aside={model.targetsSince}>
            {model.targets.length > 0 && (
              <ul className={styles.targets}>
                {model.targets.map((t) => (
                  <li key={t.label} className={styles.target}>
                    <span className={styles.targetLabel}>{t.label}</span>
                    <span className={styles.targetValue}>{t.value}</span>
                    <span className={styles.targetSource}>{t.source}</span>
                  </li>
                ))}
              </ul>
            )}
            {model.missing.map((line) => <p key={line} className={styles.missing}>{line}</p>)}
            <p className={styles.note}>{model.note}</p>
          </Card>
          <Card id="perfil-historial" title="Historial">
            <ul className={styles.history}>
              {model.history.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}
            </ul>
          </Card>
        </Frame>
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
          <RetryButton label="Reintentar" pendingLabel="Reintentando…" />
        </Frame>
      );
    case 'INVALID':
      return (
        <Frame title="No se pudo mostrar el perfil con seguridad" role="alert" tone="warn">
          <RetryButton label="Reintentar" pendingLabel="Reintentando…" />
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
