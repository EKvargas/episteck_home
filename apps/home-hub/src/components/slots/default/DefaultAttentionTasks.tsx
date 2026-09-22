'use client';
import React from 'react';
import { AttentionTasksProps } from '../types';
import styles from './DefaultSlots.module.css';

export function DefaultAttentionTasks({
  title,
  tasks,
  onToggleTask,
}: AttentionTasksProps) {
  return (
    <div className={styles.defaultCard}>
      <div className={styles.defaultHeader}>
        <h2 className={styles.defaultTitle}>{title}</h2>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {tasks.map((task) => (
          <label
            key={task.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={task.done}
              onChange={() => onToggleTask(task.id)}
            />
            <span style={{ textDecoration: task.done ? 'line-through' : 'none', opacity: task.done ? 0.6 : 1 }}>
              {task.title}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
