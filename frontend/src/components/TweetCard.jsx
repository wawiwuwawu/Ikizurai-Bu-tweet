import { formatWib, nf, toParagraphs } from '../utils.js'

export default function TweetCard({ tweet, member, view }) {
  const color = member?.color_ui || member?.color || '#3A85BA'
  const jp = toParagraphs(tweet.text)
  const id = toParagraphs(tweet.text_id)
  const showJp = view === 'jp' || view === 'both'
  const showId = view === 'id' || view === 'both'

  return (
    <article className="card" style={{ '--mc': color }}>
      <img className="avatar" src={tweet.avatar || member?.avatar || ''} alt="" loading="lazy"
           onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
      <div className="body">
        <header className="meta">
          <span className="name">{member?.jp_name || tweet.member_name || tweet.member}</span>
          {member?.romaji && <span className="romaji">{member.romaji}</span>}
          <span className="handle">@{tweet.member}</span>
          <span className="time">· {formatWib(tweet.created_at)}</span>
        </header>

        {showJp && (
          <div className="txt jp">
            {jp.map((p, i) => <p key={i}>{p}</p>)}
          </div>
        )}

        {showId && (
          tweet.text_id ? (
            <div className={`txt id ${view === 'both' ? 'with-sep' : ''}`}>
              {view === 'both' && <div className="id-label">🇮🇩 Terjemahan</div>}
              {id.map((p, i) => <p key={i}>{p}</p>)}
            </div>
          ) : (
            (view !== 'both') && <div className="txt id"><p className="pending">belum diterjemahkan — menunggu antrean</p></div>
          )
        )}

        <footer className="foot">
          <span className="stat">❤ {nf(tweet.favorite_count)}</span>
          <span className="stat">💬 {nf(tweet.conversation_count)}</span>
          {tweet.media?.length > 0 && <span className="stat">🖼 {tweet.media.length}</span>}
          <a className="open" href={tweet.url} target="_blank" rel="noopener noreferrer">Buka di X ↗</a>
        </footer>
      </div>
    </article>
  )
}
