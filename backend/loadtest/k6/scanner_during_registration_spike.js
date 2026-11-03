// Scanner traffic while a registration spike is running. Scanner latency must stay low.
import http from 'k6/http';
import { check } from 'k6';
import { API, login, register, randomSessions, registrationPayload, uuid } from './lib.js';

http.setResponseCallback(http.expectedStatuses(200, 201, 409, 503));
const session = Number(__ENV.SESSION || 1);
const peak = Number(__ENV.PEAK || 150);

export const options = {
  setupTimeout: '120s',
  scenarios: {
    registrations: {
      executor: 'ramping-arrival-rate',
      exec: 'registrations',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: 1000,
      stages: [
        { target: peak, duration: '20s' },
        { target: peak, duration: '30s' },
      ],
    },
    scanners: {
      executor: 'constant-arrival-rate',
      exec: 'scanners',
      rate: Number(__ENV.SCAN_RATE || 50),
      timeUnit: '1s',
      duration: '50s',
      preAllocatedVUs: 30,
      maxVUs: 200,
    },
  },
  thresholds: {
    'http_req_duration{name:POST /scanner/scan}': ['p(95)<500', 'p(99)<1000'],
  },
};

export function setup() {
  const qrs = [];
  for (let i = 0; i < 30; i++) {
    const r = http.post(`${API}/registrations`, JSON.stringify(registrationPayload(4, [session])), {
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': uuid() },
    });
    if (r.status === 201) qrs.push(r.json('data.qr_pass.qr_payload'));
  }
  const tokens = (__ENV.SCANNER_EMAILS || '')
    .split(',')
    .filter(Boolean)
    .map((e) => login(e.trim(), __ENV.SCANNER_PASSWORD));
  if (!tokens.length) throw new Error('SCANNER_EMAILS is required');
  return { qrs, tokens };
}

export function registrations() {
  register(1 + Math.floor(Math.random() * 8), randomSessions(1, 3));
}

export function scanners(data) {
  const res = http.post(
    `${API}/scanner/scan`,
    JSON.stringify({ qr_payload: data.qrs[Math.floor(Math.random() * data.qrs.length)] }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${data.tokens[Math.floor(Math.random() * data.tokens.length)]}`,
      },
      tags: { name: 'POST /scanner/scan' },
    },
  );
  check(res, { 'scan VALID': (r) => r.status === 200 && r.json('data.status') === 'VALID' });
}
