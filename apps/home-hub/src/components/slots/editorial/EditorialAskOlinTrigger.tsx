// src/components/slots/editorial/EditorialAskOlinTrigger.tsx
'use client';
import React from 'react';
import { AskOlinTriggerProps } from '../types';
import styles from './EditorialAskOlinTrigger.module.css';

export function EditorialAskOlinTrigger({
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
      <div className={styles.iconSquare} aria-hidden="true">
        O
      </div>
      <div className={styles.textColumn}>
        <span className={styles.title}>Ask Olin</span>
        <span className={styles.subtitle}>Hermes Ledger</span>
      </div>
    </button>
  );
}
