import { Component, useEffect, useRef, useState, type FormEvent, type PointerEvent, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import { ArrowUp, FileText, Grip, Loader2, X } from 'lucide-react'
import { streamChat } from './api'
import type { Source } from './types'

type Entry = { role: 'user' | 'assistant'; text: string; sources?: Source[]; pending?: boolean }

export class DocumentChatBoundary extends Component<{ children: ReactNode; onClose: () => void }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error) { console.error('Document chat failed', error) }
  render() {
    if (this.state.failed) return <div className="document-chat document-chat-fallback" role="alert">
      <p>The document chat ran into an error.</p><button onClick={this.props.onClose}>Close chat</button>
    </div>
    return this.props.children
  }
}

export default function DocumentChat({ documentId, filename, demo, onClose, onSignIn, onSource }: {
  documentId: string; filename: string; demo: boolean; onClose: () => void; onSignIn: () => void;
  onSource: (id: number) => void
}) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [draft, setDraft] = useState('')
  const [conversationId, setConversationId] = useState<number>()
  const [busy, setBusy] = useState(false)
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const panel = useRef<HTMLDivElement>(null)
  const messagesPanel = useRef<HTMLDivElement>(null)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    const current = messagesPanel.current
    if (current) current.scrollTop = current.scrollHeight
  }, [entries])

  function startDrag(event: PointerEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest('button')) return
    const box = panel.current?.getBoundingClientRect()
    if (!box) return
    event.preventDefault()
    const offsetX = event.clientX - box.left, offsetY = event.clientY - box.top
    const move = (next: globalThis.PointerEvent) => setPosition({
      x: Math.max(8, Math.min(window.innerWidth - box.width - 8, next.clientX - offsetX)),
      y: Math.max(8, Math.min(window.innerHeight - box.height - 8, next.clientY - offsetY)),
    })
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop) }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
  }

  async function ask(event: FormEvent) {
    event.preventDefault()
    const query = draft.trim()
    if (!query || busy) return
    if (demo) { onSignIn(); return }
    setDraft('')
    setBusy(true)
    setEntries(previous => [...previous, { role: 'user', text: query }, { role: 'assistant', text: '', pending: true }])
    const abort = new AbortController()
    controller.current = abort
    try {
      await streamChat(query, conversationId, abort.signal, {
        conversation: setConversationId,
        text: text => setEntries(previous => previous.map((entry, index) => index === previous.length - 1 ? { ...entry, text: entry.text + text } : entry)),
        sources: sources => setEntries(previous => previous.map((entry, index) => index === previous.length - 1 ? { ...entry, sources } : entry)),
      }, documentId)
      setEntries(previous => previous.map((entry, index) => index === previous.length - 1 ? { ...entry, pending: false } : entry))
    } catch (error) {
      const message = error instanceof Error ? error.message : 'The answer could not be completed.'
      setEntries(previous => previous.map((entry, index) => index === previous.length - 1 ? { ...entry, text: entry.text || message, pending: false } : entry))
    } finally { controller.current = null; setBusy(false) }
  }

  return <div ref={panel} className="document-chat" role="dialog" aria-label={`Ask about ${filename}`}
    style={position ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto' } : undefined}>
    <header className="document-chat-head" onPointerDown={startDrag}>
      <div><Grip size={16} /><span><strong>Ask about this document</strong><small title={filename}>{filename}</small></span></div>
      <button aria-label="Close document chat" onClick={onClose}><X size={18} /></button>
    </header>
    <div ref={messagesPanel} className="document-chat-messages">
      {!entries.length && <div className="document-chat-empty"><FileText size={24} /><p>Questions here search only this document.</p>{demo && <p>Sign in to ask about your own files.</p>}</div>}
      {entries.map((entry, index) => <div key={index} className={`document-chat-entry ${entry.role}`}>
        {entry.role === 'user' ? <p>{entry.text}</p> : <><ReactMarkdown components={{ a: ({ href, children }) => {
          const match = href?.match(/^#source-(\d+)$/)
          return match ? <button className="inline-citation" onClick={() => onSource(Number(match[1]))}>{children}</button> : <a href={href} target="_blank" rel="noreferrer">{children}</a>
        } }}>{entry.text.replace(/(?:\[doc:|【(?:doc:)?)(\d+)(?:\]|】)/g, '[$1](#source-$1)')}</ReactMarkdown>
          {entry.pending && <Loader2 className="spin" size={15} />}
          {!!entry.sources?.length && <div className="document-chat-sources">{entry.sources.map(source => <button key={source.document_id} onClick={() => onSource(source.document_id)}>{source.filename}{source.page_number ? ` · p. ${source.page_number}` : ''}</button>)}</div>}</>}
      </div>)}
    </div>
    <form onSubmit={ask} className="document-chat-form">
      <input aria-label="Question about this document" placeholder="Ask about this document…" value={draft} onChange={event => setDraft(event.target.value)} />
      <button aria-label="Send document question" disabled={!draft.trim() || busy}>{busy ? <Loader2 className="spin" size={17} /> : <ArrowUp size={18} />}</button>
    </form>
  </div>
}
