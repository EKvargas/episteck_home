// src/components/slots/organic/OrganicTodaySchedule.tsx
'use client';
import React from 'react';
import { Calendar } from '@phosphor-icons/react';
import { TodayScheduleProps } from '../types';
import styles from './OrganicTodaySchedule.module.css';

export function OrganicTodaySchedule({
  title,
  subtitle,
  countTag,
  events,
}: TodayScheduleProps) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.titleArea}>
          <div className={styles.iconWrapper}>
            <Calendar size={18} weight="duotone" />
          </div>
          <div>
            <h2 className={styles.titleText}>{title}</h2>
            <p className={styles.subtitleText}>{subtitle}</p>
          </div>
        </div>
        <span className={styles.countTag}>{countTag}</span>
      </div>

      <div className={styles.timelineList}>
        {events.map((event) => {
          let statusClass = styles.statusUpcoming;
          if (event.status === 'Completed') {
            statusClass = styles.statusCompleted;
          } else if (event.status === 'Now Active' || event.status === 'In Progress') {
            statusClass = styles.statusActive;
          }

          return (
            <div key={event.id} className={styles.eventRow}>
              <div className={styles.eventLeft}>
                <span className={styles.timeTag}>{event.time}</span>
                <div>
                  <h3 className={styles.eventTitle}>
                    {event.title}
                    {event.isCareLink && (
                      <span className={styles.careTag}>Care Link</span>
                    )}
                  </h3>
                  <p className={styles.eventSubtitle}>{event.subtitle}</p>
                </div>
              </div>
              <span className={`${styles.statusTag} ${statusClass}`}>
                {event.status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
