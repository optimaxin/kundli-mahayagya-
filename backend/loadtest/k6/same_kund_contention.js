// Same-Kund contention: every request is a 2-member family for ONE session, so all of them
// compete for the same best-fit Kund. Afterwards run `python -m scripts.verify_integrity`
// to confirm no overbooking and reserved_count == confirmed allocations.
import http from 'k6/http';
import { register } from './lib.js';

http.setResponseCallback(http.expectedStatuses(201, 409));
const session = Number(__ENV.SESSION || 16);

export const options = {
  scenarios: {
    contention: { executor: 'constant-vus', vus: Number(__ENV.VUS || 50), duration: __ENV.DURATION || '45s' },
  },
  thresholds: { http_req_failed: ['rate<0.01'] },
};

export default function () {
  register(2, [session]);
}
