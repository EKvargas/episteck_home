'use client';

import React from 'react';
import { Database, LockKey, Moon, Drop, Stethoscope } from '@phosphor-icons/react';
import { useAppContext } from '@/components/providers/AppProvider';
import { getDemoContextId, getTodaySummaryMock } from '@/domain/mocks';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import styles from './page.module.css';

export default function HealthPage() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  const data = getTodaySummaryMock(getDemoContextId(activeContext.mode));

  // Architecture check: if context has no care data, it is heavily restricted or unconfigured.
  const hasCare = !!data.care;

  return (
    <div className={styles.healthCanvas}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Health & Clinical</h1>
          <div style={{ marginTop: '0.75rem' }}>
            <DefaultRelationshipSwitcher
              contexts={availableContexts}
              activeContextId={activeContext.id}
              onSelectContext={(id) => setContext(id)}
            />
          </div>
        </div>
      </header>

      <main className={styles.grid}>
        {hasCare ? (
          <>
            {/* Clinical Consultation (FHIR) */}
            <div className={styles.card} style={{ gridColumn: '1 / -1', borderLeft: '4px solid var(--olin-accent)' }}>
              <div className={styles.cardHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Stethoscope size={24} weight="duotone" color="var(--olin-accent)" />
                  <h2 className={styles.cardTitle}>Clinical Truth</h2>
                </div>
                <div className={styles.provenanceBadge} title="Canonical data source">
                  <Database size={12} weight="fill" />
                  Source: FHIR Gateway
                </div>
              </div>
              <p style={{ color: 'var(--olin-text-muted)', fontSize: '0.9rem', marginBottom: '1rem', maxWidth: '600px', lineHeight: 1.5 }}>
                {data.care!.consultation.description}
              </p>
              
              <div>
                <div className={styles.valueRow}>
                  <span className={styles.valueLabel}>Doctor</span>
                  <span className={styles.valueData}>{data.care!.consultation.doctor}</span>
                </div>
                <div className={styles.valueRow}>
                  <span className={styles.valueLabel}>Facility</span>
                  <span className={styles.valueData}>{data.care!.consultation.clinic} · {data.care!.consultation.room}</span>
                </div>
                <div className={styles.valueRow}>
                  <span className={styles.valueLabel}>Next Checkup</span>
                  <span className={styles.valueData}>{data.care!.consultation.nextCheckup}</span>
                </div>
              </div>
            </div>

            {/* Rest & Recovery (Device Gateway) */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Moon size={24} weight="duotone" color="var(--olin-accent)" />
                  <h2 className={styles.cardTitle}>Rest Rhythm</h2>
                </div>
                <div className={styles.provenanceBadge} title="Device telemetry source">
                  <Database size={12} weight="fill" />
                  Source: Device Gateway
                </div>
              </div>
              
              <div style={{ padding: '1.5rem 0' }}>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--olin-text-main)', marginBottom: '4px' }}>
                  {data.care!.restRhythm.hoursSleep.split(' ').slice(0, 2).join(' ')}
                </div>
                <div style={{ fontSize: '0.875rem', color: 'var(--olin-text-muted)', fontWeight: 500 }}>
                  {data.care!.restRhythm.status}
                </div>
              </div>
            </div>

            {/* Care Hydration */}
            <div className={styles.card}>
              <div className={styles.cardHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Drop size={24} weight="duotone" color="var(--olin-accent)" />
                  <h2 className={styles.cardTitle}>Medical Hydration</h2>
                </div>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: 'auto', paddingTop: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.875rem', fontWeight: 600 }}>
                  <span>Current Volume</span>
                  <span>{data.care!.hydration.litersCurrent} / {data.care!.hydration.litersTarget} L</span>
                </div>
                <div style={{ width: '100%', height: '8px', background: 'var(--olin-badge-bg)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div 
                    style={{ 
                      height: '100%', 
                      background: 'var(--olin-accent)', 
                      borderRadius: '4px',
                      width: `${data.care!.hydration.percentage}%`,
                      transition: 'width 1s cubic-bezier(0.4, 0, 0.2, 1)'
                    }} 
                  />
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className={styles.lockedState}>
            <LockKey size={48} weight="duotone" />
            <span className={styles.lockedText}>Consent required to view clinical health</span>
            <span style={{ fontSize: '0.875rem', maxWidth: '400px', lineHeight: 1.5 }}>
              This domain is strictly protected. An explicit ConsentGrant from the Control Plane is required to view FHIR and device telemetry data.
            </span>
          </div>
        )}
      </main>
    </div>
  );
}
