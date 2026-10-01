// Uji penanda baca dalam MODE API (backend FastAPI) — memakai stub HTTP yang
// menjalankan SQL query_tweets backend apa adanya.
import { JSDOM, VirtualConsole } from 'jsdom'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const BUNDLE = process.env.BUNDLE ?? '/tmp/app-api-iife.js'
const API = process.env.API ?? 'http://127.0.0.1:8099'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let pass = 0, fail = 0
const ok = (c, n, x = '') => { if (c) { pass++; console.log(`  ✓ ${n}`) } else { fail++; console.log(`  ✗ ${n} ${x}`) } }

async function boot(storage) {
  const vc = new VirtualConsole(); const errs = []
  vc.on('error', (m) => errs.push(String(m).slice(0, 70)))
  vc.on('jsdomError', (e) => errs.push('J:' + e.message.slice(0, 70)))
  // origin = API (same-origin, seperti produksi: FE di FastAPI yang sama)
  const dom = new JSDOM('<!doctype html><body><div id="root"></div></body>', { url: API, runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc })
  const w = dom.window
  w.fetch = (i, init) => fetch(new URL(typeof i === 'string' ? i : i.url, API), init) // path relatif → same-origin
  w.HTMLElement.prototype.scrollIntoView = function () {}
  w.IntersectionObserver = class { constructor(cb) { this.cb = cb; this.el = null; w.__ios.push(this) } observe(el) { this.el = el } disconnect() { this.el = null } }
  w.__ios = []
  w.scrollToEnd = () => { for (const io of w.__ios) if (io.el?.classList.contains('sentinel')) io.cb([{ isIntersecting: true, target: io.el }]) }
  if (storage) for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v)
  const el = w.document.createElement('script'); el.textContent = fs.readFileSync(BUNDLE, 'utf8'); w.document.body.appendChild(el)
  for (let i = 0; i < 120; i++) { if (w.document.querySelector('.card[data-id]')) break; await sleep(50) }
  await sleep(300)
  if (!w.document.querySelector('.card[data-id]')) {
    console.log('  [debug]', w.document.body.innerHTML.slice(0, 150), '| err:', errs.join(' | '))
  }
  return { dom, w, errs }
}
const ids = (w) => [...w.document.querySelectorAll('.card[data-id]')].map((e) => e.dataset.id)
const cards = (w) => [...w.document.querySelectorAll('.card[data-id]')]

console.log('\n=== MODE API ===')
{
  const a = await boot()
  const n0 = cards(a.w).length
  ok(n0 === 30, `halaman pertama 30 kartu (dapat ${n0})`)
  a.w.scrollToEnd(); await sleep(400)
  ok(cards(a.w).length === 60, `infinite scroll API: 60 kartu (dapat ${cards(a.w).length})`)
  a.dom.window.close()
}

console.log('\n=== MODE API: skenario baca dari bawah ===')
{
  const a = await boot()
  ;[...a.w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama')).click()
  await sleep(500)
  for (let i = 0; i < 10; i++) { a.w.scrollToEnd(); await sleep(200) }
  const deep = cards(a.w)
  ok(deep.length >= 300, `scroll jauh: ${deep.length} tweet`)
  const target = deep[180]
  const tid = target.dataset.id
  target.querySelector('.mark').click()
  await sleep(200)
  const store = { 'ikizurai:bookmark:v1': a.w.localStorage.getItem('ikizurai:bookmark:v1') }
  a.dom.window.close()

  const { dom, w, errs } = await boot(store)
  const shown = ids(w)
  ok(shown.includes(tid), `restore ke tweet penanda ${tid.slice(0, 8)}… (posisi ${shown.indexOf(tid)}/${shown.length})`)
  ok(shown.length <= 62, `±1 halaman (${shown.length} kartu, bukan ${deep.length})`)
  ok(w.document.querySelector('.card.marked')?.dataset.id === tid, 'kartu ditandai 📍')
  // urutan asc harus tetap terjaga setelah restore
  ok([...w.document.querySelectorAll('.viewtoggle button')].find((b) => b.textContent.includes('Terlama')).classList.contains('on'), 'urutan Terlama dipulihkan')
  const asc = shown.every((id, i) => i === 0 || shown[i - 1] < id)
  ok(asc, 'urutan tweet tetap naik (terlama → terbaru)')
  const before = shown.length
  w.scrollToEnd(); await sleep(400)
  ok(ids(w).length > before, `lanjut baca dari penanda (${before} → ${ids(w).length})`)
  ok(new Set(ids(w)).size === ids(w).length, 'tidak ada duplikat')
  ok(errs.length === 0, 'tidak ada error', errs.join(' | '))
  dom.window.close()
}

console.log('\n=== MODE API: filter member + penanda ===')
{
  const a = await boot()
  // pilih chip member sungguhan (bukan "Semua member" yang tidak memfilter)
  const chip = [...a.w.document.querySelectorAll('.chip')].find((c) => !c.textContent.includes('Semua'))
  const chipName = chip.textContent.trim().slice(0, 10)
  chip.click(); await sleep(600)
  const cs = cards(a.w)
  ok(cs.length === 30, `filter member: ${cs.length} kartu`)
  const tid = cs[10].dataset.id
  cs[10].querySelector('.mark').click(); await sleep(150)
  const store = { 'ikizurai:bookmark:v1': a.w.localStorage.getItem('ikizurai:bookmark:v1') }
  a.dom.window.close()

  const { dom, w, errs } = await boot(store)
  const active = w.document.querySelector('.chip.active')?.textContent.trim().slice(0, 10)
  ok(active && !active.includes('Semua'), `filter member dipulihkan: ${active} (dibuat: ${chipName})`)
  ok(ids(w).includes(tid), 'tweet penanda ditemukan setelah restore + filter')
  ok(errs.length === 0, 'tidak ada error', errs.join(' | '))
  dom.window.close()
}

console.log(`\nLULUS: ${pass}  GAGAL: ${fail}`)
process.exit(fail ? 1 : 0)