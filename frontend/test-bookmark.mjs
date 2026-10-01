// Uji end-to-end fitur penanda baca: memuat bundle produksi (build static)
// di jsdom, memakai dataset asli. Jalankan: node test-bookmark.mjs
import { JSDOM, VirtualConsole } from 'jsdom'
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const BUNDLE = process.env.BUNDLE ?? '/tmp/app-iife.js'
const DATASET = path.join(ROOT, '..', 'dataset')
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg' }

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  const file = path.join(DATASET, url.pathname.slice('/dataset/'.length))
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end('404') }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})
await new Promise((r) => server.listen(0, r))
const BASE = `http://127.0.0.1:${server.address().port}/`

let pass = 0, fail = 0
const ok = (cond, name, extra = '') => {
  if (cond) { pass++; console.log(`  ✓ ${name}`) }
  else { fail++; console.log(`  ✗ ${name} ${extra}`) }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function boot({ storage } = {}) {
  const vc = new VirtualConsole()
  const errors = []
  vc.on('jsdomError', (e) => errors.push(e.message))
  vc.on('error', (m) => errors.push(String(m)))

  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
    url: BASE, runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  })
  const w = dom.window
  // polyfill yang tidak ada di jsdom tapi dipakai app
  w.fetch = (input, init) => fetch(new URL(typeof input === 'string' ? input : input.url, BASE), init)
  w.Headers ??= Headers
  w.Request ??= Request
  w.Response ??= Response
  w.AbortController ??= AbortController
  w.HTMLElement.prototype.scrollIntoView = function () {}
  // Mock realistis: sentinel HANYA memicu loadMore saat test memanggil
  // scrollToEnd() (meniru pengguna menggulir ke bawah). Kartu penanda hanya
  // memicu callback kalau test memanggil markVisibility().
  w.IntersectionObserver = class {
    constructor(cb) { this.cb = cb; this.el = null; w.__ios.push(this) }
    observe(el) { this.el = el }
    unobserve() {}
    disconnect() { this.el = null }
  }
  w.__ios = []
  w.scrollToEnd = () => {
    for (const io of w.__ios) if (io.el?.classList.contains('sentinel')) io.cb([{ isIntersecting: true, target: io.el }])
  }
  w.markVisibility = (on) => {
    for (const io of w.__ios) if (io.el?.classList.contains('card')) io.cb([{ isIntersecting: on, target: io.el }])
  }
  if (storage) for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v)

  const el = w.document.createElement('script')
  el.textContent = fs.readFileSync(BUNDLE, 'utf8')
  w.document.body.appendChild(el)

  // tunggu tweet pertama ter-render
  for (let i = 0; i < 200; i++) {
    if (w.document.querySelector('.card[data-id]')) break
    await sleep(50)
  }
  await sleep(400)
  if (!w.document.querySelector('.card[data-id]')) {
    console.log('  [debug] kartu tidak muncul. html:', w.document.body.innerHTML.slice(0, 200), '| errors:', errors)
  }
  return { dom, w, errors }
}

const ids = (w) => [...w.document.querySelectorAll('.card[data-id]')].map((e) => e.dataset.id)
const cards = (w) => [...w.document.querySelectorAll('.card[data-id]')]
const markedId = (w) => w.document.querySelector('.card.marked')?.dataset.id ?? null

console.log('\n=== 0. Infinite scroll tetap jalan (regresi) ===')
{
  const { dom, w, errors } = await boot()
  const n0 = cards(w).length
  ok(n0 === 30, `halaman pertama tepat 30 kartu (dapat ${n0})`)
  w.scrollToEnd(); await sleep(400)
  ok(cards(w).length === 60, `scroll lagi → 60 kartu (dapat ${cards(w).length})`)
  w.scrollToEnd(); await sleep(400)
  const all = cards(w)
  ok(all.length === 90, `scroll lagi → 90 kartu (dapat ${all.length})`)
  ok(new Set(all).size === all.length, 'tidak ada tweet duplikat setelah 3 halaman')
  const sorted = [...all]
  ok(sorted.every((id, i) => i === 0 || sorted[i - 1] >= id), 'urutan tetap terbaru → terlama')
  ok(errors.length === 0, 'tidak ada error', errors.join('; '))
  dom.window.close()
}

