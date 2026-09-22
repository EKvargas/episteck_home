// src/components/slots/hardware/HardwareRelationshipSwitcher.tsx
'use client';
import React from 'react';
import { RelationshipSwitcherProps } from '../types';
import styles from './HardwareRelationshipSwitcher.module.css';

export function HardwareRelationshipSwitcher({
  activeContextId,
  onSelectContext,
}: RelationshipSwitcherProps) {
  const isFamily = activeContextId === 'CIR-fam';
  const isErick = activeContextId === 'PSN-me';
  const isAna = activeContextId === 'PSN-ana';

  // Rotation angles for physical knob:
  // Family: -35deg, Erick: 0deg, Ana: 35deg
  const rotationDeg = isFamily ? -35 : isErick ? 0 : 35;

  return (
    <nav
      aria-label="Hardware Rotary Context Controller"
      className={styles.container}
    >
      <span className={styles.rotaryLabel} aria-hidden="true">
        Context Rotary
      </span>

      <div className={styles.controlsArea}>
        {/* Family Target */}
        <button
          type="button"
          role="tab"
          aria-selected={isFamily}
          aria-label="Family Context"
          onClick={() => onSelectContext('CIR-fam')}
          className={`${styles.contextButton} ${
            isFamily ? styles.contextButtonActive : ''
          }`}
        >
          FAMILY
        </button>

        {/* Machined Center Knob */}
        <div
          className={styles.knobWrapper}
          style={{ transform: `rotate(${rotationDeg}deg)` }}
          aria-hidden="true"
        >
          <div className={styles.knobPip} />
        </div>

        {/* Erick Target */}
        <button
          type="button"
          role="tab"
          aria-selected={isErick}
          aria-label="Erick Personal Context"
          onClick={() => onSelectContext('PSN-me')}
          className={`${styles.contextButton} ${
            isErick ? styles.contextButtonActive : ''
          }`}
        >
          ERICK
        </button>

        {/* Ana Target */}
        <button
          type="button"
          role="tab"
          aria-selected={isAna}
          aria-label="Ana Care Context"
          onClick={() => onSelectContext('PSN-ana')}
          className={`${styles.contextButton} ${
            isAna ? styles.contextButtonActive : ''
          }`}
        >
          ANA
        </button>
      </div>
    </nav>
  );
}
