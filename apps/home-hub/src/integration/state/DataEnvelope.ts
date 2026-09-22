import { SafeUIErrorCode } from './SafeUIErrorCode';

export interface DataEnvelope<T> {
  delivery: 'LOADING' | 'READY' | 'ERROR';
  authorization: 'GRANTED' | 'DENIED' | 'INDETERMINATE';
  freshness: 'FRESH' | 'STALE' | 'UNKNOWN';
  environment: 'MOCK' | 'LIVE';
  
  updatedAt?: string;
  sourceSummary?: string;
  errorCode?: SafeUIErrorCode;
  data?: T;
}

export const EnvelopeFactory = {
  loading<T>(environment: 'MOCK' | 'LIVE' = 'MOCK'): DataEnvelope<T> {
    return {
      delivery: 'LOADING',
      authorization: 'INDETERMINATE',
      freshness: 'UNKNOWN',
      environment,
    };
  },
  
  ready<T>(data: T, environment: 'MOCK' | 'LIVE' = 'MOCK', updatedAt?: string): DataEnvelope<T> {
    return {
      delivery: 'READY',
      authorization: 'GRANTED',
      freshness: 'FRESH',
      environment,
      updatedAt,
      data,
    };
  },
  
  error<T>(errorCode: SafeUIErrorCode, environment: 'MOCK' | 'LIVE' = 'MOCK'): DataEnvelope<T> {
    return {
      delivery: 'ERROR',
      authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE',
      freshness: 'UNKNOWN',
      environment,
      errorCode,
    };
  },

  denied<T>(environment: 'MOCK' | 'LIVE' = 'MOCK'): DataEnvelope<T> {
    return EnvelopeFactory.error('ACCESS_DENIED', environment);
  }
};
