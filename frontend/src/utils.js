// Util format tampilan.

/** ISO UTC → "18 Sep 2026 • 19:25 WIB" */
export function formatWib(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const date = new Intl.DateTimeFormat('id-ID', {
    timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short', year: 'numeric',
  }).format(d)
  const time = new Intl.DateTimeFormat('id-ID', {
    timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(d)
  return `${date} • ${time} WIB`
}

/** "2026-09-21T14:00:00Z" → "21 Sep • 21:00 WIB" (ringkas, untuk header) */
export function formatWibShort(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat('id-ID', {
    timeZone: 'Asia/Jakarta', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(d) + ' WIB'
}

/** Pecah teks jadi paragraf (baris kosong = pemisah). */
export function toParagraphs(text) {
  if (!text) return []
  return text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
}

export function nf(n) {
  return new Intl.NumberFormat('id-ID').format(n ?? 0)
}
