'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './AmbientRelationshipSwitcher.module.css';

export function AmbientRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  return (
    <nav
      aria-label="Household Context Switcher"
      className={styles.container}
    >
      {/* Connecting orbital constellation fiber */}
      <div className={styles.orbitalFiber} aria-hidden="true" />

      {/* Family Node */}
      <button
        type="button"
        role="tab"
        aria-selected={isFamily}
        aria-label="Family context"
        onClick={() => onSelectContext('CIR-fam')}
        className={styles.nodeButton}
      >
        <div
          className={`${styles.starOrbSmall} ${isFamily ? `${styles.activeFamily} stellar-active` : ''}`}
        >
          <span
            className={`${styles.innerDotSmall} ${isFamily ? styles.innerDotSmallActive : ''}`}
          />
        </div>
        <span
          className={`${styles.nodeLabel} ${isFamily ? styles.activeFamilyLabel : ''}`}
        >
          Family
        </span>
      </button>

      {/* Erick Node (Center / Primary) */}
      <button
        type="button"
        role="tab"
        aria-selected={isErick}
        aria-label="Erick personal context"
        onClick={() => onSelectContext('PSN-me')}
        className={styles.nodeButton}
      >
        <div
          className={`${styles.starOrbLarge} ${isErick ? `${styles.activeErick} stellar-active` : ''}`}
        >
          <div
            className={`${styles.innerDotLarge} ${isErick ? styles.innerDotLargeActive : ''}`}
          />
        </div>
        <span
          className={`${styles.nodeLabel} ${isErick ? styles.activeErickLabel : ''}`}
        >
          Erick
        </span>
      </button>

      {/* Ana Node */}
      <button
        type="button"
        role="tab"
        aria-selected={isAna}
        aria-label="Ana care context"
        onClick={() => onSelectContext('PSN-ana')}
        className={styles.nodeButton}
      >
        <div
          className={`${styles.starOrbSmall} ${isAna ? `${styles.activeAna} stellar-active` : ''}`}
        >
          <span
            className={`${styles.innerDotSmall} ${isAna ? styles.innerDotSmallActive : ''}`}
          />
        </div>
        <span
          className={`${styles.nodeLabel} ${isAna ? styles.activeAnaLabel : ''}`}
        >
          Ana
        </span>
      </button>
    </nav>
  );
}
