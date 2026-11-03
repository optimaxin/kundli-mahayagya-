// High-volume scanning incl. duplicate scans of the same members from several scanner accounts.
// The server must run with ENFORCE_CHECKIN_WINDOW=false (or during the session window).
// Requires scanner accounts assigned to SESSION (see loadtest/README.md):
//   -e SCANNER_EMAILS=scan1@example.org,scan2@example.org -e SCANNER_PASSWORD=...
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { API, login, registrationPayload, uuid } from './lib.js';

const success = new Counter('checkin_success');
const already = new Counter('checkin_already');
const session = Number(__ENV.SESSION || 1);
const families = Number(__ENV.FAMILIES || 50);

export const options = {
  setupTimeout: '120s',
  scenarios: {
    scan: { executor: 'constant-vus', vus: Number(__ENV.VUS || 40), duration: __ENV.DURATION || '45s' },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:POST /scanner/checkin}': ['p(95)<500', 'p(99)<1000'],
  },
};

export function setup() {
  const qrs = [];
  for (let i = 0; i < families; i++) {
    const members = 1 + (i % 8);
    const r = http.post(`${API}/registrations`, JSON.stringify(registrationPayload(members, [session])), {
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': uuid() },
    });
    if (r.status === 201) qrs.push({ qr: r.json('data.qr_pass.qr_payload'), members });
  }
  const tokens = (__ENV.SCANNER_EMAILS || '')
    .split(',')
    .filter(Boolean)
    .map((e) => login(e.trim(), __ENV.SCANNER_PASSWORD));
  if (!tokens.length) throw new Error('SCANNER_EMAILS is required');
  return { qrs, tokens };
}

export default function (data) {
  const fam = data.qrs[Math.floor(Math.random() * data.qrs.length)];
  const token = data.tokens[Math.floor(Math.random() * data.tokens.length)];
  const res = http.post(
    `${API}/scanner/checkin`,
    JSON.stringify({ qr_payload: fam.qr, member_number: 1 + Math.floor(Math.random() * fam.members) }),
    {
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      tags: { name: 'POST /scanner/checkin' },
    },
  );
  const status = res.status === 200 ? res.json('data.status') : `HTTP_${res.status}`;
  check(res, { 'checkin ok or duplicate': () => status === 'CHECKIN_SUCCESS' || status === 'ALREADY_CHECKED_IN' });
  if (status === 'CHECKIN_SUCCESS') success.add(1);
  if (status === 'ALREADY_CHECKED_IN') already.add(1);
}
