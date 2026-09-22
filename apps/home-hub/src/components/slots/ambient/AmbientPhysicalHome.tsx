'use client';
import React from 'react';
import { House, Thermometer, Wind, Lock, LockKeyOpen, Sun } from '@phosphor-icons/react';
import { PhysicalHomeProps } from '../types';
import styles from './AmbientPhysicalHome.module.css';

export function AmbientPhysicalHome({
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
            <House size={18} weight="bold" />
          </div>
          <div>
            <h2 className={styles.titleText}>Physical Home</h2>
            <p className={styles.subtitleText}>Gateway: 4 online nodes · Atmosphere stable</p>
          </div>
        </div>
        <span className={styles.statusPill}>Everything Good</span>
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
              <Lock size={14} weight="bold" color="#10d290" aria-hidden="true" />
            ) : (
              <LockKeyOpen size={14} weight="bold" color="#f6ab63" aria-hidden="true" />
            )}
          </div>
          <span
            className={`${styles.tileValue} ${doorLocked ? styles.tileValueLocked : styles.tileValueUnlocked}`}
          >
            {doorLocked ? 'Locked' : 'Unlocked'}
          </span>
          <button
            type="button"
            onClick={onToggleDoorLock}
            className={`${styles.tileSub} ${styles.tileSubAction}`}
          >
            {doorLocked ? 'Tap to Unlock' : 'Tap to Lock'}
          </button>
        </div>

        {/* Ambiance Scene */}
        <div
          className={`${styles.tile} ${styles.interactiveTile}`}
          onClick={onCycleAmbianceScene}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onCycleAmbianceScene();
            }
          }}
          aria-label={`Current scene is ${ambianceScene}. Press to cycle scene.`}
        >
          <div className={styles.tileTop}>
            <span>Ambiance</span>
            <Sun size={14} weight="bold" color="#f6ab63" aria-hidden="true" />
          </div>
          <span className={styles.tileValue}>{ambianceScene}</span>
          <span className={`${styles.tileSub} ${styles.tileSubAccent}`}>
            Cycle scene
          </span>
        </div>
      </div>
    </div>
  );
}
