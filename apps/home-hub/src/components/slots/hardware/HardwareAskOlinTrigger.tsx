// src/components/slots/hardware/HardwareAskOlinTrigger.tsx
'use client';
import React from 'react';
import { Microphone } from '@phosphor-icons/react';
import { AskOlinTriggerProps } from '../types';
import styles from './HardwareAskOlinTrigger.module.css';

export function HardwareAskOlinTrigger({
  isOpen,
  onToggleModal,
}: AskOlinTriggerProps) {
  return (
    <button
      type="button"
      onClick={onToggleModal}
      className={styles.triggerButton}
      aria-label="Ask Olin Voice & Terminal"
      aria-expanded={isOpen}
    >
      <div className={styles.micBadge} aria-hidden="true">
        <Microphone size={14} weight="bold" />
      </div>
      <span className={styles.triggerText}>ASK OLIN</span>
    </button>
  );
}
