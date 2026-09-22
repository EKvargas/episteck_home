// src/components/slots/organic/OrganicTodayHeader.tsx
'use client';
import React from 'react';
import { ShieldCheck, Heart, Users, User } from '@phosphor-icons/react';
import { TodayHeaderProps } from '../types';
import styles from './OrganicTodayHeader.module.css';

export function OrganicTodayHeader({
  timeIndicator,
  greetingText,
  homeStatusText,
  privacyTag,
  privacyIcon,
}: TodayHeaderProps) {
  const renderIcon = () => {
    switch (privacyIcon) {
      case 'heart':
        return <Heart size={14} weight="fill" color="#8f77a5" />;
      case 'users':
        return <Users size={14} weight="fill" color="#49714c" />;
      case 'shield':
        return <ShieldCheck size={14} weight="fill" color="#2c5330" />;
      default:
        return <User size={14} weight="fill" color="#2c5330" />;
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
