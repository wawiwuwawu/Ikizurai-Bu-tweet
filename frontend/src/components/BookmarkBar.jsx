// Chip penanda baca: tombol "kembali ke penanda" + hapus penanda.
// Muncul hanya kalau ada penanda DAN pengguna sedang jauh dari posisi penanda
// (kartu penanda tidak terlihat / tidak ada di DOM karena filter berubah).
import { formatWibShort } from '../utils.js'

export default function BookmarkBar({ bookmark, visible, onGoto, onClear }) {
  if (!bookmark || !visible) return null
  const when = bookmark.tweet?.created_at
  const label = `Kembali ke tweet ${bookmark.tweet?.member_name || bookmark.tweet?.member || ''} ${formatWibShort(when)}`.trim()

  return (
    <div className="bm-bar" role="group" aria-label="Penanda baca">
      <button type="button" className="bm-go" onClick={onGoto} title={label}>
        <span className="bm-ico" aria-hidden="true">📖</span>
        <span className="bm-txt">Kembali ke penanda</span>
        <em className="bm-when">{formatWibShort(when)}</em>
      </button>
      <button type="button" className="bm-clear" onClick={onClear}
              aria-label="Hapus penanda baca" title="Hapus penanda baca">
        ✕
      </button>
    </div>
  )
}