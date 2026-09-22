// src/components/slots/organic/OrganicRelationshipSwitcher.tsx
'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './OrganicRelationshipSwitcher.module.css';

export function OrganicRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  return (
    <nav
      aria-label="Botanical Relationship Switcher"
      className={styles.container}
    >
      {/* Trailing Vine Runner connecting the potted plants */}
      <div className={styles.vineRunner} aria-hidden="true" />

      {/* Family Pot */}
      <button
        type="button"
        role="tab"
        aria-selected={isFamily}
        aria-label="Family Context"
        onClick={() => onSelectContext('CIR-fam')}
        className={styles.potButton}
      >
        <div
          className={`${styles.potTile} ${styles.potTileSmall} ${
            isFamily ? styles.activePot : ''
          }`}
        >
          <span className={`${styles.potEmoji} ${styles.potEmojiSmall}`}>
            🌿
          </span>
        </div>
        <span
          className={`${styles.potLabel} ${
            isFamily ? styles.activeLabel : ''
          }`}
        >
          Family
        </span>
      </button>

      {/* Erick Pot (Center / Primary) */}
      <button
        type="button"
        role="tab"
        aria-selected={isErick}
        aria-label="Erick Personal Context"
        onClick={() => onSelectContext('PSN-me')}
        className={styles.potButton}
      >
        <div
          className={`${styles.potTile} ${styles.potTileLarge} ${
            isErick ? styles.activePotLarge : ''
          }`}
        >
          <span className={`${styles.potEmoji} ${styles.potEmojiLarge}`}>
            🪴
          </span>
        </div>
        <span
          className={`${styles.potLabel} ${
            isErick ? styles.activeLabel : ''
          }`}
        >
          Erick
        </span>
      </button>

      {/* Ana Pot */}
      <button
        type="button"
        role="tab"
        aria-selected={isAna}
        aria-label="Ana Care Context"
        onClick={() => onSelectContext('PSN-ana')}
        className={styles.potButton}
      >
        <div
          className={`${styles.potTile} ${styles.potTileSmall} ${
            isAna ? styles.activePot : ''
          }`}
        >
          <span className={`${styles.potEmoji} ${styles.potEmojiSmall}`}>
            🌸
          </span>
        </div>
        <span
          className={`${styles.potLabel} ${
            isAna ? styles.activeLabel : ''
          }`}
        >
          Ana
        </span>
      </button>
    </nav>
  );
}
