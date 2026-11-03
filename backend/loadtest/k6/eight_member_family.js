// Eight-member families only (each one occupies a whole Kund in every booked session).
import http from 'k6/http';
import { register, randomSessions, commonThresholds } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409));

export const options = {
  scenarios: {
    eight: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 30),
      timeUnit: '1s',
      duration: __ENV.DURATION || '45s',
      preAllocatedVUs: 30,
      maxVUs: 300,
    },
  },
  thresholds: commonThresholds,
};

export default function () {
  register(8, randomSessions(1, 2));
}
