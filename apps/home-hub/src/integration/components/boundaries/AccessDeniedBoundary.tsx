import React from 'react';
import styles from './Boundaries.module.css';

export function AccessDeniedBoundary() {
  return (
    <div className={styles.boundaryContainer}>
      <span className={styles.boundaryText}>Access Denied. You do not have permission to view this resource.</span>
    </div>
  );
}
