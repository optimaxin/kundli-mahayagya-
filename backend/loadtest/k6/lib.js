// Shared helpers for the k6 load-test scenarios.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const reg201 = new Counter('reg_201_created');
const reg409 = new Counter('reg_409_capacity_or_duplicate');
const reg503 = new Counter('reg_503_retryable'); // admission-control shedding or DB outage
const reg5xx = new Counter('reg_5xx_other');

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
export const API = `${BASE_URL}/api/v1`;

const NAMES = ['Rahul', 'Priya', 'Aarav', 'Ananya', 'Vivaan', 'Diya', 'Arjun', 'Saanvi', 'Kabir', 'Isha'];

export function uuid() {
  // RFC4122-ish v4 (sufficient for idempotency keys in load tests)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function randomMobile() {
  return String(6 + Math.floor(Math.random() * 4)) + String(Math.floor(Math.random() * 1e9)).padStart(9, '0');
}

export function registrationPayload(members, sessions) {
  const list = [];
  for (let i = 0; i < members; i++) {
    list.push({
      full_name: `${NAMES[i % NAMES.length]} Loadtest`,
      age: 10 + ((i * 9) % 70),
      gender: i % 2 ? 'female' : 'male',
      relationship: i === 0 ? 'Self' : 'Relative',
    });
  }
  return {
    coordinator: {
      name: 'Load Test',
      primary_mobile: randomMobile(),
      secondary_mobile: '',
      email: 'load@example.org',
      address: '1 Test Street',
      city: 'Agra',
      state: 'Uttar Pradesh',
      pincode: '282001',
      gotra: 'Kashyap',
      sankalp_purpose: 'Load testing',
    },
    members: list,
    selected_sessions: sessions,
  };
}

export function register(members, sessions, key) {
  const res = http.post(`${API}/registrations`, JSON.stringify(registrationPayload(members, sessions)), {
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key || uuid() },
    tags: { name: 'POST /registrations' },
  });
  if (res.status === 201) reg201.add(1);
  else if (res.status === 409) reg409.add(1);
  else if (res.status === 503) reg503.add(1);
  else if (res.status >= 500 || res.status === 0) reg5xx.add(1);
  check(res, {
    'registration 201 or expected 409': (r) => r.status === 201 || r.status === 409,
    'no unexpected 5xx': (r) => r.status < 500 || r.status === 503,
  });
  return res;
}

// One session per day (the backend rejects both slots of the same date): pick n different days (1-8),
// then a random slot (morning = odd id, afternoon = even id) for each.
export function randomSessions(min, max) {
  const n = Math.min(8, min + Math.floor(Math.random() * (max - min + 1)));
  const days = Array.from({ length: 8 }, (_, i) => i);
  for (let i = days.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [days[i], days[j]] = [days[j], days[i]];
  }
  return days.slice(0, n).map((d) => 2 * d + 1 + Math.floor(Math.random() * 2)).sort((a, b) => a - b);
}

export function login(email, password) {
  const res = http.post(`${API}/auth/login`, JSON.stringify({ email, password }), {
    headers: { 'Content-Type': 'application/json' },
  });
  if (res.status !== 200) throw new Error(`login failed for ${email}: ${res.status}`);
  return res.json('data.access_token');
}

export const commonThresholds = {
  http_req_failed: ['rate<0.01'],
  'http_req_duration{name:POST /registrations}': ['p(95)<2000', 'p(99)<4000'],
};
