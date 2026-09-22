'use client';
import React from 'react';
import { Sparkle, CaretUp } from '@phosphor-icons/react';
import { AskOlinTriggerProps } from '../types';
import styles from './AmbientAskOlinTrigger.module.css';

export function AmbientAskOlinTrigger({
  isOpen,
  onToggleModal,
}: AskOlinTriggerProps) {
  return (
    <div className={styles.triggerContainer}>
      <button
        type="button"
        onClick={onToggleModal}
        className={styles.triggerButton}
        aria-expanded={isOpen}
        aria-label="Ask Olin Assistant"
      >
        <div className={styles.sparkleOrb} aria-hidden="true">
          <Sparkle size={15} weight="fill" />
        </div>
        <div className={styles.textBlock}>
          <span className={styles.title}>Ask Olin</span>
          <span className={styles.subtitle}>Hermes Orchestration</span>
        </div>
        <CaretUp
          size={16}
          weight="bold"
          className={`${styles.chevronIcon} ${isOpen ? styles.chevronOpen : ''}`}
          aria-hidden="true"
        />
      </button>
    </div>
  );
}
