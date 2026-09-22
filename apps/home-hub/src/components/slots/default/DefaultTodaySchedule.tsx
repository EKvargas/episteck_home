'use client';
import React from 'react';
import { TodayScheduleProps } from '../types';
import styles from './DefaultSlots.module.css';

export function DefaultTodaySchedule({
  title,
  events,
}: TodayScheduleProps) {
  return (
    <div className={styles.defaultCard}>
      <div className={styles.defaultHeader}>
        <h2 className={styles.defaultTitle}>{title}</h2>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {events.map((ev) => (
          <div
            key={ev.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              padding: '0.5rem',
              background: 'rgba(0,0,0,0.03)',
              borderRadius: '0.5rem',
            }}
          >
            <span style={{ fontFamily: 'var(--olin-font-mono)', fontSize: '0.75rem', color: 'var(--olin-accent)' }}>
              {ev.time}
            </span>
            <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--olin-text-main)' }}>
              {ev.title}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
