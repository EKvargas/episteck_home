'use client';
import React from 'react';
import { PhysicalHomeProps } from '../types';
import styles from './DefaultSlots.module.css';

export function DefaultPhysicalHome({
  telemetry,
  doorLocked,
  onToggleDoorLock,
}: PhysicalHomeProps) {
  return (
    <div className={styles.defaultCard}>
      <div className={styles.defaultHeader}>
        <h2 className={styles.defaultTitle}>Physical Home</h2>
      </div>
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '0.75rem', color: 'var(--olin-text-muted)' }}>Living Room</span>
          <p style={{ margin: 0, fontWeight: 700 }}>{telemetry.livingRoom.temp}</p>
        </div>
        <div>
          <span style={{ fontSize: '0.75rem', color: 'var(--olin-text-muted)' }}>Front Door</span>
          <p style={{ margin: 0 }}>
            <button
              type="button"
              onClick={onToggleDoorLock}
              style={{ fontWeight: 600, color: doorLocked ? '#10d290' : '#f6ab63', textDecoration: 'underline' }}
            >
              {doorLocked ? 'Locked' : 'Unlocked'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
