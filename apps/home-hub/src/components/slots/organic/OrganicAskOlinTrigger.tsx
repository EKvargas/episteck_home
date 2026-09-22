// src/components/slots/organic/OrganicAskOlinTrigger.tsx
'use client';
import React from 'react';
import { AskOlinTriggerProps } from '../types';
import styles from './OrganicAskOlinTrigger.module.css';

export function OrganicAskOlinTrigger({
  isOpen,
  onToggleModal,
}: AskOlinTriggerProps) {
  return (
    <button
      type="button"
      onClick={onToggleModal}
      className={styles.triggerButton}
      aria-label="Ask Olin Family Assistant"
      aria-expanded={isOpen}
    >
      <div className={styles.iconCircle} aria-hidden="true">
        O
      </div>
      <div className={styles.textColumn}>
        <span className={styles.title}>Ask Olin</span>
        <span className={styles.subtitle}>Calm Assistant</span>
      </div>
    </button>
  );
}
