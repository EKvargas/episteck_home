// src/components/slots/hardware/HardwareTodayHeader.tsx
'use client';
import React from 'react';
import { ShieldCheck, Heart, Users, User } from '@phosphor-icons/react';
import { TodayHeaderProps } from '../types';
import styles from './HardwareTodayHeader.module.css';

export function HardwareTodayHeader({
  timeIndicator,
  greetingText,
  homeStatusText,
  privacyTag,
  privacyIcon,
}: TodayHeaderProps) {
  const renderIcon = () => {
    switch (privacyIcon) {
      case 'heart':
        return <Heart size={14} weight="fill" color="#f58e2a" />;
      case 'users':
        return <Users size={14} weight="fill" color="#10d290" />;
      case 'shield':
        return <ShieldCheck size={14} weight="fill" color="#ffb773" />;
      default:
        return <User size={14} weight="fill" color="#ffb773" />;
    }
  };

  return (
    <header className={styles.headerNav}>
      <div className={styles.greetingBlock}>
        <span className={styles.timeIndicator}>{timeIndicator}</span>
        <h1 className={styles.greetingText}>{greetingText}</h1>
      </div>

      <div className={styles.rightArea}>
        <div className={styles.homePill}>
          <span className={styles.pulseDot} aria-hidden="true" />
          <span>{homeStatusText}</span>
        </div>

        <div className={styles.privacyBadge}>
          {renderIcon()}
          <span>{privacyTag}</span>
        </div>
      </div>
    </header>
  );
}
