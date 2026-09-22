'use client';
import React from 'react';
import { ShieldCheck, Heart, Users, User } from '@phosphor-icons/react';
import { TodayHeaderProps } from '../types';
import styles from './AmbientTodayHeader.module.css';

export function AmbientTodayHeader({
  timeIndicator,
  greetingText,
  homeStatusText,
  privacyTag,
  privacyIcon,
}: TodayHeaderProps) {
  const renderIcon = () => {
    switch (privacyIcon) {
      case 'heart':
        return <Heart size={14} weight="fill" color="#f6ab63" />;
      case 'users':
        return <Users size={14} weight="fill" color="#5eb2f8" />;
      case 'shield':
        return <ShieldCheck size={14} weight="fill" color="#a4d4ff" />;
      default:
        return <User size={14} weight="fill" color="#a4d4ff" />;
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
