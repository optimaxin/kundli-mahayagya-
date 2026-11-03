// Multi-session bookings: each family books 4-16 sessions atomically (widest lock scope).
import http from 'k6/http';
import { register, randomSessions, commonThresholds } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409));

export const options = {
  scenarios: {
    multi: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20),
      timeUnit: '1s',
      duration: __ENV.DURATION || '45s',
      preAllocatedVUs: 30,
      maxVUs: 300,
    },
  },
  thresholds: commonThresholds,
};

export default function () {
  register(1 + Math.floor(Math.random() * 8), randomSessions(4, 8));
}
