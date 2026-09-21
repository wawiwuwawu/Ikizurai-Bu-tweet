// Lapisan data frontend — dua mode:
//  1) "api"    (default)  → REST /api/* dari backend FastAPI
//  2) "static" (VITE_DATA_MODE=static) → baca dataset JSON (folder dataset/) —
//     dipakai untuk build GitHub Pages, tanpa server sama sekali.
//
// Kontrak fungsi identik di kedua mode, jadi komponen tidak perlu tahu bedanya.

const BASE = import.meta.env.VITE_API_BASE ?? ''
const STATIC = import.meta.env.VITE_DATA_MODE === 'static'
const DATA_BASE = (import.meta.env.VITE_DATA_BASE
  ?? `${import.meta.env.BASE_URL ?? '/'}dataset/`).replace(/\/+$/, '')

async function get(path, { signal } = {}) {
  const res = await fetch(`${BASE}${path}`, { signal })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------- mode static

const staticPath = (p) => `${DATA_BASE}/${p}`
const monthCache = new Map() // file → rekaman (urut naik: created_at, id_str)
let indexPromise = null

async function loadMonth(file, signal) {
  if (monthCache.has(file)) return monthCache.get(file)
  const res = await fetch(staticPath(file), { signal })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const text = await res.text()
  const recs = []
  for (const line of text.split('\n')) {
    if (line.trim()) recs.push(JSON.parse(line))
  }
  monthCache.set(file, recs)
  return recs
}

async function staticIndex(signal) {
  indexPromise ??= get(staticPath('index.json'), { signal })
  return indexPromise
}

/** Versi static dari /api/tweets — filter + kursor di sisi klien.
 *  Memuat file bulan secara malas (dari terbaru ke terlama) dan berhenti
 *  begitu halaman terisi. Semantik kursor sama dengan backend:
 *  `before` = id_str eksklusif, next_before = id baris terakhir halaman.
 */
async function staticTweets({ member, q, since, until, before, limit = 30, signal }) {
  const idx = await staticIndex(signal)
  const months = [...idx.months].reverse() // terbaru → terlama
  const ql = q ? q.toLowerCase() : null
  const untilBound = until ? (until.length === 10 ? `${until}T23:59:59Z` : until) : null

  const items = []
  let skipping = Boolean(before)

  for (const m of months) {
    if (items.length > limit) break
    const recs = await loadMonth(m.file, signal)
    for (let i = recs.length - 1; i >= 0; i--) {
      const r = recs[i]
      if (skipping) {
        if (r.id_str === before) skipping = false
        continue
      }
      if (member && r.member !== member) continue
      if (ql) {
        const jp = (r.text ?? '').toLowerCase()
        const id = (r.text_id ?? '').toLowerCase()
        if (!jp.includes(ql) && !id.includes(ql)) continue
      }
      if (since && r.created_at < since) continue
      if (untilBound && r.created_at > untilBound) continue
      items.push(r)
      if (items.length > limit) break
    }
  }

  let next_before = null
  if (items.length > limit) {
    next_before = items[limit - 1].id_str
    items.length = limit
  }
  return { items, next_before }
}

// ---------------------------------------------------------------- publik

export async function fetchTweets({ member, q, since, until, before, limit = 30, signal } = {}) {
  if (STATIC) return staticTweets({ member, q, since, until, before, limit, signal })
  const p = new URLSearchParams()
  if (member) p.set('member', member)
  if (q) p.set('q', q)
  if (since) p.set('since', since)
  if (until) p.set('until', until)
  if (before) p.set('before', before)
  p.set('limit', String(limit))
  return get(`/api/tweets?${p.toString()}`, { signal })
}

export function fetchMembers(signal) {
  if (STATIC) return get(staticPath('members.json'), { signal })
  return get('/api/members', { signal })
}

export function fetchStats(signal) {
  if (STATIC) return get(staticPath('stats.json'), { signal })
  return get('/api/stats', { signal })
}

export const isStatic = STATIC
