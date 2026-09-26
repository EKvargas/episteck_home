'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './OrganicRelationshipSwitcher.module.css';

export function OrganicRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      <div className={styles.vineRunner} aria-hidden="true" />
      {contexts.map((context) => {
        const active = context.id === activeContextId;
        const sizeClass = context.mode === 'PERSONAL' ? styles.potTileLarge : styles.potTileSmall;
        return (
          <button key={context.id} type="button" role="tab" aria-selected={active}
            aria-label={`${context.name} ${context.mode === 'FAMILY' ? 'Circle' : context.mode === 'PERSONAL' ? 'Personal' : 'Care'} Context`}
            onClick={() => onSelectContext(context.id)} className={styles.potButton}>
            <span className={`${styles.potTile} ${sizeClass} ${active ? context.mode === 'PERSONAL' ? styles.activePotLarge : styles.activePot : ''}`}>
              <span className={`${styles.potEmoji} ${sizeClass === styles.potTileLarge ? styles.potEmojiLarge : styles.potEmojiSmall}`}>
                {context.mode === 'FAMILY' ? '🌿' : context.mode === 'PERSONAL' ? '🪴' : '🌱'}
              </span>
            </span>
            <span className={`${styles.potLabel} ${active ? styles.activeLabel : ''}`}>{context.name}</span>
          </button>
        );
      })}
    </nav>
  );
}
