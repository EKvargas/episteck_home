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
        <p className={styles.subtitle}>Manage appearance, privacy, and personal data permissions.</p>
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
                Durable personal preferences and household context used to adapt responses.
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
            Only authorized members of the Vargas Household have access. Memories are never shared externally or trained on public models.
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
              <h2 className={styles.cardTitle}>Home Control Plane Consent</h2>
              <p className={styles.cardSubtitle}>
                Domain services (Health, Nutrition, Physical Home) enforce local cryptographic consent grants.
              </p>
            </div>
          </div>
        </div>

        <div style={{ fontSize: '0.85rem', color: 'var(--olin-text-muted)', lineHeight: 1.5 }}>
          Active Circle: <strong>Vargas Household</strong> · Care Relationship: <strong>Erick ➔ Ana (Full Clinical Consent)</strong>.
        </div>
      </section>
    </div>
  );
}
