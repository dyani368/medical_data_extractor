import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, ArrowDownToLine, ArrowLeft, BookOpen, ChevronLeft, ChevronRight, FileText, Image, Layers3, Loader2, Table2 } from 'lucide-react'
import { requestBlob } from './api'
import type { Chunk, DocumentDetail, Extraction } from './types'

type WorkspaceProps = {
  document: DocumentDetail
  extraction: Extraction | null
  loading: boolean
  demo: boolean
  onBack: () => void
  onSource: (id: number) => void
  onAsk: () => void
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

export default function DocumentWorkspace({ document, extraction, loading, demo, onBack, onSource, onAsk }: WorkspaceProps) {
  const [tab, setTab] = useState<'parsed' | 'extracted' | 'indexed'>('parsed')
  const [page, setPage] = useState(1)
  const [activeChunkId, setActiveChunkId] = useState<number | null>(null)
  const [pageUrl, setPageUrl] = useState<string | null>(null)
  const [sourceState, setSourceState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [downloadError, setDownloadError] = useState('')
  const pages = useMemo(() => Math.max(document.page_count || 1, ...document.chunks.map(chunk => chunk.page_number || 1)), [document.page_count, document.chunks])
  const currentChunks = document.chunks.filter(chunk => !chunk.page_number || chunk.page_number === page)
  const currentExtracted = extraction?.items.filter(item => !item.page_number || item.page_number === page) || []
  const pageSize = document.pages?.find(item => item.page_number === page)
  const regions = pageSize ? Array.from(new Map(currentChunks.filter(chunk =>
    chunk.page_number === page && chunk.bbox?.length === 4 && chunk.bbox.every(Number.isFinite)
  ).map(chunk => [`${chunk.element_type}:${chunk.bbox!.map(value => Math.round(value)).join(',')}`, chunk])).values()) : []
  const figures = document.chunks.filter(chunk => chunk.element_type === 'image').length
  const tables = document.chunks.filter(chunk => chunk.element_type === 'table').length

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
    setPage(1)
    setTab('parsed')
  }, [document.document_id])

  useEffect(() => {
    setPageUrl(null)
    if (!document.filename.toLowerCase().endsWith('.pdf')) {
      setSourceState('unavailable')
      return
    }
    let active = true
    let objectUrl: string | undefined
    setSourceState('loading')
    const sampleName = document.document_id === 'demo-cardio' ? 'cardiovascular-followup'
      : document.document_id === 'demo-adverse' ? 'adverse-event-report' : null
    const path = demo && sampleName
      ? `/samples/${sampleName}/pages/${page}/preview`
      : `/documents/${document.document_id}/pages/${page}/preview`
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
      <button className="review-back" onClick={onBack}><ArrowLeft size={17} /> Documents</button>
      <span className="review-divider" />
      <div className="review-title"><FileText size={18} /><div><h1>{document.filename}</h1><span>{document.chunks.length} indexed passages · {pages} {pages === 1 ? 'page' : 'pages'}</span></div></div>
      <button className="button primary review-ask" onClick={onAsk}>Ask across records <ChevronRight size={16} /></button>
    </header>
    <div className="review-flow" aria-label="Document processing stages">
      <span><b>1</b> Source</span><ChevronRight size={14} /><span><b>2</b> Parse</span><ChevronRight size={14} /><span><b>3</b> Extract</span><ChevronRight size={14} /><span><b>4</b> Index</span><ChevronRight size={14} /><span><b>5</b> Ask</span>
    </div>
    <div className="review-columns">
      <section className="review-original" aria-label="Original document">
        <div className="review-pane-head"><div><span className="pane-kicker">SOURCE DOCUMENT</span><h2>Original file</h2></div>{sourceState === 'ready' && !demo ? <button className="pane-download" onClick={() => void downloadOriginal()}><ArrowDownToLine size={15} /> Download PDF</button> : <span className="pane-aside">Your uploaded record</span>}</div>
        <div className="page-controls"><span>Page {page} of {pages}</span><div><button aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(value => value - 1)}><ChevronLeft size={18} /></button><button aria-label="Next page" disabled={page >= pages} onClick={() => setPage(value => value + 1)}><ChevronRight size={18} /></button></div></div>
        {downloadError && <p className="review-download-error" role="alert">{downloadError}</p>}
        <div className="pdf-stage">
          {sourceState === 'loading' ? <div className="pdf-empty"><Loader2 className="spin" size={24} /><p>Loading the original PDF…</p></div>
            : pageUrl ? <div className="page-image-wrap"><img className="page-image" src={pageUrl} alt={`${document.filename}, page ${page}`} />{regions.map(chunk => {
              const [x0, y0, x1, y1] = chunk.bbox!
              const left = Math.max(0, Math.min(100, x0 / pageSize!.width * 100))
              const top = Math.max(0, Math.min(100, y0 / pageSize!.height * 100))
              const right = Math.max(0, Math.min(100, x1 / pageSize!.width * 100))
              const bottom = Math.max(0, Math.min(100, y1 / pageSize!.height * 100))
              return <button key={chunk.id} className={`page-region ${chunk.element_type || 'text'} ${activeChunkId === chunk.id ? 'active' : ''}`} style={{ left: `${left}%`, top: `${top}%`, width: `${Math.max(0.5, right - left)}%`, height: `${Math.max(0.5, bottom - top)}%` }} aria-label={`Show ${elementLabel(chunk.element_type)} passage ${(chunk.chunk_index ?? 0) + 1}`} title={`${elementLabel(chunk.element_type)} · passage ${(chunk.chunk_index ?? 0) + 1}`} onClick={() => { setTab('parsed'); setActiveChunkId(chunk.id); window.document.getElementById(`evidence-${chunk.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }} />
            })}</div>
              : <div className="pdf-empty"><FileText size={36} /><h3>Original preview unavailable</h3><p>{demo ? 'The saved example does not include a PDF preview.' : 'This is an earlier upload or a text file. Its indexed passages remain available on the right.'}</p></div>}
        </div>
      </section>
      <section className="review-results" aria-label="Document processing results">
        <div className="review-pane-head"><div><span className="pane-kicker">PROCESSING RESULTS</span><h2>Understand this record</h2></div><span className="pane-aside">{tables} tables · {figures} figures</span></div>
        <div className="review-tabs" role="tablist" aria-label="Document views">
          <button role="tab" aria-selected={tab === 'parsed'} className={tab === 'parsed' ? 'active' : ''} onClick={() => setTab('parsed')}><Layers3 size={16} /> Parsed content</button>
          <button role="tab" aria-selected={tab === 'extracted'} className={tab === 'extracted' ? 'active' : ''} onClick={() => setTab('extracted')}><Table2 size={16} /> Extraction</button>
          <button role="tab" aria-selected={tab === 'indexed'} className={tab === 'indexed' ? 'active' : ''} onClick={() => setTab('indexed')}><BookOpen size={16} /> Search passages</button>
        </div>
        <div className="review-content">
          {loading ? <div className="loading-state"><Loader2 className="spin" size={20} /> Loading document results…</div> : tab === 'parsed' ? <>
            <p className="review-intro">Text, tables, and figures are kept as distinct evidence, with their page and section context.</p>
            {currentChunks.length ? currentChunks.map(chunk => <article className={`evidence-block ${activeChunkId === chunk.id ? 'active' : ''}`} id={`evidence-${chunk.id}`} key={chunk.id} onMouseEnter={() => setActiveChunkId(chunk.id)}>
              <div className="evidence-head"><span className={`evidence-kind ${chunk.element_type || 'text'}`}>{chunk.element_type === 'image' ? <Image size={15} /> : chunk.element_type === 'table' ? <Table2 size={15} /> : <FileText size={15} />}{elementLabel(chunk.element_type)}</span><span>Page {chunk.page_number || page} · Passage {(chunk.chunk_index ?? 0) + 1}</span></div>
              {chunk.section_title && <h3>{chunk.section_title}</h3>}
              {chunk.element_type === 'table' ? <TableEvidence content={chunk.content} /> : chunk.element_type === 'image' ? <FigureEvidence chunk={chunk} /> : <p>{chunk.content}</p>}<button onClick={() => onSource(chunk.id)}>Open source evidence <ChevronRight size={14} /></button>
            </article>) : <div className="review-empty">No indexed content on this page. Try another page.</div>}
          </> : tab === 'extracted' ? <>
            <p className="review-intro">Structured findings generated from each passage. Review the original alongside any model-produced result.</p>
            {currentExtracted.length ? currentExtracted.map(item => <article className="finding-block" key={item.document_id}>
              <div className="evidence-head"><span>Page {item.page_number || page} · Passage {(item.chunk_index ?? 0) + 1}</span><span className={`finding-status ${item.status}`}>{item.status === 'succeeded' ? 'Extracted' : item.status === 'failed' ? 'Needs review' : 'Pending'}</span></div>
              {item.status === 'failed' ? <p className="finding-error"><AlertCircle size={16} /> Extraction failed{item.error_type ? `: ${item.error_type}` : '.'} The parsed passage is still available.</p> : item.result ? <><h3>{item.result.category}</h3><p>{item.result.summary}</p>{Object.entries(item.result.key_entities).length > 0 && <dl>{Object.entries(item.result.key_entities).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}</> : <p>Extraction is pending.</p>}
            </article>) : <div className="review-empty">No extraction results on this page.</div>}
          </> : <>
            <p className="review-intro">These are the passages available to search and cite. Open one to check the exact evidence.</p>
            {currentChunks.length ? currentChunks.map(chunk => <button className="indexed-row" key={chunk.id} onClick={() => onSource(chunk.id)}><span><strong>{elementLabel(chunk.element_type)} · Page {chunk.page_number || page}</strong><small>{chunk.section_title || `Passage ${(chunk.chunk_index ?? 0) + 1}`}</small></span><ChevronRight size={17} /></button>) : <div className="review-empty">No indexed passages on this page.</div>}
          </>}
        </div>
      </section>
    </div>
  </div>
}
