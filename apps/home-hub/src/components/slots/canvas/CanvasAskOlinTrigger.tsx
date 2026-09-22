// src/components/slots/canvas/CanvasAskOlinTrigger.tsx
'use client';
import React from 'react';
import { AskOlinTriggerProps } from '../types';
import styles from './CanvasAskOlinTrigger.module.css';

export function CanvasAskOlinTrigger({
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
        <span className={styles.subtitle}>Family Assistant</span>
      </div>
    </button>
  );
}
