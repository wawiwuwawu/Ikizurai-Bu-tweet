// Penanda baca — satu posisi baca terakhir, disimpan di localStorage browser.
//
// Bentuk data (v1):
//   { v: 1, id: "<id_str>", tweet: { ...snapshot tweet... },
//     filters: { member, q, since, until, view, order }, saved_at: "<ISO>" }
//
// `tweet` ikut disimpan sebagai cadangan: kalau saat restore tweet penanda tidak
// muncul di hasil query (mis. hari itu tweet-nya melebihi 1 halaman, atau tweet
// hilang dari arsip), salinan ini tetap bisa dirender.
//
// Penanda cuma satu — menandai posisi baru otomatis menimpa yang lama.

const KEY = 'ikizurai:bookmark:v1'
const MAX_TWEET_BYTES = 8000 // buang media kalau salinan tweet terlalu besar

const FILTER_KEYS = ['member', 'q', 'since', 'until', 'view', 'order']

/** Buang key asing + pastikan nilainya string (aman untuk form/date input). */
export function sanitizeFilters(raw) {
  const f = {}
  for (const k of FILTER_KEYS) {
    const v = raw?.[k]
    f[k] = typeof v === 'string' ? v : ''
  }
  f.view = f.view || 'both'
  f.order = f.order === 'asc' ? 'asc' : 'desc'
  return f
}

export function readBookmark() {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const bm = JSON.parse(raw)
    if (!bm || typeof bm !== 'object') return null
    if (!bm.id || !bm.tweet?.id_str) return null
    return { ...bm, filters: sanitizeFilters(bm.filters) }
  } catch {
    return null // JSON rusak / localStorage tidak tersedia (mode privat) → dianggap belum ada penanda
  }
}

export function writeBookmark({ tweet, filters }) {
  const copy = { ...tweet }
  if (JSON.stringify(copy).length > MAX_TWEET_BYTES) delete copy.media // biar kecil
  const bm = {
    v: 1,
    id: tweet.id_str,
    tweet: copy,
    filters: sanitizeFilters(filters),
    saved_at: new Date().toISOString(),
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(bm))
  } catch {
    // kuota penuh / storage diblokir — penanda tetap hidup di sesi ini saja
  }
  return bm
}

export function clearBookmark() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // abaikan
  }
}