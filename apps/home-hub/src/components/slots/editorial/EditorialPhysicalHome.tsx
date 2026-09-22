// src/components/slots/editorial/EditorialPhysicalHome.tsx
'use client';
import React from 'react';
import { House, Thermometer, Wind, Lock, LockKeyOpen, Sun } from '@phosphor-icons/react';
import { PhysicalHomeProps } from '../types';
import styles from './EditorialPhysicalHome.module.css';

export function EditorialPhysicalHome({
  telemetry,
  doorLocked,
  onToggleDoorLock,
  ambianceScene,
  onCycleAmbianceScene,
}: PhysicalHomeProps) {
  return (
    <div className={styles.card}>
      <div className={styles.headerRow}>
        <div className={styles.titleArea}>
          <div className={styles.iconBadge} aria-hidden="true">
            <House size={16} weight="bold" />
          </div>
          <div>
            <h2 className={styles.titleText}>Physical Home</h2>
            <p className={styles.subtitleText}>Gateway: 4 online nodes · Atmosphere stable</p>
          </div>
        </div>
        <span className={styles.statusPill}>EVERYTHING NORMAL</span>
      </div>

      <div className={styles.tilesGrid}>
        {/* Living Room */}
        <div className={styles.tile}>
          <div className={styles.tileTop}>
            <span>Living</span>
            <Thermometer size={14} weight="bold" aria-hidden="true" />
          </div>
          <span className={styles.tileValue}>{telemetry.livingRoom.temp}</span>
          <span className={`${styles.tileSub} ${styles.tileSubEmerald}`}>
            {telemetry.livingRoom.humidity}
          </span>
        </div>

        {/* Climate HVAC */}
        <div className={styles.tile}>
          <div className={styles.tileTop}>
            <span>Climate</span>
            <Wind size={14} weight="bold" aria-hidden="true" />
          </div>
          <span className={styles.tileValue}>{telemetry.climate.mode}</span>
          <span className={styles.tileSub}>{telemetry.climate.targetTemp}</span>
        </div>

        {/* Perimeter Door Lock */}
        <div className={styles.tile}>
          <div className={styles.tileTop}>
            <span>Front Door</span>
            {doorLocked ? (
              <Lock size={14} weight="bold" color="#1d7335" aria-hidden="true" />
            ) : (
              <LockKeyOpen size={14} weight="bold" color="#781c22" aria-hidden="true" />
            )}
          </div>
          <span
            className={`${styles.tileValue} ${
              doorLocked ? styles.tileValueEmerald : styles.tileValueAmber
            }`}
          >
            {doorLocked ? 'LOCKED' : 'UNLOCKED'}
          </span>
          <button
            type="button"
            onClick={onToggleDoorLock}
            className={styles.tileSubLink}
          >
            {doorLocked ? 'Tap to Unlock' : 'Tap to Lock'}
          </button>
        </div>

        {/* Ambiance Lighting Mode */}
        <div
          onClick={onCycleAmbianceScene}
          className={`${styles.tile} ${styles.tileClickable}`}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onCycleAmbianceScene();
            }
          }}
          aria-label="Cycle ambiance scene"
        >
          <div className={styles.tileTop}>
            <span>Ambiance</span>
            <Sun size={14} weight="fill" color="#781c22" aria-hidden="true" />
          </div>
          <span className={styles.tileValue}>{ambianceScene}</span>
          <span className={`${styles.tileSub} ${styles.tileSubAccent}`}>CYCLE SCENE</span>
        </div>
      </div>
    </div>
  );
}
