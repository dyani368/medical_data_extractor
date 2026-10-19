import { useState } from 'react'
import { ArrowRight, BookOpen, FileSearch, FileText, Layers3, Menu, ShieldCheck, X } from 'lucide-react'

type Props = {
  authenticated: boolean
  onSignIn: () => void
  onWorkspace: () => void
  onSample: () => void
}

export default function HomePage({ authenticated, onSignIn, onWorkspace, onSample }: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const enter = authenticated ? onWorkspace : onSignIn
  return <div className="home-page">
    <header className="home-header">
      <a className="home-brand" href="/" aria-label="Clarity home"><span className="home-brand-icon"><FileSearch size={19} strokeWidth={1.8} /></span><span>clarity<span className="home-brand-period">.</span></span></a>
      <div className="home-mobile-actions"><button className="home-mobile-login" onClick={enter}>{authenticated ? 'Workspace' : 'Sign in'}</button><button className="home-menu-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}>{menuOpen ? <X size={21} /> : <Menu size={21} />}</button></div>
      <nav className={menuOpen ? 'home-nav open' : 'home-nav'} aria-label="Main navigation">
        <a href="#workflow" onClick={() => setMenuOpen(false)}>How it works</a>
        <a href="#review" onClick={() => setMenuOpen(false)}>Document review</a>
        <a href="#principles" onClick={() => setMenuOpen(false)}>Our approach</a>
        <button className="home-nav-login" onClick={enter}>{authenticated ? 'Open workspace' : 'Sign in'} <ArrowRight size={16} /></button>
      </nav>
    </header>

    <main>
      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy">
          <p className="home-kicker">CLINICAL DOCUMENT INTELLIGENCE</p>
          <h1 id="home-title">Understand the document.<br /><em>See the evidence.</em></h1>
          <p className="home-lead">Clarity turns clinical PDFs into reviewable text, tables, and findings—then helps you ask questions with answers linked back to the source.</p>
          <div className="home-hero-actions"><button className="home-primary" onClick={enter}>{authenticated ? 'Open your workspace' : 'Get started'} <ArrowRight size={18} /></button><a className="home-secondary" href="#workflow">Explore the workflow <ArrowRight size={17} /></a></div>
          <p className="home-hero-note"><ShieldCheck size={16} /> Your documents remain in your account-scoped workspace.</p>
        </div>
        <div className="home-product-preview" aria-label="Illustration of source-linked document review">
          <div className="home-preview-top"><span className="home-preview-dot" /> Document review <span>Page 1 of 2</span></div>
          <div className="home-preview-body"><div className="home-preview-paper"><div className="home-paper-label">SOURCE DOCUMENT</div><strong>Cardiovascular follow-up</strong><div className="home-paper-rule" /><p>Presenting concern</p><div className="home-paper-highlight">Reports mild dizziness during the last week. Blood pressure at this visit: <strong>160/95 mmHg.</strong></div><div className="home-paper-lines"><i /><i /><i /></div></div><div className="home-preview-findings"><div className="home-paper-label">EXTRACTED FINDINGS</div><div className="home-finding"><span>Symptom</span><strong>Mild dizziness</strong><small>Page 1 · source linked</small></div><div className="home-finding"><span>Blood pressure</span><strong>160/95 mmHg</strong><small>Page 1 · source linked</small></div><div className="home-preview-citation"><BookOpen size={15} /> Open source passage <ArrowRight size={14} /></div></div></div>
          <div className="home-preview-caption">Illustrative sample record. The workspace shows the actual parsed pages and findings from your files.</div>
        </div>
      </section>

      <section id="workflow" className="home-section home-workflow" aria-labelledby="workflow-title"><div className="home-section-heading"><p className="home-kicker">ONE CONNECTED WORKFLOW</p><h2 id="workflow-title">From upload to a verifiable answer.</h2><p>Each stage stays visible, so you can see what was processed before relying on an answer.</p></div><div className="home-steps"><article><span>01</span><FileText size={23} /><h3>Process</h3><p>Upload a PDF. Background workers parse its pages, tables, and figures, redact sensitive information, and report processing status.</p></article><article><span>02</span><Layers3 size={23} /><h3>Review</h3><p>Inspect the original page alongside extracted content and findings. See what was indexed—and what needs another look.</p></article><article><span>03</span><BookOpen size={23} /><h3>Ask & verify</h3><p>Ask follow-up questions across your records. Open page-level citations and check the evidence behind each answer.</p></article></div></section>

      <section id="review" className="home-section home-review" aria-labelledby="review-title"><div><p className="home-kicker">BUILT AROUND THE RECORD</p><h2 id="review-title">A review workspace,<br />not just a chat box.</h2><p>Documents are the starting point. Clarity shows how each one was parsed, what the extraction found, and which passage an answer used. If processing is incomplete, you can see that too.</p><button className="home-text-action" onClick={onSample}>Explore sample records <ArrowRight size={17} /></button></div><div className="home-review-list"><div><span>01 / SOURCE</span><strong>Original page view</strong><p>Read the page beside the extracted content.</p></div><div><span>02 / STRUCTURE</span><strong>Text, tables & figures</strong><p>Move through parsed sections without losing page context.</p></div><div><span>03 / ANSWER</span><strong>Linked citations</strong><p>Trace an answer back to the passage that supports it.</p></div></div></section>

      <section id="principles" className="home-section home-principles"><p className="home-kicker">DESIGNED FOR CAREFUL USE</p><div><h2>Evidence before confidence.</h2><p>Clarity can help you explore records; it does not replace clinical judgment. Answers can be incomplete, and the source document remains the place to verify them.</p></div></section>
    </main>
    <footer className="home-footer"><span>clarity. <small>Clinical Document Intelligence</small></span><a href="https://github.com/dyani368/medical_data_extractor" target="_blank" rel="noreferrer">GitHub ↗</a></footer>
  </div>
}
