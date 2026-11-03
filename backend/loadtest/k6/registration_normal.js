// Normal registration traffic: constant arrival rate, families of 1-8, 1-3 sessions.
// k6 run -e BASE_URL=http://localhost:8000 -e RATE=50 -e DURATION=60s registration_normal.js
import http from 'k6/http';
import { register, randomSessions, commonThresholds } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409));

export const options = {
  scenarios: {
    registrations: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 50),
      timeUnit: '1s',
      duration: __ENV.DURATION || '60s',
      preAllocatedVUs: 50,
      maxVUs: Number(__ENV.MAX_VUS || 400),
    },
  },
  thresholds: commonThresholds,
};

export default function () {
  register(1 + Math.floor(Math.random() * 8), randomSessions(1, 3));
}
