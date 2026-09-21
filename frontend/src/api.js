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
 *  Memuat file bulan secara malas dan berhenti begitu halaman terisi.
 *  order="desc" (default) → terbaru dulu (bulan & isi dibalik, kursor `before`).
 *  order="asc"            → terlama dulu (bulan & isi maju, kursor `after`).
 */
async function staticTweets({ member, q, since, until, before, after, order = 'desc', limit = 30, signal }) {
  const idx = await staticIndex(signal)
  const asc = order === 'asc'
  const months = asc ? [...idx.months] : [...idx.months].reverse()
  const cursor = asc ? after : before
  const ql = q ? q.toLowerCase() : null
  const untilBound = until ? (until.length === 10 ? `${until}T23:59:59Z` : until) : null

  const items = []
  let skipping = Boolean(cursor)

  for (const m of months) {
    if (items.length > limit) break
    const recs = await loadMonth(m.file, signal)
    const start = asc ? 0 : recs.length - 1
    const end = asc ? recs.length : -1
    const step = asc ? 1 : -1
    for (let i = start; asc ? i < end : i > end; i += step) {
      const r = recs[i]
      if (skipping) {
        if (r.id_str === cursor) skipping = false
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

  let next_cursor = null
  if (items.length > limit) {
    next_cursor = items[limit - 1].id_str
    items.length = limit
  }
  return { items, order, next_cursor }
}

// ---------------------------------------------------------------- publik

export async function fetchTweets({ member, q, since, until, before, after, order = 'desc', limit = 30, signal } = {}) {
  if (STATIC) return staticTweets({ member, q, since, until, before, after, order, limit, signal })
  const p = new URLSearchParams()
  if (member) p.set('member', member)
  if (q) p.set('q', q)
  if (since) p.set('since', since)
  if (until) p.set('until', until)
  if (before) p.set('before', before)
  if (after) p.set('after', after)
  p.set('order', order)
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
