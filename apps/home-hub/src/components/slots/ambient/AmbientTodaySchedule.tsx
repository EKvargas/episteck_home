'use client';
import React from 'react';
import { CalendarBlank } from '@phosphor-icons/react';
import { TodayScheduleProps } from '../types';
import styles from './AmbientTodaySchedule.module.css';

export function AmbientTodaySchedule({
  title,
  subtitle,
  countTag,
  events,
}: TodayScheduleProps) {
  const getStatusClass = (color?: string) => {
    switch (color) {
      case 'emerald':
        return styles.statusEmerald;
      case 'amber':
        return styles.statusAmber;
      case 'sky':
        return styles.statusSky;
      default:
        return styles.statusSlate;
    }
  };

  return (
    <div className={styles.card}>
      <div className={styles.headerRow}>
        <div className={styles.titleArea}>
          <div className={styles.iconBadge} aria-hidden="true">
            <CalendarBlank size={18} weight="bold" />
          </div>
          <div>
            <h2 className={styles.titleText}>{title}</h2>
            <p className={styles.subtitleText}>{subtitle}</p>
          </div>
        </div>
        <span className={styles.countTag}>{countTag}</span>
      </div>

      <div className={styles.timelineList}>
        {events.length > 0 ? (
          events.map((event) => (
            <div key={event.id} className={styles.timelineItem}>
              <div className={styles.eventLeft}>
                <div className={styles.timeTag}>{event.time}</div>
                <div className={styles.eventContent}>
                  <div className={styles.eventTitleRow}>
                    <h3 className={styles.eventTitle}>{event.title}</h3>
                    {event.isCareLink && (
                      <span className={styles.careBadge}>Care Link</span>
                    )}
                  </div>
                  {event.subtitle && (
                    <p className={styles.eventSubtitle}>{event.subtitle}</p>
                  )}
                </div>
              </div>
              {event.status && (
                <span className={`${styles.statusTag} ${getStatusClass(event.statusColor)}`}>
                  {event.status}
                </span>
              )}
            </div>
          ))
        ) : (
          <p className={styles.subtitleText} style={{ textAlign: 'center', padding: '1rem' }}>
            No scheduled events for this context.
          </p>
        )}
      </div>
    </div>
  );
}
