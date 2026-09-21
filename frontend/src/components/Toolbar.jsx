// Toolbar: pencarian, rentang tanggal, mode tampilan (ID/JP/JP+ID).
export default function Toolbar({ filters, onChange, onClear, hasFilter }) {
  return (
    <div className="toolbar">
      <div className="row">
        <div className="search-wrap">
          <span className="search-ico">🔍</span>
          <input
            className="search"
            type="search"
            placeholder="Cari kata di tweet (Jepang / Indonesia)…"
            value={filters.q}
            onChange={(e) => onChange({ q: e.target.value })}
            aria-label="Cari tweet"
          />
        </div>

        <div className="dates">
          <label>
            <span>Dari</span>
            <input type="date" value={filters.since} max={filters.until || undefined}
                   onChange={(e) => onChange({ since: e.target.value })} />
          </label>
          <label>
            <span>Sampai</span>
            <input type="date" value={filters.until} min={filters.since || undefined}
                   onChange={(e) => onChange({ until: e.target.value })} />
          </label>
        </div>

        <div className="viewtoggle" role="group" aria-label="Mode tampilan teks">
          {[
            ['id', '🇮🇩 ID'],
            ['jp', 'JP'],
            ['both', 'JP + ID'],
          ].map(([key, label]) => (
            <button key={key} type="button"
                    className={filters.view === key ? 'on' : ''}
                    onClick={() => onChange({ view: key })}>
              {label}
            </button>
          ))}
        </div>

        {hasFilter && (
          <button type="button" className="clear" onClick={onClear}>✕ Bersihkan</button>
        )}
      </div>
    </div>
  )
}
