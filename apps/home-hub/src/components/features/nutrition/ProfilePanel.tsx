import type { ReactNode } from 'react';
import type { ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { RetryButton } from './RetryButton';
import styles from './ProfilePanel.module.css';

function Frame({ title, role, tone, busy, children }: {
  title: string; role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children?: ReactNode;
}) {
  return (
    <section
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      data-testid="profile-panel"
    >
      <h2 className={styles.title}>{title}</h2>
      {children}
    </section>
  );
}

const who = (name: string | null) => name ?? 'this person';

export function ProfilePanel({ model, signInHref }: { model: ProfilePanelModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame title="Checking Nutrition profile…" role="status" busy>
          <p className={styles.body}>Looking up the profile for {who(model.subjectName)}.</p>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'PRESENT':
      return (
        <Frame title="Nutrition profile on file">
          <dl className={styles.facts}>
            <dt>Person</dt><dd>{who(model.subjectName)}</dd>
            <dt>Profile type</dt><dd>{model.contextLabel}</dd>
            <dt>Target source</dt><dd>{model.targetSourceLabel}</dd>
            <dt>Targets</dt><dd>{model.targetCount === 0 ? 'None configured' : `${model.targetCount} configured`}</dd>
          </dl>
          <p className={styles.body}>Target values are not shown on this page yet.</p>
          <p className={styles.badge}>Source: Nutrition service</p>
        </Frame>
      );
    case 'ABSENT':
      return (
        <Frame title={`No nutrition profile for ${who(model.subjectName)}`} role="status">
          <p className={styles.body}>Nothing has been set up in Nutrition for this person yet.</p>
        </Frame>
      );
    case 'DENIED':
      return (
        <Frame title="Access restricted" role="alert" tone="warn">
          <p className={styles.body}>Nutrition information for {who(model.subjectName)} is not available to you.</p>
        </Frame>
      );
    case 'SESSION':
      return (
        <Frame title="Your session has expired" role="alert" tone="warn">
          <p className={styles.body}>Sign in again to see Nutrition information.</p>
          <a className={styles.retry} href={signInHref}>Sign in again</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame title="Nutrition is temporarily unavailable" role="alert" tone="warn">
          <p className={styles.body}>We could not reach Nutrition for {who(model.subjectName)}. Nothing is shown rather than guessing.</p>
          <RetryButton />
        </Frame>
      );
    case 'INVALID':
      return (
        <Frame title="This profile could not be shown safely" role="alert" tone="warn">
          <p className={styles.body}>Nutrition answered with something unexpected, so it was not displayed.</p>
          <RetryButton />
        </Frame>
      );
    case 'NOT_CONFIGURED':
      return (
        <Frame title="Nutrition is not set up on this Hub" role="alert" tone="warn">
          <p className={styles.body}>Ask the Episteck team to finish the Nutrition connection.</p>
        </Frame>
      );
    default: {
      const unmapped: never = model;
      void unmapped;
      return null;
    }
  }
}
