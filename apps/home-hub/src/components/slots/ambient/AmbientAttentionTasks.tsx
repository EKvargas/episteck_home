'use client';
import React from 'react';
import { Bell } from '@phosphor-icons/react';
import { AttentionTasksProps } from '../types';
import styles from './AmbientAttentionTasks.module.css';

export function AmbientAttentionTasks({
  title,
  pendingCountTag,
  tasks,
  onToggleTask,
}: AttentionTasksProps) {
  return (
    <div className={styles.card}>
      <div className={styles.headerRow}>
        <div className={styles.titleArea}>
          <Bell size={18} weight="fill" className={styles.bellIcon} aria-hidden="true" />
          <h2 className={styles.titleText}>{title}</h2>
        </div>
        <span className={styles.pendingBadge}>{pendingCountTag}</span>
      </div>

      <div className={styles.taskList} role="list" aria-label="Actionable tasks">
        {tasks.map((task) => {
          const isAlert = task.isDoorAlert;
          return (
            <label
              key={task.id}
              className={`${styles.taskItem} ${isAlert && !task.done ? styles.taskItemAlert : ''}`}
            >
              <input
                type="checkbox"
                checked={task.done}
                onChange={() => onToggleTask(task.id)}
                className={styles.checkboxInput}
                aria-label={`Mark "${task.title}" as ${task.done ? 'not done' : 'done'}`}
              />
              <span
                className={`${styles.taskText} ${task.done ? styles.taskTextDone : ''}`}
              >
                {task.title}
              </span>
              <span
                className={`${styles.taskTag} ${isAlert && !task.done ? styles.taskTagAlert : ''}`}
              >
                {task.tag}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