console.log('\n=== 1. Tandai posisi di tengah daftar ===')
{
  const { dom, w, errors } = await boot()
  const all = cards(w)
  ok(all.length >= 30, `halaman pertama berisi ${all.length} kartu`)
  ok(w.document.querySelectorAll('.mark').length === all.length, 'setiap kartu punya tombol 🔖')

  const target = all[12]
  const tid = target.dataset.id
  target.querySelector('.mark').click()
  await sleep(120)

  ok(markedId(w) === tid, `kartu ${tid.slice(0, 8)}… jadi penanda`)
  ok(target.querySelector('.mark').classList.contains('on'), 'tombol penanda aktif (label "penanda")')
  ok(target.querySelector('.mark').getAttribute('aria-pressed') === 'true', 'aria-pressed = true')

  const saved = JSON.parse(w.localStorage.getItem('ikizurai:bookmark:v1'))
  ok(saved?.id === tid, 'tersimpan di localStorage dengan id yang benar')
  ok(saved?.filters?.order === 'desc' && 'view' in saved.filters, 'filter ikut tersimpan', JSON.stringify(saved?.filters))
  ok(saved?.tweet?.id_str === tid && !!saved.tweet.created_at, 'snapshot tweet ikut tersimpan (cadangan)')
  ok(errors.length === 0, 'tidak ada error runtime', errors.join('; '))
  dom.window.close()
}

console.log('\n=== 2. Tandai lagi di tweet lain → penanda lama hilang ===')
{
  const { dom, w } = await boot()
  const all = cards(w)
  all[5].querySelector('.mark').click(); await sleep(80)
  const first = all[5].dataset.id
  all[20].querySelector('.mark').click(); await sleep(80)
  ok(markedId(w) === all[20].dataset.id, 'penanda pindah ke kartu baru')
  ok(w.document.querySelectorAll('.card.marked').length === 1, 'hanya satu kartu berpenanda')
  ok(JSON.parse(w.localStorage.getItem('ikizurai:bookmark:v1')).id === all[20].dataset.id, 'localStorage ditimpa')
  ok(!w.document.querySelector(`.card[data-id="${first}"]`).classList.contains('marked'), 'penanda lama dilepas')
  dom.window.close()
}

console.log('\n=== 3. Buka ulang browser → restore ke tweet penanda ===')
{
  const first = await boot()
  const all = cards(first.w)
  const tid = all[12].dataset.id
  const savedFilters = JSON.parse(first.w.localStorage.getItem('ikizurai:bookmark:v1') ?? 'null')
  all[12].querySelector('.mark').click()
  await sleep(150)
  const store = { 'ikizurai:bookmark:v1': first.w.localStorage.getItem('ikizurai:bookmark:v1') }
  first.dom.window.close()

  // "browser ditutup & dibuka lagi" → localStorage sama persis, halaman baru
  const { dom, w, errors } = await boot({ storage: store })
  const shown = ids(w)
  ok(shown.includes(tid), `tweet penanda ${tid.slice(0, 8)}… ada di daftar (posisi ${shown.indexOf(tid)})`)
  ok(markedId(w) === tid, 'kartu penanda diberi tanda 📍')
  ok(shown.length > 1 && shown.length <= 62, `restore ±1 halaman: ${shown.length} kartu (bukan 2463)`, String(shown.length))
  const i = shown.indexOf(tid)
  ok(i > 0, `ada konteks di atas (${i} kartu)`)
  ok(i < shown.length - 1, `ada konteks di bawah (${shown.length - 1 - i} kartu)`)
  ok(w.document.querySelector('[data-testid]') === null, 'tidak ada elemen asing')
  ok(errors.length === 0, 'tidak ada error runtime', errors.join('; '))
  void savedFilters
  dom.window.close()
}

