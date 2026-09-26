'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './AmbientRelationshipSwitcher.module.css';
import { contextAccessibleLabel } from '../contextLabel';

export function AmbientRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      <div className={styles.orbitalFiber} aria-hidden="true" />
      {contexts.map((context) => {
        const active = context.id === activeContextId;
        const family = context.mode === 'FAMILY';
        const sizeClass = context.mode === 'PERSONAL' ? styles.starOrbLarge : styles.starOrbSmall;
        const activeClass = family ? styles.activeFamily : context.mode === 'PERSONAL' ? styles.activeErick : styles.activeAna;
        const labelClass = family ? styles.activeFamilyLabel : context.mode === 'PERSONAL' ? styles.activeErickLabel : styles.activeAnaLabel;
        return (
          <button key={context.id} type="button" role="tab" aria-selected={active}
            aria-label={contextAccessibleLabel(context.name, context.mode)}
            onClick={() => onSelectContext(context.id)} className={styles.nodeButton}>
            <span className={`${sizeClass} ${active ? activeClass : ''}`}>
              {context.mode === 'FAMILY' ? '◉' : context.mode === 'PERSONAL' ? '✦' : '●'}
            </span>
            <span className={`${styles.nodeLabel} ${active ? labelClass : ''}`}>{context.name}</span>
          </button>
        );
      })}
    </nav>
  );
}
