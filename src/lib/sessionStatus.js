// Public status of one session in the booking picker. Pure (no React, no network) so it can be unit-tested
// with `npm test`. The server decides everything: this module only maps its answer to a label and an icon.
//
//   status      = the server's `availability`: AVAILABLE | NOT_FOR_THIS_FAMILY | FULL | CLOSED
//   closedReason = the server's `closed_reason`. 'SESSION_FULL' means the organisers closed this session
//                  to new bookings (the session is permanently full). The picker shows it with a lock.
//
// Labels are [English, Hindi]. They deliberately carry no seat counts.
export const STATUS = {
  AVAILABLE: [['Booking available', 'बुकिंग उपलब्ध'], 'text-emerald-700'],
  NOT_FOR_THIS_FAMILY: [['Fully booked', 'बुकिंग पूर्ण'], 'text-saffron-600'],
  FULL: [['Session full', 'सत्र पूर्ण'], 'text-red-600'],
  CLOSED: [['Booking closed', 'बुकिंग बंद'], 'text-stone-500'],
  SESSION_LOCKED: [['Session Full', 'सत्र पूर्ण'], 'text-red-600'],
  error: [['Could not load', 'लोड नहीं हो सका'], 'text-red-600'],
  loading: [['Checking…', 'जाँच हो रही है…'], 'text-stone-400'],
}

export const LOCKED_REASON = 'SESSION_FULL'

export const isSessionLocked = (a) => a?.status === 'CLOSED' && a?.closedReason === LOCKED_REASON

// -> { key, label: [en, hi], tone, locked, selectable }
export function sessionStatusView(a) {
  const key = isSessionLocked(a) ? 'SESSION_LOCKED' : (a?.status in STATUS ? a.status : 'loading')
  const [label, tone] = STATUS[key]
  return { key, label, tone, locked: key === 'SESSION_LOCKED', selectable: a?.status === 'AVAILABLE' }
}

// The one string for a language: pick(['Session Full', 'सत्र पूर्ण'], 'hi') -> 'सत्र पूर्ण'
export const pick = (label, lang) => (lang === 'hi' && label[1] ? label[1] : label[0])
