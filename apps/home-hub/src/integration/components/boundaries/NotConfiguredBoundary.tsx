import React from 'react';
import styles from './Boundaries.module.css';

export function NotConfiguredBoundary() {
  return (
    <div className={styles.boundaryContainer}>
      <span className={styles.boundaryText}>This resource has not been configured yet.</span>
    </div>
  );
}
