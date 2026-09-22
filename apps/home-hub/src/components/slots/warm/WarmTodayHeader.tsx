// src/components/slots/warm/WarmTodayHeader.tsx
'use client';
import React from 'react';
import { ShieldCheck, Heart, Users, User } from '@phosphor-icons/react';
import { TodayHeaderProps } from '../types';
import styles from './WarmTodayHeader.module.css';

export function WarmTodayHeader({
  timeIndicator,
  greetingText,
  homeStatusText,
  privacyTag,
  privacyIcon,
}: TodayHeaderProps) {
  const renderIcon = () => {
    switch (privacyIcon) {
      case 'heart':
        return <Heart size={14} weight="fill" color="#c4643c" />;
      case 'users':
        return <Users size={14} weight="fill" color="#57704e" />;
      case 'shield':
        return <ShieldCheck size={14} weight="fill" color="#923f1e" />;
      default:
        return <User size={14} weight="fill" color="#923f1e" />;
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
