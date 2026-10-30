import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ArrowDownToLine, ArrowLeft, ChevronLeft, ChevronRight, FileText, Image, Loader2, Table2 } from 'lucide-react'
import { requestBlob } from './api'
import DocumentChat, { DocumentChatBoundary } from './DocumentChat'
import type { Chunk, DocumentDetail, Extraction } from './types'

type WorkspaceProps = {
  document: DocumentDetail
  extraction: Extraction | null
  loading: boolean
  demo: boolean
  focusedChunk?: number | null
  focusedPage?: number | null
  onBack: () => void
  backLabel: string
  onSource: (id: number) => void
  onSignIn: () => void
}

const elementLabel = (value?: string) => value === 'image' ? 'Figure' : value === 'table' ? 'Table' : 'Text'

function TableEvidence({ content }: { content: string }) {
  const lines = content.split('\n')
  const first = lines.findIndex(line => line.trim().startsWith('|'))
  const cells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(value => value.trim())
  if (first < 0 || lines.length < first + 2 || !/^\s*\|?[\s|:-]+\|?\s*$/.test(lines[first + 1])) {
    return <p>{content}</p>
  }
  const header = cells(lines[first])
  const body = lines.slice(first + 2).filter(line => line.trim().startsWith('|')).map(cells)
  return <>{first > 0 && <p>{lines.slice(0, first).join('\n')}</p>}<div className="table-scroll"><table><thead><tr>{header.map((cell, index) => <th key={index}>{cell}</th>)}</tr></thead><tbody>{body.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div></>
}

function FigureEvidence({ chunk }: { chunk: Chunk }) {
  const [visualUrl, setVisualUrl] = useState<string | null>(null)
  const path = chunk.visuals?.[0]?.url
  useEffect(() => {
    if (!path) return
    let active = true
    let url: string | undefined
    requestBlob(path).then(blob => {
      if (!active) return
      url = URL.createObjectURL(blob)
      setVisualUrl(url)
    }).catch(() => { if (active) setVisualUrl(null) })
    return () => { active = false; if (url) URL.revokeObjectURL(url) }
  }, [path])
  return <>{visualUrl && <img className="evidence-figure" src={visualUrl} alt={`Extracted figure from page ${chunk.page_number || 1}`} />}<p>{chunk.content}</p></>
}

const readable = (value: unknown) => Array.isArray(value) ? value.join(', ') : value && typeof value === 'object' ? Object.entries(value).map(([key, item]) => `${key.replace(/_/g, ' ')}: ${String(item)}`).join(' · ') : String(value ?? '')
const heading = (chunk: Chunk) => {
  const title = chunk.section_title?.trim() || chunk.content.split('\n').find(line => line.trim())?.trim() || ''
  if (!title) return chunk.element_type === 'table' ? 'Table' : chunk.element_type === 'image' ? 'Figure' : 'Text'
  return title.length > 84 ? `${title.slice(0, 81).trimEnd()}…` : title
}

export default function DocumentWorkspace({ document, extraction, loading, demo, focusedChunk, focusedPage, backLabel, onBack, onSource, onSignIn }: WorkspaceProps) {
  const [chatOpen, setChatOpen] = useState(false)
  const [tab, setTab] = useState<'findings' | 'source'>('findings')
  const [page, setPage] = useState(1)
  const [activeChunkId, setActiveChunkId] = useState<number | null>(null)
  const [pageUrl, setPageUrl] = useState<string | null>(null)
  const [sourceState, setSourceState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [downloadError, setDownloadError] = useState('')
  const scrollFrame = useRef<number | null>(null)
  const pages = useMemo(() => Math.max(document.page_count || 1, ...document.chunks.map(chunk => chunk.page_number || 1)), [document.page_count, document.chunks])
  const currentChunks = document.chunks.filter(chunk => !chunk.page_number || chunk.page_number === page)
  const currentExtracted = extraction?.items.filter(item => !item.page_number || item.page_number === page) || []
  const pageSize = document.pages?.find(item => item.page_number === page)
  const regions = pageSize ? Array.from(new Map(currentChunks.filter(chunk =>
    chunk.page_number === page && chunk.bbox?.length === 4 && chunk.bbox.every(Number.isFinite)
  ).map(chunk => [`${chunk.element_type}:${chunk.bbox!.map(value => Math.round(value)).join(',')}`, chunk])).values()) : []
  const extractionByChunk = new Map(currentExtracted.map(item => [item.document_id, item]))

  function locate(chunk: Chunk) {
    setActiveChunkId(chunk.id)
    window.document.getElementById(`region-${chunk.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  function followPageScroll(event: React.UIEvent<HTMLDivElement>) {
    if (!regions.length || scrollFrame.current != null) return
    const stage = event.currentTarget
    scrollFrame.current = requestAnimationFrame(() => {
      scrollFrame.current = null
      const center = stage.getBoundingClientRect().top + stage.clientHeight * 0.48
      const closest = regions.map(chunk => ({ chunk, element: window.document.getElementById(`region-${chunk.id}`) }))
        .filter((entry): entry is { chunk: Chunk; element: HTMLElement } => !!entry.element)
        .sort((a, b) => Math.abs((a.element.getBoundingClientRect().top + a.element.getBoundingClientRect().bottom) / 2 - center) - Math.abs((b.element.getBoundingClientRect().top + b.element.getBoundingClientRect().bottom) / 2 - center))[0]
      if (closest && closest.chunk.id !== activeChunkId) {
        setActiveChunkId(closest.chunk.id)
        window.document.getElementById(`evidence-${closest.chunk.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    })
  }

  useEffect(() => () => { if (scrollFrame.current != null) cancelAnimationFrame(scrollFrame.current) }, [])

  async function downloadOriginal() {
    setDownloadError('')
    try {
      const blob = await requestBlob(`/documents/${document.document_id}/source`)
      const url = URL.createObjectURL(blob)
      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = document.filename
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setDownloadError('Could not download the original PDF. Please try again.') }
  }

  useEffect(() => {
    setChatOpen(false)
    setPage(focusedPage || 1)
    setTab(document.document_id.startsWith('legacy-') ? 'source' : 'findings')
    setActiveChunkId(focusedChunk || null)
  }, [document.document_id, focusedChunk, focusedPage])

  useEffect(() => { if (focusedChunk && !loading) window.setTimeout(() => window.document.getElementById(`evidence-${focusedChunk}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 120) }, [focusedChunk, loading, page])

  useEffect(() => {
    setPageUrl(null)
    if (document.document_id.startsWith('legacy-') || !document.filename.toLowerCase().endsWith('.pdf')) {
      setSourceState('unavailable')
      return
    }
    let active = true
    let objectUrl: string | undefined
    setSourceState('loading')
    const sampleName = document.document_id === 'demo-cardio' ? 'cardiovascular-followup'
      : document.document_id === 'demo-adverse' ? 'adverse-event-report'
      : document.document_id === 'demo-project' ? 'project-status' : null
    if (demo && sampleName) {
      setPageUrl(`/samples/${sampleName}-page-${page}.png`)
      setSourceState('ready')
      return
    }
    const path = `/documents/${document.document_id}/pages/${page}/preview`
    requestBlob(path).then(blob => {
      if (!active) return
      objectUrl = URL.createObjectURL(blob)
      setPageUrl(objectUrl)
      setSourceState('ready')
    }).catch(() => {
      if (active) setSourceState('unavailable')
    })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [document.document_id, document.filename, demo, page])

  return <div className="document-workspace">
    <header className="review-header">
      <button className="review-back" onClick={onBack}><ArrowLeft size={17} /> {backLabel}</button>
      <span className="review-divider" />
      <div className="review-title"><FileText size={18} /><div><h1>{document.filename}</h1><span>{pages} {pages === 1 ? 'page' : 'pages'}</span></div></div>
      {demo && <button className="review-signin" onClick={onSignIn}>Sign in</button>}
      <button className="button primary review-ask" onClick={() => setChatOpen(true)}>Ask this document <ChevronRight size={16} /></button>
    </header>
    <div className="review-columns">
      <section className="review-original" aria-label="Original document">
        <div className="review-pane-head"><h2>Original document</h2>{sourceState === 'ready' && !demo && <button className="pane-download" onClick={() => void downloadOriginal()}><ArrowDownToLine size={15} /> Download</button>}</div>
        <div className="page-controls"><span>Page <strong>{page}</strong> / {pages}</span><div><button aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={18} /></button><button aria-label="Next page" disabled={page >= pages} onClick={() => setPage(value => value + 1)}><ChevronRight size={18} /></button></div></div>
        {downloadError && <p className="review-download-error" role="alert">{downloadError}</p>}
        <div className="pdf-stage" onScroll={followPageScroll}>
          {sourceState === 'loading' ? <div className="pdf-empty"><Loader2 className="spin" size={24} /><p>Loading the original PDF…</p></div>
            : pageUrl ? <div className="page-image-wrap"><img className="page-image" src={pageUrl} alt={`${document.filename}, page ${page}`} />{regions.map(chunk => {
              const [x0, y0, x1, y1] = chunk.bbox!
              const left = Math.max(0, Math.min(100, x0 / pageSize!.width * 100))
              const top = Math.max(0, Math.min(100, y0 / pageSize!.height * 100))
              const right = Math.max(0, Math.min(100, x1 / pageSize!.width * 100))
              const bottom = Math.max(0, Math.min(100, y1 / pageSize!.height * 100))
              return <button id={`region-${chunk.id}`} key={chunk.id} className={`page-region ${chunk.element_type || 'text'} ${activeChunkId === chunk.id ? 'active' : ''}`} style={{ left: `${left}%`, top: `${top}%`, width: `${Math.max(0.5, right - left)}%`, height: `${Math.max(0.5, bottom - top)}%` }} aria-label={`Show ${heading(chunk)}`} title={heading(chunk)} onMouseEnter={() => setActiveChunkId(chunk.id)} onClick={() => { setTab('findings'); setActiveChunkId(chunk.id); window.document.getElementById(`evidence-${chunk.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} />
            })}</div>
              : <div className="pdf-empty"><FileText size={36} /><h3>Original preview unavailable</h3><p>{demo ? 'This sample does not include a PDF preview.' : 'The source file is unavailable. The indexed content is shown on the right.'}</p></div>}
        </div>
      </section>
      <section className="review-results" aria-label="Document processing results">
        <div className="review-pane-head"><h2>Page {page} details</h2></div>
        <div className="review-tabs" role="tablist" aria-label="Document views">
          <button role="tab" aria-selected={tab === 'findings'} className={tab === 'findings' ? 'active' : ''} onClick={() => setTab('findings')}>AI findings</button>
          <button role="tab" aria-selected={tab === 'source'} className={tab === 'source' ? 'active' : ''} onClick={() => setTab('source')}>Parsed content</button>
        </div>
        <div className="review-content">
          {loading ? <div className="loading-state"><Loader2 className="spin" size={20} /> Loading document results…</div> : currentChunks.length ? currentChunks.map(chunk => {
            const item = extractionByChunk.get(chunk.id)
            const values = Object.entries(item?.result?.key_entities || {}).filter(([, value]) => value != null && String(value).trim())
            return <article className={`evidence-block ${activeChunkId === chunk.id ? 'active' : ''}`} id={`evidence-${chunk.id}`} key={chunk.id} onMouseEnter={() => setActiveChunkId(chunk.id)} onFocus={() => setActiveChunkId(chunk.id)}>
              <div className="evidence-head"><span className={`evidence-kind ${chunk.element_type || 'text'}`}>{chunk.element_type === 'image' ? <Image size={15} /> : chunk.element_type === 'table' ? <Table2 size={15} /> : <FileText size={15} />}{elementLabel(chunk.element_type)}</span>{item?.status === 'failed' && <span className="finding-status failed">Review needed</span>}</div>
              <h3>{heading(chunk)}</h3>
              {tab === 'findings' ? item?.status === 'failed' ? <p className="finding-error"><AlertCircle size={16} /> Extraction unavailable. See parsed content.</p> : item?.result ? <>{values.length > 0 && <dl className="finding-values">{values.map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{readable(value)}</dd></div>)}</dl>}{item.result.summary && item.result.summary.trim() !== chunk.content.trim() && !/^insufficient context\b/i.test(item.result.summary.trim()) && <p className="finding-summary">{item.result.summary}</p>}{!values.length && (!item.result.summary || /^insufficient context\b/i.test(item.result.summary.trim())) && <p>No useful findings extracted. Review parsed content.</p>}</> : <p>AI findings are not available for this part. See parsed content.</p>
                : chunk.element_type === 'table' ? <TableEvidence content={chunk.content} /> : chunk.element_type === 'image' ? <FigureEvidence chunk={chunk} /> : <div className="parsed-text">{chunk.content.split(/\n\s*\n/).filter(Boolean).map((part, i) => <p key={i}>{part}</p>)}</div>}
              <div className="evidence-foot"><button disabled={!chunk.bbox} onClick={() => locate(chunk)}>{chunk.bbox ? 'Locate on page' : 'Page location unavailable'}</button><button onClick={() => setTab(tab === 'findings' ? 'source' : 'findings')}>{tab === 'findings' ? 'View parsed content' : 'View AI findings'} <ChevronRight size={14} /></button></div>
            </article>
          }) : <div className="review-empty">No content on this page.</div>}
        </div>
      </section>
    </div>
    {chatOpen && <DocumentChatBoundary key={document.document_id} onClose={() => setChatOpen(false)}><DocumentChat documentId={document.document_id} filename={document.filename} demo={demo} onClose={() => setChatOpen(false)} onSignIn={onSignIn} onSource={id => { setChatOpen(false); onSource(id) }} /></DocumentChatBoundary>}
  </div>
}
