// src/app/settings/privacy/page.tsx
'use client';

import React from 'react';
import Link from 'next/link';
import { Brain, ArrowRight, ShieldCheck, Lock } from '@phosphor-icons/react';
import styles from './page.module.css';

export default function PrivacySettingsPage() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Settings</h1>
        <p className={styles.subtitle}>Preview appearance and privacy controls. Permission controls are not active in this prototype.</p>
      </header>

      {/* Settings Sub-tabs */}
      <nav className={styles.tabsRow} aria-label="Settings categories">
        <Link href="/settings/appearance" className={styles.tabLink}>
          Appearance
        </Link>
        <Link href="/settings/privacy" className={`${styles.tabLink} ${styles.tabLinkActive}`}>
          Privacy &amp; Data
        </Link>
      </nav>

      {/* Compact Memory Status Card */}
      <section className={styles.card} aria-labelledby="memory-status-title">
        <div className={styles.cardHeader}>
          <div className={styles.cardTitleArea}>
            <div className={styles.iconCircle}>
              <Brain size={22} weight="fill" />
            </div>
            <div>
              <h2 id="memory-status-title" className={styles.cardTitle}>What Olin remembers</h2>
              <p className={styles.cardSubtitle}>
                Mock personal preferences and household context used in demo responses.
              </p>
            </div>
          </div>
        </div>

        <div className={styles.statsRow}>
          <div className={styles.statItem}>
            <span className={styles.statNum}>12</span>
            <span className={styles.statLabel}>Active Memories</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statNum} style={{ color: 'var(--olin-accent)' }}>
              1
            </span>
            <span className={styles.statLabel}>Suggestion to Review</span>
          </div>
          <div className={styles.statItem}>
            <span className={styles.statNum}>3</span>
            <span className={styles.statLabel}>Replaced / Inactive</span>
          </div>
        </div>

        <div className={styles.actionRow}>
          <p className={styles.privacyNote}>
            <Lock size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
            These memory counts and controls are demo content. This screen does not establish access or data-sharing policy.
          </p>

          <Link href="/memory" className={styles.linkBtn}>
            Review &amp; Control Memory <ArrowRight size={14} weight="bold" />
          </Link>
        </div>
      </section>

      {/* Data Ownership & Consent Summary */}
      <section className={styles.card}>
        <div className={styles.cardHeader}>
          <div className={styles.cardTitleArea}>
            <div className={styles.iconCircle} style={{ background: 'rgba(16, 185, 129, 0.12)', color: '#10b981' }}>
              <ShieldCheck size={22} weight="fill" />
            </div>
            <div>
              <h2 className={styles.cardTitle}>Consent design preview</h2>
              <p className={styles.cardSubtitle}>
                Domain access and consent enforcement are outside this F2 prototype.
              </p>
            </div>
          </div>
        </div>

        <div style={{ fontSize: '0.85rem', color: 'var(--olin-text-muted)', lineHeight: 1.5 }}>
          Demo Circle: <strong>Vargas Household</strong> · Care relationship display: <strong>Erick and Ana</strong>. No domain permission is inferred.
        </div>
      </section>
    </div>
  );
}
