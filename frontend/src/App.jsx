import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchMembers, fetchStats, fetchTweets } from './api.js'
import { clearBookmark, readBookmark, sanitizeFilters, writeBookmark } from './bookmark.js'
import BookmarkBar from './components/BookmarkBar.jsx'
import MemberChips from './components/MemberChips.jsx'
import Toolbar from './components/Toolbar.jsx'
import TweetCard from './components/TweetCard.jsx'
import { formatWibShort, nf } from './utils.js'

const PAGE = 30
const DEFAULT_FILTERS = { member: '', q: '', since: '', until: '', view: 'both', order: 'desc' }

export default function App() {
  const [boot] = useState(() => readBookmark())
  const [members, setMembers] = useState([])
  const [stats, setStats] = useState(null)
  const [filters, setFilters] = useState(() => ({ ...DEFAULT_FILTERS, ...(boot?.filters ?? {}) }))

  // ---- penanda baca
  const [bookmark, setBookmark] = useState(boot)
  const [jumpNonce, setJumpNonce] = useState(0)
  const [restoring, setRestoring] = useState(false)
  const [markOnScreen, setMarkOnScreen] = useState(true)
  const pendingMark = useRef(boot) // penanda yang belum direstore
  const scrollTarget = useRef(null) // id tweet yang harus di-scroll setelah dirender
  const loadMoreRef = useRef(null) // cursor loadMore yang sedang berjalan (anti duplikat)
  const genRef = useRef(0) // generasi filter; hasil request dari generasi lama dibuang

  const [tweets, setTweets] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [bootError, setBootError] = useState(null)

  const qDebounced = useDebounced(filters.q, 350)
  const memberMap = useMemo(() => Object.fromEntries(members.map((m) => [m.screen_name, m])), [members])
  const filterKey = `${filters.member}|${qDebounced}|${filters.since}|${filters.until}|${filters.order}|${jumpNonce}`

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
    let cancelled = false
    const mark = pendingMark.current
    // filter berubah → naikkan generasi. loadMore yang masih/antre dengan
    // generasi lama otomatis dibuang (tidak akan menempelkan tweet filter lama).
    genRef.current += 1
    loadMoreRef.current = null
    setLoading(true)
    setError(null)
    setRestoring(Boolean(mark))
    fetchTweets({
      member: filters.member, q: qDebounced, since: filters.since, until: filters.until,
      order: filters.order, limit: PAGE, signal: ac.signal,
    })
      .then(async (d) => {
        if (cancelled) return
        // tweet penanda tidak ada di halaman pertama → bangun daftar di sekelilingnya
        if (mark && !d.items.some((t) => t.id_str === mark.id)) {
          const w = await fetchWindow(mark, ac.signal)
          if (cancelled) return
          setTweets(dedupe(w.items))
          setNextCursor(w.next)
        } else {
          setTweets(d.items)
          setNextCursor(d.next_cursor)
        }
        pendingMark.current = null
        if (mark) scrollTarget.current = mark.id
        setLoading(false)
        setRestoring(false)
      })
      .catch((e) => {
        if (e.name === 'AbortError' || cancelled) return
        setError(e.message); setLoading(false); setRestoring(false)
      })
    return () => { cancelled = true; ac.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  const loadMore = useCallback(() => {
    if (!nextCursor || loadMoreRef.current || loading || restoring) return
    const gen = genRef.current
    const cursor = nextCursor
    loadMoreRef.current = cursor
    setLoadingMore(true)
    fetchTweets({
      member: filters.member, q: qDebounced, since: filters.since, until: filters.until,
      order: filters.order,
      ...(filters.order === 'asc' ? { after: cursor } : { before: cursor }),
      limit: PAGE,
    })
      .then((d) => {
        // request selesai tapi filter sudah berubah / request lain menggantikannya → buang
        if (gen !== genRef.current || loadMoreRef.current !== cursor) return
        // jaga-jaga: jangan pernah menempelkan tweet yang sudah ada di daftar
        setTweets((t) => {
          const seen = new Set(t.map((x) => x.id_str))
          return [...t, ...d.items.filter((x) => !seen.has(x.id_str))]
        })
        setNextCursor(d.next_cursor)
      })
      .catch((e) => { if (gen === genRef.current && loadMoreRef.current === cursor) setError(e.message) })
      .finally(() => {
        if (gen === genRef.current && loadMoreRef.current === cursor) {
          loadMoreRef.current = null
          setLoadingMore(false)
        }
      })
  }, [nextCursor, loading, restoring, filters.member, qDebounced, filters.since, filters.until, filters.order])

  // ---- scroll ke tweet tertentu (setelah React selesai render)
  useEffect(() => {
    const id = scrollTarget.current
    if (!id || !tweets.length) return
    scrollTarget.current = null
    requestAnimationFrame(() => requestAnimationFrame(() => {
      document.querySelector(`.card[data-id="${id}"]`)?.scrollIntoView({ block: 'start' })
    }))
  }, [tweets])

  // ---- infinite scroll
  const sentinel = useRef(null)
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const gen = genRef.current
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && gen === genRef.current) loadMore()
    }, { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [loadMore])

  const setFilter = (patch) => setFilters((f) => ({ ...f, ...patch }))
  const hasFilter = Boolean(filters.member || filters.q || filters.since || filters.until)

  // ganti urutan → kembali ke atas (biar kelihatan dari awal daftar), tapi jangan
  // menabrak scroll restore saat pertama kali buka.
  const firstRun = useRef(true)
  useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filters.order])

  // ---- aksi penanda baca

  // klik 🔖 di kartu: simpan posisi (menimpa yang lama), atau hapus kalau diklik lagi di tweet yang sama
  const markTweet = useCallback((tweet) => {
    if (bookmark?.id === tweet.id_str) {
      clearBookmark()
      setBookmark(null)
      return
    }
    setBookmark(writeBookmark({ tweet, filters }))
  }, [bookmark, filters])

  const gotoMark = useCallback(() => {
    if (!bookmark) return
    if (scrollToCard(bookmark.id, 'smooth')) return // kartu masih ada di daftar → cukup digulir
    // kartu tidak ada (filter berubah / di luar daftar yang termuat) → restore ulang
    pendingMark.current = bookmark
    setJumpNonce((n) => n + 1)
    setFilters((f) => (sameFilters(f, bookmark.filters) ? f : { ...DEFAULT_FILTERS, ...bookmark.filters }))
  }, [bookmark])

  const dropMark = useCallback(() => {
    clearBookmark()
    setBookmark(null)
  }, [])

  // chip "kembali ke penanda" hanya perlu kalau pengguna jauh dari tweet penanda.
  // "tweet penanda ada di daftar" dihitung saat render (murni), sedangkan
  // "sedang terlihat di layar" datang dari callback IntersectionObserver.
  useEffect(() => {
    if (!bookmark) return
    const el = document.querySelector(`.card[data-id="${bookmark.id}"]`)
    if (!el) return // tidak ada di DOM → sudah tertutup oleh markInList
    const io = new IntersectionObserver((es) => setMarkOnScreen(es[0].isIntersecting), { rootMargin: '-72px 0px -45% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [bookmark, tweets])

  // chip hanya muncul kalau ada penanda, tweet-nya tidak sedang tampil di layar,
  // dan belum selesai proses restore
  const markInList = Boolean(bookmark) && tweets.some((t) => t.id_str === bookmark.id)
  const showBar = Boolean(bookmark) && !restoring && !(markInList && markOnScreen)

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
                <span>{stats.generated_at ? 'data per' : 'cek terakhir'}{' '}
                  <b>{formatWibShort(stats.generated_at || stats.last_check)}</b></span>
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
          onClear={() => setFilters({ ...DEFAULT_FILTERS, view: filters.view, order: filters.order })}
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
                <TweetCard key={t.id_str} tweet={t} member={memberMap[t.member]} view={filters.view}
                           marked={bookmark?.id === t.id_str} onMark={markTweet} />
              ))}
            </div>
            <div ref={sentinel} className="sentinel">
              {restoring ? '📍 Menuju penanda…' : loadingMore ? 'Memuat lagi…' : nextCursor ? '' : '— akhir arsip —'}
            </div>
          </>
        )}
      </main>

      <footer className="footer">
        <span>Ikizurai-Bu Tweet · proyek penggemar non-resmi · data dari arsip X publik (gsm-app.com)</span>
        <span>terjemahan dibuat AI (bukan 100% akurat) · © プロジェクトイキヅライブ！</span>
      </footer>

      <BookmarkBar bookmark={bookmark} visible={showBar} onGoto={gotoMark} onClear={dropMark} />
    </div>
  )
}

