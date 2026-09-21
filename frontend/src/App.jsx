import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchMembers, fetchStats, fetchTweets } from './api.js'
import MemberChips from './components/MemberChips.jsx'
import Toolbar from './components/Toolbar.jsx'
import TweetCard from './components/TweetCard.jsx'
import { formatWibShort, nf } from './utils.js'

const PAGE = 30

export default function App() {
  const [members, setMembers] = useState([])
  const [stats, setStats] = useState(null)
  const [filters, setFilters] = useState({ member: '', q: '', since: '', until: '', view: 'both' })

  const [tweets, setTweets] = useState([])
  const [nextBefore, setNextBefore] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [bootError, setBootError] = useState(null)

  const qDebounced = useDebounced(filters.q, 350)
  const memberMap = useMemo(() => Object.fromEntries(members.map((m) => [m.screen_name, m])), [members])
  const filterKey = `${filters.member}|${qDebounced}|${filters.since}|${filters.until}`

  // ---- data awal (member + statistik)
  useEffect(() => {
    const ac = new AbortController()
    Promise.all([fetchMembers(ac.signal), fetchStats(ac.signal)])
      .then(([ms, st]) => { setMembers(ms); setStats(st) })
      .catch((e) => { if (e.name !== 'AbortError') setBootError(e.message) })
    return () => ac.abort()
  }, [])

  // ---- daftar tweet (reset saat filter berubah)
  useEffect(() => {
    const ac = new AbortController()
    setLoading(true)
    setError(null)
    fetchTweets({
      member: filters.member, q: qDebounced, since: filters.since, until: filters.until,
      limit: PAGE, signal: ac.signal,
    })
      .then((d) => { setTweets(d.items); setNextBefore(d.next_before); setLoading(false) })
      .catch((e) => { if (e.name !== 'AbortError') { setError(e.message); setLoading(false) } })
    return () => ac.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  const loadMore = useCallback(() => {
    if (!nextBefore || loadingMore || loading) return
    setLoadingMore(true)
    fetchTweets({
      member: filters.member, q: qDebounced, since: filters.since, until: filters.until,
      before: nextBefore, limit: PAGE,
    })
      .then((d) => { setTweets((t) => [...t, ...d.items]); setNextBefore(d.next_before) })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingMore(false))
  }, [nextBefore, loadingMore, loading, filters.member, qDebounced, filters.since, filters.until])

  // ---- infinite scroll
  const sentinel = useRef(null)
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver((entries) => { if (entries[0].isIntersecting) loadMore() }, { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [loadMore])

  const setFilter = (patch) => setFilters((f) => ({ ...f, ...patch }))
  const hasFilter = Boolean(filters.member || filters.q || filters.since || filters.until)

  return (
    <div className="page">
      <header className="hero">
        <div className="hero-inner">
          <div className="hero-title">
            <span className="bird">🐦</span>
            <div>
              <h1>Ikizurai-Bu Tweet</h1>
              <p className="sub">イキヅライブ！LOVELIVE!BLUEBIRD — arsip tweet 10 member + terjemahan Indonesia</p>
            </div>
          </div>
          <div className="hero-stats">
            {stats ? (
              <>
                <span><b>{nf(stats.total)}</b> tweet</span>
                <span><b>{nf(stats.translated)}</b> diterjemahkan</span>
                <span>cek terakhir <b>{formatWibShort(stats.last_check)}</b></span>
              </>
            ) : (
              <span className="muted">memuat…</span>
            )}
          </div>
        </div>
      </header>

      <main className="container">
        <MemberChips members={members} active={filters.member}
                     onSelect={(m) => setFilter({ member: m === filters.member ? '' : m })} />

        <Toolbar
          filters={filters}
          onChange={setFilter}
          onClear={() => setFilters({ member: '', q: '', since: '', until: '', view: filters.view })}
          hasFilter={hasFilter}
        />

        {bootError && <p className="notice err">Gagal memuat data awal: {bootError}</p>}
        {error && <p className="notice err">Terjadi kesalahan: {error}</p>}

        {loading ? (
          <div className="list">{[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}</div>
        ) : tweets.length === 0 ? (
          <p className="notice">Tidak ada tweet yang cocok dengan filter. 🐦</p>
        ) : (
          <>
            <div className="list">
              {tweets.map((t) => (
                <TweetCard key={t.id_str} tweet={t} member={memberMap[t.member]} view={filters.view} />
              ))}
            </div>
            <div ref={sentinel} className="sentinel">
              {loadingMore ? 'Memuat lagi…' : nextBefore ? '' : '— akhir arsip —'}
            </div>
          </>
        )}
      </main>

      <footer className="footer">
        <span>Ikizurai-Bu Tweet · proyek penggemar non-resmi · data dari arsip X publik</span>
        <span>© プロジェクトイキヅライブ！</span>
      </footer>
    </div>
  )
}

function SkeletonCard() {
  return (
    <div className="card skeleton">
      <div className="sk-avatar" />
      <div className="sk-lines">
        <div className="sk-line w40" />
        <div className="sk-line w90" />
        <div className="sk-line w70" />
      </div>
    </div>
  )
}

function useDebounced(value, ms) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
