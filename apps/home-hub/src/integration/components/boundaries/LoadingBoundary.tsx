import React from 'react';
import styles from './Boundaries.module.css';

export function LoadingBoundary() {
  return (
    <div className={styles.boundaryContainer}>
      <div className={styles.loadingSpinner} />
      <span className={styles.boundaryText}>Loading...</span>
    </div>
  );
}