// Bangun daftar di sekitar tweet penanda.
//
// Selalu ada "1 halaman di bawahnya" (kursor ke arah bacafurther) supaya
// infinite scroll langsung lanjut normal. Di atas penanda: tweet-tweet lain
// pada hari yang sama bila ada (konteks), jika tidak ya tidak ada.
async function fetchWindow(mark, signal) {
  const f = sanitizeFilters(mark.filters)
  const base = { member: f.member, q: f.q, since: f.since, until: f.until, order: f.order, signal }
  const cursorKey = f.order === 'asc' ? 'after' : 'before'

  // 1) konteks di atas penanda: tweet lain pada hari yang sama
  const day = String(mark.tweet?.created_at ?? '').slice(0, 10)
  const before = []
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    const r = await fetchTweets({ ...base, since: day, until: day, limit: PAGE, signal })
    const i = r.items.findIndex((t) => t.id_str === mark.id)
    if (i >= 0) before.push(...r.items.slice(0, i))
  }

  // 2) 1 halaman di bawah penanda — ini yang jadi next_cursor untuk lanjut baca
  const after = await fetchTweets({ ...base, [cursorKey]: mark.id, limit: PAGE, signal })
  const self = mark.tweet ?? after.items.find((t) => t.id_str === mark.id) ?? null
  const below = after.items.filter((t) => t.id_str !== mark.id)
  const items = dedupe(self ? [...before, self, ...below] : [...before, ...below])
  return { items, next: after.next_cursor }
}

/** Buang tweet berduplikat (React butuh key unik) — jaga-jaga bila halaman
 *  hasil fetch tumpang tindih. */
function dedupe(items) {
  const seen = new Set()
  return items.filter((t) => (seen.has(t.id_str) ? false : (seen.add(t.id_str), true)))
}

function sameFilters(a, b) {
  return ['member', 'q', 'since', 'until', 'view', 'order'].every((k) => (a?.[k] ?? '') === (b?.[k] ?? ''))
}

/** Gulir ke kartu tweet tertentu. False kalau kartu itu tidak ada di DOM. */
function scrollToCard(id, behavior = 'auto') {
  const el = document.querySelector(`.card[data-id="${id}"]`)
  if (!el) return false
  el.scrollIntoView({ behavior, block: 'start' })
  return true
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
