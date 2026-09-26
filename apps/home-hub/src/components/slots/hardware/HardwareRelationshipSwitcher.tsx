'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './HardwareRelationshipSwitcher.module.css';

export function HardwareRelationshipSwitcher({ contexts, activeContextId, onSelectContext }: RelationshipSwitcherProps) {
  return (
    <nav aria-label="Household Relationship Switcher" className={styles.container}>
      <span className={styles.rotaryLabel}>SCOPE</span>
      <div className={styles.controlsArea}>
        {contexts.map((context) => {
          const active = context.id === activeContextId;
          return (
            <button key={context.id} type="button" role="tab" aria-selected={active}
              aria-label={`${context.name} ${context.mode === 'FAMILY' ? 'Circle' : context.mode === 'PERSONAL' ? 'Personal' : 'Care'} Context`}
              onClick={() => onSelectContext(context.id)}
              className={`${styles.contextButton} ${active ? styles.contextButtonActive : ''}`}>
              {context.name}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
