// Registration spike: ramp from a trickle to PEAK requests/second and back.
// Admission control should shed excess load with fast 503 + Retry-After instead of timing out.
// k6 run -e PEAK=200 registration_spike.js
import http from 'k6/http';
import { register, randomSessions } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409, 503));
const peak = Number(__ENV.PEAK || 200);

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: Number(__ENV.MAX_VUS || 1500),
      stages: [
        { target: 10, duration: '10s' },
        { target: peak, duration: '20s' },
        { target: peak, duration: __ENV.HOLD || '30s' },
        { target: 10, duration: '10s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
  },
};

export default function () {
  register(1 + Math.floor(Math.random() * 8), randomSessions(1, 3));
}
