import React from 'react';
import styles from './Boundaries.module.css';

export function ServiceUnavailableBoundary() {
  return (
    <div className={styles.boundaryContainer}>
      <span className={styles.boundaryText}>Service is currently unavailable. Please try again later.</span>
    </div>
  );
}
