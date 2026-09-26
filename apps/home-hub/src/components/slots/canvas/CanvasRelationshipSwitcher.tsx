'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './CanvasRelationshipSwitcher.module.css';
import { contextAccessibleLabel } from '../contextLabel';

export function CanvasRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      {contexts.map((context) => {
        const active = context.id === activeContextId;
        const activeClass = context.mode === 'FAMILY'
          ? styles.activeFamily
          : context.mode === 'PERSONAL' ? styles.activeErick : styles.activeAna;
        return (
          <button key={context.id} type="button" role="tab" aria-selected={active}
            aria-label={contextAccessibleLabel(context.name, context.mode)}
            onClick={() => onSelectContext(context.id)}
            className={`${styles.nodeButton} ${active ? activeClass : ''}`}>
            {context.name}
          </button>
        );
      })}
    </nav>
  );
}
