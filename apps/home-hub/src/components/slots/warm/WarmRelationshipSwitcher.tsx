// src/components/slots/warm/WarmRelationshipSwitcher.tsx
'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './WarmRelationshipSwitcher.module.css';

export function WarmRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  return (
    <nav
      aria-label="Household Relationship Switcher"
      className={styles.container}
    >
      {/* Stitched yarn runner connecting the portraits */}
      <div className={styles.stitchedRunner} aria-hidden="true" />

      {/* Family Portrait */}
      <button
        type="button"
        role="tab"
        aria-selected={isFamily}
        aria-label="Family Context"
        onClick={() => onSelectContext('CIR-fam')}
        className={styles.portraitButton}
      >
        <div
          className={`${styles.portraitCircle} ${styles.portraitCircleSmall} ${
            isFamily ? styles.activeCircle : ''
          }`}
        >
          <span className={`${styles.portraitEmoji} ${styles.portraitEmojiSmall}`}>
            👨‍👩‍👧
          </span>
        </div>
        <span
          className={`${styles.portraitLabel} ${
            isFamily ? styles.activeLabel : ''
          }`}
        >
          Family
        </span>
      </button>

      {/* Erick Portrait (Center) */}
      <button
        type="button"
        role="tab"
        aria-selected={isErick}
        aria-label="Erick Personal Context"
        onClick={() => onSelectContext('PSN-me')}
        className={styles.portraitButton}
      >
        <div
          className={`${styles.portraitCircle} ${styles.portraitCircleLarge} ${
            isErick ? styles.activeCircleLarge : ''
          }`}
        >
          <span className={`${styles.portraitEmoji} ${styles.portraitEmojiLarge}`}>
            🧔
          </span>
        </div>
        <span
          className={`${styles.portraitLabel} ${
            isErick ? styles.activeLabel : ''
          }`}
        >
          Erick
        </span>
      </button>

      {/* Ana Portrait */}
      <button
        type="button"
        role="tab"
        aria-selected={isAna}
        aria-label="Ana Care Context"
        onClick={() => onSelectContext('PSN-ana')}
        className={styles.portraitButton}
      >
        <div
          className={`${styles.portraitCircle} ${styles.portraitCircleSmall} ${
            isAna ? styles.activeCircle : ''
          }`}
        >
          <span className={`${styles.portraitEmoji} ${styles.portraitEmojiSmall}`}>
            👩
          </span>
        </div>
        <span
          className={`${styles.portraitLabel} ${
            isAna ? styles.activeLabel : ''
          }`}
        >
          Ana
        </span>
      </button>
    </nav>
  );
}
