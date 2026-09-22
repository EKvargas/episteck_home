// src/components/slots/organic/OrganicAttentionTasks.tsx
'use client';
import React from 'react';
import { Bell } from '@phosphor-icons/react';
import { AttentionTasksProps } from '../types';
import styles from './OrganicAttentionTasks.module.css';

export function OrganicAttentionTasks({
  title,
  pendingCountTag,
  tasks,
  onToggleTask,
}: AttentionTasksProps) {
  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.titleArea}>
          <Bell size={18} weight="fill" className={styles.bellIcon} />
          <h2 className={styles.titleText}>{title}</h2>
        </div>
        <span className={styles.pendingTag}>{pendingCountTag}</span>
      </div>

      <div className={styles.taskList}>
        {tasks.map((task) => (
          <label
            key={task.id}
            className={`${styles.taskItem} ${
              task.isDoorAlert ? styles.taskItemDoorAlert : ''
            }`}
          >
            <input
              type="checkbox"
              checked={task.done}
              onChange={() => onToggleTask(task.id)}
              className={styles.taskCheckbox}
              aria-label={task.title}
            />
            <span
              className={`${styles.taskText} ${
                task.done ? styles.taskTextDone : ''
              }`}
            >
              {task.title}
            </span>
            <span
              className={`${styles.taskTag} ${
                task.isDoorAlert ? styles.taskTagDoor : ''
              }`}
            >
              {task.tag}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
