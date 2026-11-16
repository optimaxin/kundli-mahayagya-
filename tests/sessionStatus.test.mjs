// Run with: npm test   (Node's built-in test runner, no extra dependencies)
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { LOCKED_REASON, isSessionLocked, pick, sessionStatusView } from '../src/lib/sessionStatus.js'

// What GET /api/v1/sessions returns for the locked session (14 Dec 2026 MORNING), as db.js stores it.
const locked = { status: 'CLOSED', closedReason: LOCKED_REASON, open: false, fits: false }

test('locked session: Hindi shows सत्र पूर्ण with a lock and cannot be selected', () => {
  const v = sessionStatusView(locked)
  assert.equal(v.locked, true)
  assert.equal(v.selectable, false)
  assert.equal(pick(v.label, 'hi'), 'सत्र पूर्ण')
})

test('locked session: English shows "Session Full"', () => {
  assert.equal(pick(sessionStatusView(locked).label, 'en'), 'Session Full')
})

test('locked session is never selectable, whatever the other flags say', () => {
  assert.equal(sessionStatusView({ ...locked, fits: true, open: true }).selectable, false)
  assert.equal(isSessionLocked(locked), true)
})

test('an ordinary session is selectable and has no lock', () => {
  const v = sessionStatusView({ status: 'AVAILABLE', closedReason: null })
  assert.equal(v.locked, false)
  assert.equal(v.selectable, true)
  assert.equal(pick(v.label, 'en'), 'Booking available')
})

test('a session closed by the booking cut-off keeps the generic "Booking closed" text, no lock', () => {
  const v = sessionStatusView({ status: 'CLOSED', closedReason: 'CUTOFF' })
  assert.equal(v.locked, false)
  assert.equal(v.selectable, false)
  assert.equal(pick(v.label, 'en'), 'Booking closed')
  assert.equal(pick(v.label, 'hi'), 'बुकिंग बंद')
})

test('other states are unchanged and not selectable', () => {
  for (const status of ['NOT_FOR_THIS_FAMILY', 'FULL', 'CLOSED', 'error', 'loading']) {
    assert.equal(sessionStatusView({ status }).selectable, false, status)
  }
  assert.equal(pick(sessionStatusView({ status: 'FULL' }).label, 'hi'), 'सत्र पूर्ण')
  assert.equal(sessionStatusView({ status: 'no-such-state' }).key, 'loading')
})

test('the status label carries no seat counts', () => {
  const v = sessionStatusView(locked)
  assert.equal(/\d/.test(v.label.join(' ')), false)
})

test('the picker is wired to the shared mapping: lock icon + disabled button + closed_reason from the API', () => {
  const src = readFileSync(new URL('../src/pages/Register.jsx', import.meta.url), 'utf8')
  assert.match(src, /sessionStatusView/)
  assert.match(src, /<Lock /)
  assert.match(src, /disabled=\{!can\}/)
  const db = readFileSync(new URL('../src/lib/db.js', import.meta.url), 'utf8')
  assert.match(db, /closedReason: s\.closed_reason/)
  assert.match(db, /SESSION_NOT_BOOKABLE/)
})
