// Database restart / network interruption drill.
// Start this, then during the run execute ONE of:
//   docker compose restart db                                   (database restart)
//   docker network disconnect mahayagya_default mahayagya-db-1  (network interruption)
//   ... wait ~10 s ...
//   docker network connect mahayagya_default mahayagya-db-1
// Expected: requests during the outage fail FAST (5xx/503, no hangs, no partial bookings);
// traffic recovers automatically (pool_pre_ping) once the DB is back; verify_integrity passes.
import http from 'k6/http';
import { register, randomSessions } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409));

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20),
      timeUnit: '1s',
      duration: __ENV.DURATION || '90s',
      preAllocatedVUs: 50,
      maxVUs: 300,
    },
  },
  thresholds: { http_req_duration: ['max<20000'] },
};

export default function () {
  register(1 + Math.floor(Math.random() * 8), randomSessions(1, 2));
}
