'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './WarmRelationshipSwitcher.module.css';

export function WarmRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      <div className={styles.stitchedRunner} aria-hidden="true" />
      {contexts.map((context) => {
        const active = context.id === activeContextId;
        const family = context.mode === 'FAMILY';
        const sizeClass = !family && context.mode === 'PERSONAL' ? styles.portraitCircleLarge : styles.portraitCircleSmall;
        return (
          <button key={context.id} type="button" role="tab" aria-selected={active}
            aria-label={`${context.name} ${context.mode === 'FAMILY' ? 'Circle' : context.mode === 'PERSONAL' ? 'Personal' : 'Care'} Context`}
            onClick={() => onSelectContext(context.id)} className={styles.portraitButton}>
            <span className={`${styles.portraitCircle} ${sizeClass} ${active ? family || context.mode !== 'PERSONAL' ? styles.activeCircle : styles.activeCircleLarge : ''}`}>
              <span className={`${styles.portraitEmoji} ${sizeClass === styles.portraitCircleLarge ? styles.portraitEmojiLarge : styles.portraitEmojiSmall}`}>
                {family ? '👨‍👩‍👧' : context.mode === 'PERSONAL' ? '🧑' : '👤'}
              </span>
            </span>
            <span className={`${styles.portraitLabel} ${active ? styles.activeLabel : ''}`}>{context.name}</span>
          </button>
        );
      })}
    </nav>
  );
}
