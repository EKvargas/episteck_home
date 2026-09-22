'use client';
import React from 'react';
import { LockKey, Database } from '@phosphor-icons/react';
import { WellbeingNutritionProps } from '../types';
import styles from './DefaultSlots.module.css';

export function DefaultWellbeingNutrition({
  title,
  nutrition,
}: WellbeingNutritionProps) {
  return (
    <div className={styles.defaultCard}>
      <div className={styles.defaultHeader}>
        <h2 className={styles.defaultTitle}>{title}</h2>
      </div>
      {nutrition ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>
              {nutrition.calories}
            </span>
            <span style={{ color: 'var(--olin-text-muted)', fontSize: '0.875rem' }}>
              {' '}/ {nutrition.targetCalories} kcal
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--olin-text-muted)', opacity: 0.8 }}>
             <Database size={12} weight="fill" /> Provenance: svc-nutrition
          </div>
        </div>
      ) : (
        <div style={{ 
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          gap: '12px', padding: '32px 0', color: 'var(--olin-text-muted)',
          background: 'var(--olin-badge-bg)', borderRadius: '12px', border: '1px dashed var(--olin-surface-border)'
        }}>
          <LockKey size={24} weight="duotone" />
          <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Consent required for clinical truth</span>
        </div>
      )}
    </div>
  );
}
