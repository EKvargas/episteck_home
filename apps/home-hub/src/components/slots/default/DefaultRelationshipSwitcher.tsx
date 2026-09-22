'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './DefaultSlots.module.css';

export function DefaultRelationshipSwitcher({
  contexts,
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  return (
    <nav className={styles.defaultSwitcher} aria-label="Context switcher">
      {contexts.map((ctx) => {
        const isActive = ctx.id === activeContextId;
        return (
          <button
            key={ctx.id}
            type="button"
            className={`${styles.defaultChip} ${isActive ? styles.defaultChipActive : ''}`}
            onClick={() => onSelectContext(ctx.id)}
            aria-selected={isActive}
            data-mode={ctx.mode}
            role="tab"
          >
            {ctx.name}
          </button>
        );
      })}
    </nav>
  );
}