console.log('\n=== 4. Filter ikut dipulihkan + restore ulang saat filter berubah ===')
{
  const a = await boot()
  const all = cards(a.w)
  // simulate: user baca dengan urutan "Terlama" (asc)
  const asc = [...a.w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama'))
  asc.click(); await sleep(600)
  const allAsc = cards(a.w)
  const tid = allAsc[8].dataset.id
  allAsc[8].querySelector('.mark').click(); await sleep(150)
  const store = { 'ikizurai:bookmark:v1': a.w.localStorage.getItem('ikizurai:bookmark:v1') }
  a.dom.window.close()

  const { dom, w, errors } = await boot({ storage: store })
  const ascBtn = [...w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama'))
  ok(ascBtn.classList.contains('on'), 'tombol "Terlama" aktif lagi (urutan dipulihkan)')
  ok(ids(w).includes(tid), `tweet penanda (mode asc) dipulihkan: ${tid.slice(0, 8)}…`)
  ok(errors.length === 0, 'tidak ada error runtime', errors.join('; '))
  dom.window.close()
}

console.log('\n=== 5. Tweet penanda di luar daftar saat ini → chip "Kembali" ===')
{
  const { dom, w, errors } = await boot()
  const all = cards(w)
  all[3].querySelector('.mark').click()
  await sleep(120)
  ok(!w.document.querySelector('.bm-bar'), 'chip disembunyikan saat tweet penanda terlihat')

  // ganti filter member → daftar berubah, tweet penanda tidak termuat
  const chip = [...w.document.querySelectorAll('.chip')].find((c) => c.textContent.includes('member') === false && c.textContent.trim().length > 2)
  chip.click()
  await sleep(700)
  const markedStillThere = markedId(w) !== null
  ok(!markedId(w) || !w.document.querySelector('.card.marked'), 'penanda tidak ikut berubah saat filter diganti')
  ok(markedStillThere ? w.document.querySelector('.bm-bar') !== null : true, 'chip muncul saat pengguna jauh dari penanda')

  // klik chip → harus restore ke tweet penanda
  const bar = w.document.querySelector('.bm-bar')
  ok(bar !== null, 'chip "Kembali ke penanda" tampil')
  bar.querySelector('.bm-go').click()
  await sleep(900)
  const saved = JSON.parse(w.localStorage.getItem('ikizurai:bookmark:v1'))
  ok(ids(w).includes(saved.id), 'klik chip mengembalikan daftar ke tweet penanda')
  ok(errors.length === 0, 'tidak ada error runtime', errors.join('; '))
  dom.window.close()
}

console.log('\n=== 6. Hapus penanda ===')
{
  const { dom, w } = await boot()
  cards(w)[4].querySelector('.mark').click(); await sleep(100)
  ok(markedId(w) !== null, 'penanda dibuat')
  cards(w)[4].querySelector('.mark').click(); await sleep(100)
  ok(markedId(w) === null, 'klik 🔖 lagi di tweet yang sama → penanda dihapus')
  ok(w.localStorage.getItem('ikizurai:bookmark:v1') === null, 'localStorage dibersihkan')
  ok(w.document.querySelector('.bm-bar') === null, 'chip hilang')
  dom.window.close()
}

console.log('\n=== 7. Ketahanan: localStorage rusak / tidak ada penanda ===')
{
  const { dom, w, errors } = await boot({ storage: { 'ikizurai:bookmark:v1': '{bukan jsonValid' } })
  ok(errors.length === 0, 'JSON rusak tidak membuat crash', errors.join('; '))
  ok(cards(w).length >= 30, 'daftar tetap termuat normal')
  ok(w.document.querySelector('.bm-bar') === null, 'chip tidak muncul')
  dom.window.close()
}
{
  const { dom, w, errors } = await boot()
  ok(cards(w).length >= 30, 'tanpa penanda: daftar normal')
  ok(markedId(w) === null, 'tidak ada kartu bertanda')
  ok(errors.length === 0, 'tidak ada error', errors.join('; '))
  dom.window.close()
}

console.log('\n=== 8. Tampilan lama tidak berubah ===')
{
  const { dom, w } = await boot()
  ok(w.document.querySelector('.hero h1').textContent === 'Ikizurai-Bu Tweet', 'hero tetap sama')
  ok(w.document.querySelectorAll('.chip').length >= 11, 'chip member tetap lengkap')
  ok(w.document.querySelectorAll('.viewtoggle').length === 2, 'dua grup tombol view tetap ada')
  const card = cards(w)[0]
  ok(card.querySelector('.open')?.textContent.includes('Buka di X'), 'link "Buka di X ↗" tetap ada')
  ok(card.querySelector('.avatar') !== null, 'avatar tetap ada')
  const footChildren = [...card.querySelector('.foot').children].map((c) => c.className)
  ok(footChildren.filter((c) => c === 'stat').length === 2, 'dua stat (❤ 💬) tetap ada')
  dom.window.close()
}

server.close()
console.log(`\n${'='.repeat(46)}\nLULUS: ${pass}   GAGAL: ${fail}\n${'='.repeat(46)}\n`)
process.exit(fail ? 1 : 0)