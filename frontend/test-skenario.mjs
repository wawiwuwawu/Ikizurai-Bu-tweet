// uji skenario asli user: baca dari bawah (mode Terlama), scroll jauh,
// tandai, tutup browser, buka lagi → harus kembali ke posisi yang sama.
import { JSDOM, VirtualConsole } from 'jsdom'
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const DATASET = path.join(ROOT, '..', 'dataset')
const MIME = { '.json': 'application/json' }
const server = http.createServer((req, res) => {
  const file = path.join(DATASET, new URL(req.url, 'http://x').pathname.slice('/dataset/'.length))
  if (!fs.existsSync(file)) { res.writeHead(404); return res.end() }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})
await new Promise((r) => server.listen(0, r))
const BASE = `http://127.0.0.1:${server.address().port}/`
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let pass = 0, fail = 0
const ok = (c, n, x = '') => { if (c) { pass++; console.log(`  ✓ ${n}`) } else { fail++; console.log(`  ✗ ${n} ${x}`) } }

async function boot(storage) {
  const vc = new VirtualConsole(); const errs = []
  vc.on('error', (m) => errs.push(String(m).slice(0, 70)))
  vc.on('jsdomError', (e) => errs.push('J:' + e.message.slice(0, 70)))
  const dom = new JSDOM('<!doctype html><body><div id="root"></div></body>', { url: BASE, runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc })
  const w = dom.window
  w.fetch = (i, init) => fetch(new URL(typeof i === 'string' ? i : i.url, BASE), init)
  w.HTMLElement.prototype.scrollIntoView = function () {}
  w.IntersectionObserver = class { constructor(cb) { this.cb = cb; this.el = null; w.__ios.push(this) } observe(el) { this.el = el } disconnect() { this.el = null } }
  w.__ios = []
  w.scrollToEnd = () => { for (const io of w.__ios) if (io.el?.classList.contains('sentinel')) io.cb([{ isIntersecting: true, target: io.el }]) }
  if (storage) for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v)
  const el = w.document.createElement('script'); el.textContent = fs.readFileSync('/tmp/app-iife.js', 'utf8'); w.document.body.appendChild(el)
  for (let i = 0; i < 120; i++) { if (w.document.querySelector('.card[data-id]')) break; await sleep(50) }
  await sleep(300)
  return { dom, w, errs }
}
const cards = (w) => [...w.document.querySelectorAll('.card[data-id]')]
const ids = (w) => cards(w).map((e) => e.dataset.id)

console.log('\n=== SKENARIO USER: baca dari bawah, scroll jauh, tandai, buka lagi ===')
{
  const a = await boot()
  // mode "Terlama" — pengguna membaca dari awal arsip ke bawah
  ;[...a.w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama')).click()
  await sleep(600)
  // scroll jauh ke bawah (8 halaman)
  for (let i = 0; i < 8; i++) { a.w.scrollToEnd(); await sleep(250) }
  const deep = cards(a.w)
  ok(deep.length >= 240, `sudah scroll jauh: ${deep.length} tweet termuat`)
  ok(ids(a.w).every((id, i) => i === 0 || ids(a.w)[i - 1] < id), 'urutan terlama → terbaru (membaca ke bawah)')

  // tandai tweet yang sedang dibaca (tengah daftar)
  const target = deep[150]
  const tid = target.dataset.id
  target.querySelector('.mark').click()
  await sleep(200)
  const store = { 'ikizurai:bookmark:v1': a.w.localStorage.getItem('ikizurai:bookmark:v1') }
  const savedOrder = JSON.parse(store['ikizurai:bookmark:v1']).filters.order
  a.dom.window.close()

  // "tutup & buka browser"
  const { dom, w, errs } = await boot(store)
  const shown = ids(w)
  ok(savedOrder === 'asc' && [...w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama')).classList.contains('on'),
    'buka lagi → langsung mode Terlama seperti waktu ditutup')
  ok(shown.includes(tid), `tweet penanda ${tid.slice(0, 8)}… ada di daftar (posisi ${shown.indexOf(tid)}/${shown.length})`)
  ok(shown.length <= 62, `hanya ±1 halaman dimuat, bukan 240+ (${shown.length} kartu)`)
  ok(w.document.querySelector('.card.marked')?.dataset.id === tid, 'kartu penanda ditandai 📍')
  ok(errs.length === 0, 'tidak ada error', errs.join(' | '))

  // lanjutkan membaca dari situ — infinite scroll masih정상
  const n0 = shown.length
  w.scrollToEnd(); await sleep(400)
  ok(ids(w).length > n0, `bisa lanjut baca ke bawah dari penanda (${n0} → ${ids(w).length})`)
  ok(new Set(ids(w)).size === ids(w).length, 'tidak ada duplikat saat melanjutkan')
  dom.window.close()
}

console.log(`\nLULUS: ${pass}  GAGAL: ${fail}`)
server.close(); process.exit(fail ? 1 : 0)