// src/components/slots/canvas/CanvasRelationshipSwitcher.tsx
'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './CanvasRelationshipSwitcher.module.css';

export function CanvasRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  return (
    <nav
      aria-label="Family Canvas Mode Selector"
      className={styles.container}
    >
      {/* Family Pill */}
      <button
        type="button"
        role="tab"
        aria-selected={isFamily}
        aria-label="Family Context"
        onClick={() => onSelectContext('CIR-fam')}
        className={`${styles.nodeButton} ${
          isFamily ? styles.activeFamily : ''
        }`}
      >
        Family
      </button>

      {/* Erick Pill */}
      <button
        type="button"
        role="tab"
        aria-selected={isErick}
        aria-label="Erick Personal Context"
        onClick={() => onSelectContext('PSN-me')}
        className={`${styles.nodeButton} ${
          isErick ? styles.activeErick : ''
        }`}
      >
        Erick
      </button>

      {/* Ana Pill */}
      <button
        type="button"
        role="tab"
        aria-selected={isAna}
        aria-label="Ana Care Context"
        onClick={() => onSelectContext('PSN-ana')}
        className={`${styles.nodeButton} ${
          isAna ? styles.activeAna : ''
        }`}
      >
        Ana
      </button>
    </nav>
  );
}
