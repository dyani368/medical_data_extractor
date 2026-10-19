import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import { ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUp, BookOpen, Check, CheckCircle2, ChevronRight, CircleHelp, Clock3, FileCheck2, FileSearch, FileText, FolderOpen, Layers3, Loader2, LogOut, Menu, MessageSquare, Plus, Search, ShieldCheck, Sparkles, Square, Trash2, UploadCloud, X, AlertCircle, ExternalLink } from 'lucide-react'
import { ApiError, newKey, request, requestBlob, setAccessToken, streamChat } from './api'
import type { Conversation, DocumentDetail, DocumentSummary, Extraction, Job, Message, Passage, Source, User } from './types'
import { demoDetails, demoDocuments, demoExtractions, demoMessages, demoPassage } from './demo'
import DocumentWorkspace from './DocumentWorkspace'

const cleanName = (name: string) => name.replace(/_chunk_\d+$/, '').replace(/_/g, ' ')
const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.'
const terminal = (status: string) => ['completed', 'completed_with_errors', 'failed', 'deleted'].includes(status)

function Brand({ dark = false }: { dark?: boolean }) {
  return <div className={`brand ${dark ? 'brand-light' : ''}`}><span className="brand-mark"><FileSearch size={23} strokeWidth={1.7} /></span><span>clarity<span className="brand-dot">.</span></span></div>
}

function AuthScreen({ onLogin, onDemo, message }: { onLogin: (token: string, user: User) => void; onDemo: () => void; message: string }) {
  const [register, setRegister] = useState(false)
  const [username, setUsername] = useState(''), [email, setEmail] = useState(''), [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false), [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError('')
    try {
      if (register) await request('/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, email, password }) })
      const auth = await request<{ access_token: string }>('/token', { method: 'POST', body: new URLSearchParams({ username, password }) })
      setAccessToken(auth.access_token)
      const user = await request<User>('/me')
      onLogin(auth.access_token, user)
    } catch (error) { setError(errorText(error)) } finally { setLoading(false) }
  }
  return <div className="auth-page">
    <section className="auth-story">
      <Brand />
      <div className="auth-story-content"><span className="eyebrow"><span className="mini-line" /> CLINICAL DOCUMENT INTELLIGENCE</span>
        <h1>Your documents.<br />Clearer answers.</h1>
        <p>A focused workspace to understand clinical records, explore extracted findings, and follow every answer back to its evidence.</p>
        <div className="preview-card"><div className="preview-header"><span className="file-icon"><FileText size={21} /></span><div><strong>Cardiovascular follow-up</strong><span>Document insight · page 1</span></div><span className="tiny-check"><Check size={14} /></span></div>
          <div className="preview-answer">The record notes <strong>mild dizziness</strong> and a blood pressure of <strong>160/95 mmHg.</strong><span className="preview-cite">1</span></div>
          <div className="preview-footer"><BookOpen size={14} /> Traceable to a source passage <ArrowRight size={14} /></div>
        </div>
        <div className="auth-features"><span><FileCheck2 size={16} /> Structured extraction</span><span><ShieldCheck size={16} /> Account-scoped records</span><span><MessageSquare size={16} /> Contextual answers</span></div>
      </div><div className="auth-story-footer">Built to make the evidence easy to see.<span>01 / 03</span></div>
    </section>
    <section className="auth-form-wrap"><div className="auth-form">
      <div className="auth-small-brand"><Brand /></div><span className="eyebrow">CLINICAL DOCUMENT WORKSPACE</span><h2>{register ? 'Create your workspace.' : 'Understand every document.'}</h2><p>{register ? 'Create an account to review PDFs, extracted findings, and source-grounded answers.' : 'Clarity processes PDF records, shows what it extracted, and answers questions with source passages. Sign in to continue.'}</p>
      <div className="auth-toggle"><button type="button" className={!register ? 'active' : ''} onClick={() => { setRegister(false); setError('') }}>Sign in</button><button type="button" className={register ? 'active' : ''} onClick={() => { setRegister(true); setError('') }}>Create account</button></div>
      <form onSubmit={submit}><label>Username<input autoComplete="username" minLength={register ? 3 : 1} maxLength={50} required value={username} onChange={event => setUsername(event.target.value)} placeholder="Your username" /></label>
        {register && <label>Email address<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} placeholder="you@example.com" /></label>}
        <label>Password<input type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 12 : 1} required value={password} onChange={event => setPassword(event.target.value)} placeholder={register ? 'At least 12 characters' : 'Your password'} /></label>
        {(error || message) && <div className="error-box" role="alert"><AlertCircle size={17} /><span>{error || message}</span></div>}
        <button className="button primary auth-submit" disabled={loading}>{loading ? <Loader2 className="spin" size={17} /> : null}{register ? 'Create workspace' : 'Sign in'}<ArrowRight size={17} /></button>
      </form><div className="or-divider"><span>or see how it works</span></div><button className="button outline demo-button" onClick={onDemo}><FileText size={17} />Explore sample records</button><p className="auth-note">Read-only sample records. Sign in to process your own files.</p>
    </div><div className="auth-footer"><span>Clarity · Clinical Document Intelligence</span><a href="https://github.com/dyani368/medical_data_extractor" target="_blank" rel="noreferrer">View project <ExternalLink size={12} /></a></div></section>
  </div>
}

