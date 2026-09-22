// src/components/slots/editorial/EditorialRelationshipSwitcher.tsx
'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './EditorialRelationshipSwitcher.module.css';

export function EditorialRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  return (
    <nav
      aria-label="Editorial Ledger Index"
      className={styles.container}
    >
      {/* Family Index */}
      <button
        type="button"
        role="tab"
        aria-selected={isFamily}
        aria-label="Family Context Ledger"
        onClick={() => onSelectContext('CIR-fam')}
        className={`${styles.itemButton} ${
          isFamily ? styles.itemButtonActive : ''
        }`}
      >
        {isFamily && <span className={styles.inkRing} aria-hidden="true" />}
        <span>FAMILY</span>
      </button>

      {/* Erick Index */}
      <button
        type="button"
        role="tab"
        aria-selected={isErick}
        aria-label="Erick Personal Ledger"
        onClick={() => onSelectContext('PSN-me')}
        className={`${styles.itemButton} ${
          isErick ? styles.itemButtonActive : ''
        }`}
      >
        {isErick && <span className={styles.inkRing} aria-hidden="true" />}
        <span>ERICK</span>
      </button>

      {/* Ana Index */}
      <button
        type="button"
        role="tab"
        aria-selected={isAna}
        aria-label="Ana Care Ledger"
        onClick={() => onSelectContext('PSN-ana')}
        className={`${styles.itemButton} ${
          isAna ? styles.itemButtonActive : ''
        }`}
      >
        {isAna && <span className={styles.inkRing} aria-hidden="true" />}
        <span>ANA</span>
      </button>
    </nav>
  );
}
