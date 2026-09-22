import React from 'react';
import styles from './Boundaries.module.css';

interface Props {
  environment: 'MOCK' | 'LIVE';
}

export function MockProvenanceIndicator({ environment }: Props) {
  if (environment === 'LIVE') {
    return null;
  }
  
  return (
    <div className={styles.mockIndicator} title="Data is mocked for development">
      MOCK DATA
    </div>
  );
}
