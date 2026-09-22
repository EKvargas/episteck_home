'use client';
import React from 'react';
import { AskOlinTriggerProps } from '../types';

export function DefaultAskOlinTrigger({
  onToggleModal,
}: AskOlinTriggerProps) {
  return (
    <div style={{ position: 'fixed', bottom: '1.5rem', right: '1.5rem', zIndex: 40 }}>
      <button
        type="button"
        onClick={onToggleModal}
        style={{
          padding: '0.75rem 1.25rem',
          borderRadius: '9999px',
          background: 'var(--olin-surface-card)',
          border: '1px solid var(--olin-surface-border)',
          color: 'var(--olin-text-main)',
          fontWeight: 600,
          boxShadow: 'var(--olin-shadow-elevation)',
          cursor: 'pointer',
        }}
      >
        Ask Olin
      </button>
    </div>
  );
}
