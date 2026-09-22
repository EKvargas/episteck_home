import React from 'react';
import styles from './Boundaries.module.css';

export function OfflineBoundary() {
  return (
    <div className={styles.boundaryContainer}>
      <span className={styles.boundaryText}>You are currently offline. Displaying stale data if available.</span>
    </div>
  );
}
