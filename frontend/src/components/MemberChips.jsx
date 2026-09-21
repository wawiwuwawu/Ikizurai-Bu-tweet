// Chip filter member: avatar + nama. Klik = filter; klik lagi = reset.
export default function MemberChips({ members, active, onSelect }) {
  if (!members.length) return null
  return (
    <div className="chips" role="list">
      <button
        type="button"
        className={`chip ${active === '' ? 'active' : ''}`}
        onClick={() => onSelect('')}
      >
        Semua member
      </button>
      {members.map((m) => (
        <button
          key={m.screen_name}
          type="button"
          role="listitem"
          className={`chip ${active === m.screen_name ? 'active' : ''}`}
          style={{ '--mc': m.color_ui || m.color }}
          title={`${m.romaji} (@${m.screen_name})`}
          onClick={() => onSelect(m.screen_name)}
        >
          {m.avatar && <img src={m.avatar} alt="" loading="lazy" />}
          <span className="chip-name">{m.jp_name}</span>
          <span className="chip-count">{m.count}</span>
        </button>
      ))}
    </div>
  )
}
