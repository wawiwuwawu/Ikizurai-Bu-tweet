const BASE = import.meta.env.VITE_API_BASE ?? ''

async function get(path, { signal } = {}) {
  const res = await fetch(`${BASE}${path}`, { signal })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function fetchTweets({ member, q, since, until, before, limit = 30, signal }) {
  const p = new URLSearchParams()
  if (member) p.set('member', member)
  if (q) p.set('q', q)
  if (since) p.set('since', since)
  if (until) p.set('until', until)
  if (before) p.set('before', before)
  p.set('limit', String(limit))
  return get(`/api/tweets?${p.toString()}`, { signal })
}

export const fetchMembers = (signal) => get('/api/members', { signal })
export const fetchStats = (signal) => get('/api/stats', { signal })
