'use client';
import React from 'react';
import { TodayHeaderProps } from '../types';

export function DefaultTodayHeader({
  timeIndicator,
  greetingText,
}: TodayHeaderProps) {
  return (
    <header style={{ marginBottom: '1.5rem' }}>
      <span style={{ fontSize: '0.8125rem', color: 'var(--olin-text-muted)' }}>{timeIndicator}</span>
      <h1 style={{ fontFamily: 'var(--olin-font-headline)', fontSize: '1.75rem', fontWeight: 700, margin: '0.25rem 0 0 0' }}>
        {greetingText}
      </h1>
    </header>
  );
}
