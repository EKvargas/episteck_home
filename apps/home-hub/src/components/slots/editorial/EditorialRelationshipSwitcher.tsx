'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './EditorialRelationshipSwitcher.module.css';

export function EditorialRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      {contexts.map((context) => {
        const active = context.id === activeContextId;
        return (
          <button key={context.id} type="button" role="tab" aria-selected={active}
            aria-label={`${context.name} ${context.mode === 'FAMILY' ? 'Circle' : context.mode === 'PERSONAL' ? 'Personal' : 'Care'} Context`}
            onClick={() => onSelectContext(context.id)}
            className={`${styles.itemButton} ${active ? styles.itemButtonActive : ''}`}>
            {context.name}{active && <span className={styles.inkRing} aria-hidden="true" />}
          </button>
        );
      })}
    </nav>
  );
}