function Status({ status }: { status: string }) {
  const good = ['succeeded', 'completed'].includes(status), warning = ['partial', 'completed_with_errors'].includes(status), failed = status === 'failed'
  return <span className={`status ${good ? 'good' : warning ? 'warning' : failed ? 'bad' : 'neutral'}`}><span />{good ? 'Ready' : warning ? 'Needs review' : failed ? 'Failed' : 'Processing'}</span>
}

function Answer({ content, sources = [], onSource }: { content: string; sources?: Source[]; onSource: (id: number) => void }) {
  const ids: number[] = []
  const markdown = content.replace(/(?:\[doc:|【(?:doc:)?)(\d+)(?:\]|】)/g, (_, value) => {
    const id = Number(value); if (!ids.includes(id)) ids.push(id)
    return ` [${ids.indexOf(id) + 1}](#source-${id})`
  })
  return <><div className="answer-markdown"><ReactMarkdown components={{ a: ({ href, children }) => {
    const match = href?.match(/^#source-(\d+)$/)
    return match ? <button className="inline-citation" aria-label={`Open source ${children}`} onClick={() => onSource(Number(match[1]))}>{children}</button> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
  } }}>{markdown}</ReactMarkdown></div>{sources.length > 0 && <div className="answer-sources"><span className="source-label"><BookOpen size={13} /> SOURCES</span>{sources.map(source => <button key={source.document_id} onClick={() => onSource(source.document_id)} className="source-chip"><FileText size={14} /><span>{cleanName(source.filename)}</span>{source.page_number ? <small>p. {source.page_number}</small> : null}<ChevronRight size={13} /></button>)}</div>}</>
}

function Workspace({ user, demo, onLogout }: { user: User; demo: boolean; onLogout: () => void }) {
  const [view, setView] = useState<'documents' | 'chat'>('documents'), [mobileNav, setMobileNav] = useState(false)
  const [documents, setDocuments] = useState<DocumentSummary[]>(demo ? demoDocuments : []), [documentTotal, setDocumentTotal] = useState(demo ? demoDocuments.length : 0)
  const [docsLoading, setDocsLoading] = useState(!demo), [docsError, setDocsError] = useState(''), [filter, setFilter] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([]), [conversationId, setConversationId] = useState<number>()
  const [conversationLoading, setConversationLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>(demo ? demoMessages : []), [draft, setDraft] = useState(''), [busy, setBusy] = useState(false)
  const [selectedDocument, setSelectedDocument] = useState<DocumentDetail | null>(null), [extraction, setExtraction] = useState<Extraction | null>(null), [panelLoading, setPanelLoading] = useState(false), [panelTab, setPanelTab] = useState<'extraction' | 'passages'>('extraction')
  const [source, setSource] = useState<Passage | null>(null), [sourceLoading, setSourceLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DocumentSummary | null>(null), [deleting, setDeleting] = useState(false)
  const [guide, setGuide] = useState(false), [toast, setToast] = useState(''), [uploading, setUploading] = useState(false), [dragging, setDragging] = useState(false), [connected, setConnected] = useState(true)
  const jobStorageKey = `clarity.jobs.${user.id}`
  const [jobs, setJobs] = useState<Job[]>(() => { try { return demo ? [] : JSON.parse(sessionStorage.getItem(jobStorageKey) || '[]') } catch { return [] } })
  const jobsRef = useRef(jobs), fileInput = useRef<HTMLInputElement>(null), chatScroll = useRef<HTMLDivElement>(null), chatAbort = useRef<AbortController | null>(null), documentRequest = useRef(0), sourceRequest = useRef(0)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const uploadKeys = useRef(new Map<string, string>())
  const notify = useCallback((message: string) => { setToast(message); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 7000) }, [])
  const refreshDocuments = useCallback(async (append = false) => {
    if (demo) return
    setDocsLoading(true); setDocsError('')
    try { const data = await request<{ items: DocumentSummary[]; total: number }>(`/documents?limit=100&offset=${append ? documents.length : 0}`); setDocuments(previous => append ? [...previous, ...data.items] : data.items); setDocumentTotal(data.total); setConnected(true) }
    catch (error) { setDocsError(errorText(error)); setConnected(false) } finally { setDocsLoading(false) }
  }, [demo, documents.length])
  const refreshConversations = useCallback(async () => { if (!demo) { try { const data = await request<{ items: Conversation[] }>('/conversations?limit=100'); setConversations(data.items) } catch { /* The document view exposes connection errors. */ } } }, [demo])
  useEffect(() => { void refreshDocuments(); void refreshConversations() }, [demo]) // Refresh once per workspace; later refreshes are explicit.
  useEffect(() => { jobsRef.current = jobs; if (!demo) sessionStorage.setItem(jobStorageKey, JSON.stringify(jobs)) }, [jobs, demo, jobStorageKey])
  useEffect(() => {
    if (demo) return
    let canceled = false, polling = false
    const timer = setInterval(async () => {
      if (polling) return
      const active = jobsRef.current.filter(job => !terminal(job.status))
      if (!active.length) return
      polling = true
      await Promise.all(active.map(async job => {
        try { const data = await request<Omit<Job, 'filename' | 'job_id'>>(`/jobs/${job.job_id}`); if (canceled) return; setJobs(previous => previous.map(item => item.job_id === job.job_id ? { ...item, ...data, connectionError: false } : item)); if (terminal(data.status)) void refreshDocuments() }
        catch (error) { if (!canceled) setJobs(previous => previous.map(item => item.job_id === job.job_id ? error instanceof ApiError && error.status === 404 ? { ...item, status: 'failed', error: 'Job status expired or unavailable', connectionError: false } : { ...item, connectionError: true } : item)) }
      }))
      polling = false
    }, 2500)
    return () => { canceled = true; clearInterval(timer) }
  }, [demo, refreshDocuments])
  useEffect(() => () => { chatAbort.current?.abort(); clearTimeout(toastTimer.current) }, [])
  useEffect(() => { function escape(event: KeyboardEvent) { if (event.key === 'Escape') { sourceRequest.current++; documentRequest.current++; setSourceLoading(false); setPanelLoading(false); setSource(null); setSelectedDocument(null); setGuide(false); setDeleteTarget(null); setMobileNav(false) } } window.addEventListener('keydown', escape); return () => window.removeEventListener('keydown', escape) }, [])
  useEffect(() => () => source?.visuals?.forEach(visual => visual.object_url && URL.revokeObjectURL(visual.object_url)), [source])
  useEffect(() => {
    const dialog = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
      .find(element => window.getComputedStyle(element).display !== 'none')
    if (!dialog) return
    const previous = document.activeElement as HTMLElement | null
    const controls = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, textarea, [tabindex="0"]'))
    controls()[0]?.focus()
    function trap(event: KeyboardEvent) {
      if (event.key !== 'Tab') return
      const items = controls(), first = items[0], last = items.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    document.addEventListener('keydown', trap)
    return () => { document.removeEventListener('keydown', trap); previous?.focus() }
  }, [!!selectedDocument, !!source, sourceLoading, guide, !!deleteTarget])
  useEffect(() => { const element = chatScroll.current; if (element && view === 'chat' && (busy || messages.length <= 2)) element.scrollTop = element.scrollHeight }, [messages, view, busy])

  async function uploadFiles(files: FileList | File[] | null) {
    if (!files?.length) return
    if (demo) { onLogout(); return }
    setUploading(true)
    for (const file of Array.from(files)) {
      if (file.size > 20_000_000 || !/\.(pdf|txt)$/i.test(file.name)) { notify(`${file.name}: choose a PDF or TXT file no larger than 20 MB.`); continue }
      const form = new FormData(); form.append('file', file)
      const signature = `${file.name}:${file.size}:${file.lastModified}`
      const retryKey = uploadKeys.current.get(signature) || newKey()
      uploadKeys.current.set(signature, retryKey)
      try { const result = await request<{ job_id: string }>('/upload', { method: 'POST', body: form, headers: { 'Idempotency-Key': retryKey } }); uploadKeys.current.delete(signature); setJobs(previous => [{ job_id: result.job_id, filename: file.name, status: 'queued', progress: '0%' }, ...previous]); notify('Upload accepted. Your document is being processed.') }
      catch (error) { notify(`${file.name}: ${errorText(error)}`) }
    }
    setUploading(false); if (fileInput.current) fileInput.current.value = ''
  }
  async function inspectDocument(document: DocumentSummary) {
    const sequence = ++documentRequest.current; setSource(null); setSelectedDocument({ document_id: document.document_id, filename: document.filename, created_at: document.created_at, chunks: [] }); setExtraction(null); setPanelLoading(true); setPanelTab('extraction')
    try { const [detail, extracted] = demo ? [demoDetails[document.document_id], demoExtractions[document.document_id]] : await Promise.all([request<DocumentDetail>(`/documents/${document.document_id}`), request<Extraction>(`/documents/${document.document_id}/extraction`)]); if (sequence === documentRequest.current) { setSelectedDocument(detail); setExtraction(extracted) } }
    catch (error) { notify(errorText(error)); setSelectedDocument(null) } finally { if (sequence === documentRequest.current) setPanelLoading(false) }
  }
  async function inspectSource(id: number) {
    const sequence = ++sourceRequest.current; setSelectedDocument(null); setSource(null); setSourceLoading(true)
    try {
      let passage = demo ? demoPassage(id) : await request<Passage>(`/chunks/${id}`)
      if (!passage) throw new Error('Source passage is unavailable.')
      if (!demo && passage.visuals?.length) {
        const visuals = await Promise.all(passage.visuals.map(async visual => {
          const blob = await requestBlob(visual.url)
          return { ...visual, object_url: URL.createObjectURL(blob) }
        }))
        passage = { ...passage, visuals }
      }
      if (sequence === sourceRequest.current) setSource(passage)
      else passage.visuals?.forEach(visual => visual.object_url && URL.revokeObjectURL(visual.object_url))
    }
    catch (error) { notify(errorText(error)) } finally { if (sequence === sourceRequest.current) setSourceLoading(false) }
  }
  async function deleteDocument() {
    if (!deleteTarget) return; setDeleting(true)
    try { await request(`/documents/${deleteTarget.document_id}`, { method: 'DELETE' }); setDeleteTarget(null); setSelectedDocument(null); await refreshDocuments(); notify('Document and its extraction results deleted.') }
    catch (error) { notify(errorText(error)) } finally { setDeleting(false) }
  }
  function newChat() { chatAbort.current?.abort(); setBusy(false); setConversationId(undefined); setMessages(demo ? demoMessages : []); setDraft(''); setView('chat'); setMobileNav(false) }
  async function openConversation(conversation: Conversation) {
    chatAbort.current?.abort(); setBusy(false); setView('chat'); setMobileNav(false); setConversationLoading(true); setConversationId(conversation.conversation_id)
    try { const result = await request<{ messages: { id: number; role: 'user' | 'assistant'; content: string }[] }>(`/conversations/${conversation.conversation_id}`); setMessages(result.messages.map(message => ({ ...message, id: String(message.id) }))) }
    catch (error) { notify(errorText(error)); setMessages([]) } finally { setConversationLoading(false) }
  }
  async function sendQuestion(value: string) {
    const question = value.trim(); if (!question || busy || conversationLoading) return
    if (demo) { onLogout(); return }
    const id = newKey(), controller = new AbortController(); chatAbort.current = controller; setBusy(true); setDraft('')
    setMessages(previous => [...previous, { id: newKey(), role: 'user', content: question }, { id, role: 'assistant', content: '', sources: [], pending: true }])
    try {
      await streamChat(question, conversationId, controller.signal, {
        conversation: setConversationId,
        text: text => setMessages(previous => previous.map(message => message.id === id ? { ...message, content: message.content + text } : message)),
        sources: sources => setMessages(previous => previous.map(message => message.id === id ? { ...message, sources } : message)),
      })
      setMessages(previous => previous.map(message => message.id === id ? { ...message, pending: false } : message)); await refreshConversations()
    } catch (error) {
      const stopped = controller.signal.aborted
      setMessages(previous => previous.map(message => message.id === id ? { ...message, pending: false, interrupted: true, content: message.content || (stopped ? 'Generation stopped.' : errorText(error)) } : message))
      if (!stopped) notify(errorText(error))
    } finally { if (chatAbort.current === controller) { setBusy(false); chatAbort.current = null } }
  }

  const visibleDocuments = documents.filter(document => cleanName(document.filename).toLowerCase().includes(filter.toLowerCase()))
  const sidebar = <><Brand dark /><div className="workspace-label">DOCUMENT WORKSPACE</div><nav className="main-nav"><button className={view === 'documents' ? 'selected' : ''} onClick={() => { setView('documents'); setMobileNav(false) }}><FolderOpen size={19} />Document library<span className="nav-count">{documentTotal}</span></button><button className={view === 'chat' ? 'selected' : ''} onClick={() => { setView('chat'); setMobileNav(false) }}><MessageSquare size={19} />Ask Clarity<ArrowUp className="nav-arrow" size={15} /></button></nav>
    <div className="conversation-heading"><span>CONVERSATIONS</span><button aria-label="Start a new conversation" onClick={newChat}><Plus size={17} /></button></div><div className="conversation-nav">{demo ? <button className={view === 'chat' ? 'active' : ''} onClick={() => { setView('chat'); setMobileNav(false) }}><MessageSquare size={14} />Cardiovascular follow-up</button> : conversations.length ? conversations.map(conversation => <button key={conversation.conversation_id} className={conversationId === conversation.conversation_id && view === 'chat' ? 'active' : ''} onClick={() => void openConversation(conversation)} title={conversation.title}><MessageSquare size={14} /><span>{conversation.title || `Conversation ${conversation.conversation_id}`}</span></button>) : <p>Your conversations will<br />appear here.</p>}</div>
    <div className="sidebar-bottom"><div className="sidebar-tip"><BookOpen size={20} /><strong>Start with a sample.</strong><p>Explore a record, ask a question, and inspect the evidence.</p><button onClick={() => setGuide(true)}>Get sample documents <ArrowRight size={14} /></button></div><button className="sidebar-help" onClick={() => setGuide(true)}><CircleHelp size={16} />How Clarity works</button><div className="account-row"><span className="avatar">{demo ? 'D' : user.username.slice(0, 2).toUpperCase()}</span><div><strong>{demo ? 'Demo workspace' : user.username}</strong><span>{demo ? 'Sample records' : 'Personal workspace'}</span></div><button aria-label={demo ? 'Leave demo and sign in' : 'Sign out'} title={demo ? 'Sign in' : 'Sign out'} onClick={onLogout}><LogOut size={17} /></button></div></div></>

  return <div className={`workspace ${selectedDocument ? 'review-open' : ''}`}>
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}>{sidebar}</aside>{mobileNav && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    <main className="workspace-main">{selectedDocument ? <DocumentWorkspace document={selectedDocument} extraction={extraction} loading={panelLoading} demo={demo} onBack={() => { documentRequest.current++; setSelectedDocument(null); setPanelLoading(false) }} onSource={id => void inspectSource(id)} onAsk={() => { setSelectedDocument(null); setView('chat') }} /> : <><header className="topbar"><div className="breadcrumb"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileNav(true)}><Menu size={20} /></button><span className="breadcrumb-muted">Workspace</span><ChevronRight size={13} /><strong>{view === 'documents' ? 'Document library' : 'Ask Clarity'}</strong></div><div className="topbar-right"><span className={`connection ${!connected ? 'offline' : ''}`}><i />{demo ? 'Sample view' : connected ? 'Connected' : 'Offline'}</span><button className="icon-button" aria-label="Help and sample documents" onClick={() => setGuide(true)}><CircleHelp size={19} /></button></div></header>
      {demo && <div className="demo-banner"><Sparkles size={15} /><span>You’re exploring a saved example with sample records.</span><button onClick={onLogout}>Sign in to use your own documents <ArrowRight size={14} /></button></div>}
      {view === 'documents' ? <div className="library-page"><div className="page-heading"><div><span className="eyebrow">CLARITY / DOCUMENT WORKSPACE</span><h1>Understand what’s in your documents.</h1><p>Upload a clinical record, inspect how it was processed, then ask questions with traceable evidence.</p></div><button className="button primary" disabled={uploading} onClick={() => demo ? onLogout() : fileInput.current?.click()}>{uploading ? <Loader2 size={17} className="spin" /> : <Plus size={17} />}{demo ? 'Sign in to upload' : 'Upload documents'}</button></div>
        <section className="workflow-intro" aria-label="How Clarity works"><div><span>01</span><strong>Upload</strong><p>Add a PDF or text record.</p></div><div><span>02</span><strong>Review</strong><p>Inspect parsed content and extracted findings.</p></div><div><span>03</span><strong>Ask</strong><p>Get an answer and open its cited evidence.</p></div></section>
        <div className={`dropzone ${dragging ? 'dragging' : ''}`} onDragOver={event => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); void uploadFiles(event.dataTransfer.files) }}><span className="upload-symbol"><UploadCloud size={27} strokeWidth={1.5} /></span><div><strong>Add a document to your workspace</strong><p>Drop a file here or <button onClick={() => demo ? onLogout() : fileInput.current?.click()}>choose a file</button>. Processing continues in the background.</p><span>PDF or TXT · Up to 20 MB · PDFs up to 100 pages</span><span className="privacy-note">Use synthetic or de-identified records. Content is processed by the configured LLM provider.</span></div></div>
        <input ref={fileInput} className="hidden" type="file" accept=".pdf,.txt" multiple onChange={event => void uploadFiles(event.target.files)} aria-label="Upload documents" />
        {jobs.length > 0 && <div className="job-list">{jobs.map(job => <div className={`job-card ${job.status === 'failed' ? 'job-failed' : ''}`} key={job.job_id}><span className="file-icon">{terminal(job.status) ? <FileCheck2 size={19} /> : <Loader2 size={19} className="spin" />}</span><div className="job-info"><strong>{cleanName(job.filename)}</strong><span>{job.connectionError ? 'Waiting for the server — we’ll keep checking.' : job.status === 'completed_with_errors' ? `Indexed, with ${job.failed_chunks || 'some'} failed extractions. Open the document to review.` : job.status === 'completed' ? 'Indexed and ready to explore.' : job.status === 'failed' ? `Processing failed${job.error ? ` (${job.error})` : ''}. Upload again to retry.` : job.step || 'Queued for processing'}</span>{!terminal(job.status) && <div className="progress-track"><i style={{ width: job.progress }} /></div>}</div>{terminal(job.status) ? <button className="icon-button" aria-label={`Dismiss ${job.filename} notification`} onClick={() => setJobs(previous => previous.filter(item => item.job_id !== job.job_id))}><X size={16} /></button> : <span className="job-progress">{job.progress}</span>}</div>)}</div>}
        <section className="document-section"><div className="section-toolbar"><div><h2>Document library <span>{documentTotal} entries</span></h2><p>Open a document to compare its source, parsed content, extraction, and search passages.</p></div><div className="search-field"><Search size={16} /><input aria-label="Search document filenames" placeholder="Search documents…" value={filter} onChange={event => setFilter(event.target.value)} />{filter && <button aria-label="Clear search" onClick={() => setFilter('')}><X size={14} /></button>}</div></div>
          {docsError ? <div className="empty-state"><AlertCircle size={30} /><h3>Couldn’t load your library</h3><p>{docsError}</p><button className="button outline" onClick={() => void refreshDocuments()}>Try again</button></div> : docsLoading && !documents.length ? <div className="loading-state"><Loader2 className="spin" size={25} />Loading your library…</div> : !visibleDocuments.length ? <div className="empty-state"><div className="empty-icon"><FileText size={32} /></div><h3>{filter ? 'No matching documents' : 'Your next insight starts here.'}</h3><p>{filter ? 'Try another filename or clear your search.' : 'Upload a clinical record to see extracted findings and start asking questions.'}</p><button className="button outline" onClick={() => filter ? setFilter('') : setGuide(true)}>{filter ? 'Clear search' : 'Try a sample document'}<ArrowRight size={15} /></button></div> : <div className="document-table"><div className="table-head"><span>DOCUMENT</span><span>PASSAGES</span><span>EXTRACTION</span><span>ADDED</span><span /></div>{visibleDocuments.map(document => <div className="document-row" key={document.document_id}><button className="document-name" onClick={() => void inspectDocument(document)}><span className="file-icon"><FileText size={21} strokeWidth={1.5} /></span><span><strong>{cleanName(document.filename)}</strong><small>{document.document_id.startsWith('legacy-') ? 'Earlier indexed passage · original file unavailable' : document.filename.toLowerCase().includes('.pdf') ? 'PDF document' : 'Text document'}</small></span></button><span className="passage-count"><Layers3 size={14} />{document.chunk_count}</span><Status status={document.extraction_status} /><span className="document-date">{shortDate(document.created_at)}</span><div className="row-actions"><button className="icon-button" aria-label={`Inspect ${cleanName(document.filename)}`} onClick={() => void inspectDocument(document)}><ChevronRight size={18} /></button>{!demo && <button className="icon-button delete-button" aria-label={`Delete ${cleanName(document.filename)}`} onClick={() => setDeleteTarget(document)}><Trash2 size={15} /></button>}</div></div>)}</div>}
          {documents.length < documentTotal && <button className="button outline load-more" disabled={docsLoading} onClick={() => void refreshDocuments(true)}>{docsLoading ? 'Loading…' : 'Load more documents'}</button>}
        </section><div className="library-footer"><span><ShieldCheck size={14} />Record access is scoped to your signed-in account.</span><button onClick={() => { setView('chat') }}>Ready to ask a question? <ArrowRight size={14} /></button></div>
      </div> : <div className="chat-page"><div className="chat-header"><div><span className="chat-heading-icon"><Sparkles size={20} /></span><div><h2>Ask Clarity</h2><span>Answers grounded in your document library</span></div></div><button className="button outline small" onClick={newChat}><Plus size={15} />New conversation</button></div>
        <div className="chat-scroll" ref={chatScroll}>{conversationLoading ? <div className="loading-state"><Loader2 className="spin" size={25} />Opening conversation…</div> : messages.length ? <div className="messages">{demo && <div className="sample-answer-label">SAVED EXAMPLE · Click a citation to inspect its source</div>}{messages.map(message => <div key={message.id} className={`message ${message.role}`}><span className={`message-avatar ${message.role === 'assistant' ? 'assistant-avatar' : ''}`}>{message.role === 'assistant' ? <Sparkles size={17} /> : user.username.slice(0, 1).toUpperCase()}</span><div className="message-body"><div className="message-label">{message.role === 'assistant' ? 'Clarity' : demo ? 'You · sample question' : 'You'}{message.pending && <span>Working with your records</span>}</div>{message.role === 'user' ? <p className="user-question">{message.content}</p> : message.pending && !message.content ? <div className="thinking"><span /><span /><span /><small>Finding relevant evidence…</small></div> : <><Answer content={message.content} sources={message.sources} onSource={id => void inspectSource(id)} />{message.pending && <span className="stream-cursor" />}{message.interrupted && <div className="interrupted"><AlertCircle size={13} />Response interrupted. You can retry your question.</div>}</>}</div></div>)}</div> : <div className="chat-welcome"><span className="welcome-symbol"><Sparkles size={30} strokeWidth={1.3} /></span><span className="eyebrow">LET YOUR RECORDS SPEAK</span><h1>What would you like<br />to understand?</h1><p>Ask about your documents. Get a clear answer<br />with the passages that support it.</p>{!documentTotal ? <button className="button primary" onClick={() => setView('documents')}><UploadCloud size={17} />Upload your first document</button> : <div className="suggestions">{['What symptoms and measurements were recorded?', 'Summarize the reported adverse event.', 'What follow-up plan does the record describe?'].map(question => <button key={question} onClick={() => void sendQuestion(question)}><FileSearch size={18} /><span>{question}</span><ArrowUp size={15} /></button>)}</div>}</div>}</div>
        <div className="composer-wrap"><form className="composer" onSubmit={event => { event.preventDefault(); void sendQuestion(draft) }}><textarea aria-label="Ask a question about your documents" placeholder={demo ? 'Sign in to ask questions about your own documents' : 'Ask a question about your documents…'} value={draft} rows={2} disabled={demo} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendQuestion(draft) } }} /><div className="composer-bottom"><span><BookOpen size={14} />{demo ? 'Saved example' : `${documentTotal} document${documentTotal === 1 ? '' : 's'} in your library`}</span>{demo ? <button type="button" className="button primary small" onClick={onLogout}>Sign in to ask<ArrowRight size={14} /></button> : busy ? <button type="button" className="send-button" aria-label="Stop generating" onClick={() => chatAbort.current?.abort()}><Square size={17} /></button> : <button className="send-button" aria-label="Send question" disabled={!draft.trim() || conversationLoading}><ArrowUp size={20} /></button>}</div></form><p className="composer-note">AI responses can be incomplete. Review the cited records before drawing conclusions.</p></div>
      </div>}
    </>}</main>
    {(selectedDocument || panelLoading) && <><button className="panel-scrim" aria-label="Close document panel" onClick={() => { documentRequest.current++; setSelectedDocument(null); setPanelLoading(false) }} /><aside className="detail-panel" role="dialog" aria-label="Document details"><div className="panel-heading"><span className="eyebrow">DOCUMENT DETAIL</span><button className="icon-button" aria-label="Close document details" onClick={() => { documentRequest.current++; setSelectedDocument(null); setPanelLoading(false) }}><X size={20} /></button></div><span className="panel-file-icon"><FileText size={29} strokeWidth={1.4} /></span><h2>{cleanName(selectedDocument?.filename || 'Loading document')}</h2><p className="panel-meta">{selectedDocument?.chunks.length || '—'} source passages{selectedDocument?.created_at ? ` · Added ${shortDate(selectedDocument.created_at)}` : ''}</p><div className="panel-tabs"><button className={panelTab === 'extraction' ? 'active' : ''} onClick={() => setPanelTab('extraction')}><Sparkles size={15} />Extraction</button><button className={panelTab === 'passages' ? 'active' : ''} onClick={() => setPanelTab('passages')}><BookOpen size={15} />Source passages</button></div><div className="panel-content">{panelLoading ? <div className="loading-state"><Loader2 className="spin" size={22} />Loading findings…</div> : panelTab === 'extraction' ? extraction?.items.map(item => <article className="extraction-card" key={item.document_id}><div className="extraction-card-head"><span>{item.page_number ? `Page ${item.page_number}` : 'Text record'} · Passage {(item.chunk_index ?? 0) + 1}</span><Status status={item.status} /></div>{item.status === 'failed' ? <div className="error-box"><AlertCircle size={17} /><span>Extraction failed{item.error_type ? ` (${item.error_type})` : ''}. The source passage is still available for review.</span></div> : item.result ? <><span className="category-label">{item.result.category}</span><p>{item.result.summary}</p>{Object.keys(item.result.key_entities).length > 0 && <dl className="entities">{Object.entries(item.result.key_entities).map(([key, value]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}<div className="confidence"><span>Model-reported confidence</span><strong>{Math.round(item.result.confidence * 100)}%</strong></div></> : <p className="muted">Extraction is not available yet.</p>}</article>) : selectedDocument?.chunks.map(chunk => <article className="passage-card" key={chunk.id}><div><span><BookOpen size={14} />{chunk.page_number ? `Page ${chunk.page_number}` : 'Text record'}</span><small>Passage {(chunk.chunk_index ?? 0) + 1}</small></div><p>{chunk.content}</p></article>)}</div></aside></>}
    {(source || sourceLoading) && <><button className="panel-scrim" aria-label="Close source panel" onClick={() => { sourceRequest.current++; setSource(null); setSourceLoading(false) }} /><aside className="detail-panel source-panel" role="dialog" aria-label="Cited source passage"><div className="panel-heading"><span className="eyebrow">FOLLOW THE EVIDENCE</span><button className="icon-button" aria-label="Close source passage" onClick={() => { sourceRequest.current++; setSource(null); setSourceLoading(false) }}><X size={20} /></button></div><span className="panel-file-icon"><BookOpen size={29} strokeWidth={1.4} /></span><h2>{cleanName(source?.filename || 'Loading source')}</h2><p className="panel-meta">{source?.page_number ? `Page ${source.page_number}` : 'Source passage'}{source?.element_type ? ` · ${source.element_type}` : ''}{source?.section_title ? ` · ${source.section_title}` : ''}{source?.chunk_index != null ? ` · Passage ${source.chunk_index + 1}` : ''}</p><div className="source-explainer"><ShieldCheck size={17} /><p>This is the retrieved passage cited by the answer. Check the wording and context for yourself.</p></div><div className="panel-content">{sourceLoading ? <div className="loading-state"><Loader2 className="spin" size={22} />Opening source…</div> : <><div className="source-text">{source?.content}</div>{!!source?.visuals?.length && <div className="source-visuals">{source.visuals.map((visual, index) => <figure key={`${visual.url}-${index}`}><img src={visual.object_url} alt={`Source visual ${index + 1}`} /><figcaption>Original visual from {source?.filename}, page {source?.page_number || 'unknown'}.</figcaption></figure>)}</div>}</>}</div></aside></>}
    {deleteTarget && <div className="modal-scrim" onClick={() => !deleting && setDeleteTarget(null)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title" onClick={event => event.stopPropagation()}><span className="modal-icon danger"><Trash2 size={24} /></span><h2 id="delete-title">Delete this document?</h2><p><strong>{cleanName(deleteTarget.filename)}</strong> and its extraction results will be permanently removed from your library.</p><div className="modal-actions"><button className="button outline" disabled={deleting} onClick={() => setDeleteTarget(null)}>Keep document</button><button className="button destructive" disabled={deleting} onClick={() => void deleteDocument()}>{deleting ? <Loader2 className="spin" size={16} /> : null}Delete document</button></div></section></div>}
    {guide && <div className="modal-scrim" onClick={() => setGuide(false)}><section className="modal guide-modal" role="dialog" aria-modal="true" aria-labelledby="guide-title" onClick={event => event.stopPropagation()}><button className="icon-button modal-close" aria-label="Close guide" onClick={() => setGuide(false)}><X size={20} /></button><span className="modal-icon"><FileSearch size={25} /></span><span className="eyebrow">FROM RECORD TO UNDERSTANDING</span><h2 id="guide-title">A little clarity, in three steps.</h2><div className="guide-steps">{[['01', 'Add a document', 'Upload a PDF or TXT file. Text, tables, and selected figures are processed in the background.'], ['02', 'Explore the findings', 'Open a document to inspect extracted summaries, entities, source passages, and processing errors.'], ['03', 'Ask and verify', 'Ask a question, continue the conversation, and open a citation to inspect its passage and original figure.']].map(([number, title, body]) => <div key={number}><span>{number}</span><section><strong>{title}</strong><p>{body}</p></section></div>)}</div><div className="sample-downloads"><span className="eyebrow">TRY THESE SAMPLE RECORDS</span><a href="/samples/cardiovascular-followup.pdf" download><FileText size={18} /><span>Cardiovascular follow-up</span><ArrowDownToLine size={16} /></a><a href="/samples/adverse-event-report.pdf" download><FileText size={18} /><span>Adverse event report</span><ArrowDownToLine size={16} /></a><p>These PDFs contain invented records for demonstration.</p></div></section></div>}
    {toast && <div className="toast" role="status"><AlertCircle size={18} /><span>{toast}</span><button aria-label="Dismiss notification" onClick={() => setToast('')}><X size={16} /></button></div>}
  </div>
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem('clarity.token'))
  const [sessionRetry, setSessionRetry] = useState(0)
  const [user, setUser] = useState<User | null>(null), [checking, setChecking] = useState(!!token), [demo, setDemo] = useState(false), [message, setMessage] = useState('')
  setAccessToken(token)
  const logout = useCallback(() => { setAccessToken(null); sessionStorage.removeItem('clarity.token'); setToken(null); setUser(null); setDemo(false); setChecking(false) }, [])
  useEffect(() => {
    if (!token) { setChecking(false); return }
    let canceled = false; setChecking(true); setMessage('')
    request<User>('/me').then(user => { if (!canceled) setUser(user) }).catch(error => { if (!canceled) { if (error instanceof ApiError && error.status === 401) logout(); setMessage(errorText(error)) } }).finally(() => { if (!canceled) setChecking(false) })
    return () => { canceled = true }
  }, [token, logout, sessionRetry])
  useEffect(() => { function expired() { logout(); setMessage('Your session expired. Sign in to continue.') } window.addEventListener('session-expired', expired); return () => window.removeEventListener('session-expired', expired) }, [logout])
  if (checking) return <div className="boot-screen"><Brand /><Loader2 className="spin" size={24} /><p>Opening your workspace…</p></div>
  if (demo) return <Workspace key="demo" user={{ id: 0, username: 'Demo' }} demo onLogout={logout} />
  if (token && !user) return <div className="boot-screen"><Brand /><AlertCircle size={24} /><p>We couldn’t reconnect to your workspace.</p><p>{message}</p><button className="button primary" onClick={() => setSessionRetry(value => value + 1)}>Retry connection</button><button className="button outline" onClick={logout}>Return to sign in</button></div>
  if (!token || !user) return <AuthScreen message={message} onDemo={() => { setMessage(''); setDemo(true) }} onLogin={(token, user) => { sessionStorage.setItem('clarity.token', token); setAccessToken(token); setToken(token); setUser(user); setMessage('') }} />
  return <Workspace key={user.id} user={user} demo={false} onLogout={logout} />
}
