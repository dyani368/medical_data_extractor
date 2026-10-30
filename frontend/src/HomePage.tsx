import { useState } from 'react'
import { ArrowRight, FileSearch, Menu, X } from 'lucide-react'

type Props = {
  authenticated: boolean
  onSignIn: () => void
  onWorkspace: () => void
  onSample: () => void
}

export default function HomePage({ authenticated, onSignIn, onWorkspace, onSample }: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const enter = authenticated ? onWorkspace : onSample
  return <div className="home-page">
    <header className="home-header">
      <a className="home-brand" href="/" aria-label="Clarity home"><span className="home-brand-icon"><FileSearch size={19} strokeWidth={1.8} /></span><span>clarity<span className="home-brand-period">.</span></span></a>
      <div className="home-mobile-actions"><button className="home-mobile-login" onClick={authenticated ? onWorkspace : onSignIn}>{authenticated ? 'Workspace' : 'Sign in'}</button><button className="home-menu-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}>{menuOpen ? <X size={21} /> : <Menu size={21} />}</button></div>
      <nav className={menuOpen ? 'home-nav open' : 'home-nav'} aria-label="Main navigation">
        <a href="#review" onClick={() => setMenuOpen(false)}>Document review</a>
        <button className="home-nav-login" onClick={authenticated ? onWorkspace : onSignIn}>{authenticated ? 'Open workspace' : 'Sign in'} <ArrowRight size={16} /></button>
      </nav>
    </header>

    <main>
      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy">
          <p className="home-kicker">DOCUMENT INTELLIGENCE</p>
          <h1 id="home-title">Understand the document.<br /><em>See the evidence.</em></h1>
          <p className="home-lead">Review PDF pages beside structured findings, then ask questions with answers linked to the original document.</p>
          <div className="home-hero-actions"><button className="home-primary" onClick={enter}>{authenticated ? 'Open your workspace' : 'Explore sample workspace'} <ArrowRight size={18} /></button></div>
        </div>
        <div className="home-product-preview" aria-label="Illustration of source-linked document review">
          <div className="home-preview-top"><span className="home-preview-dot" /> Document review <span>Page 1</span></div>
          <div className="home-preview-body"><div className="home-preview-paper"><div className="home-paper-label">SOURCE DOCUMENT</div><strong>Service reliability review</strong><div className="home-paper-rule" /><p>Incident review</p><div className="home-paper-highlight">A database connection pool limit caused a <strong>37-minute outage</strong>. The team increased the limit and added alerts.</div><div className="home-paper-lines"><i /><i /><i /></div></div><div className="home-preview-findings"><div className="home-paper-label">FINDINGS</div><div className="home-finding"><span>Cause</span><strong>Connection pool limit</strong></div><div className="home-finding"><span>Impact</span><strong>37-minute outage</strong></div></div></div>
        </div>
      </section>

      <section id="review" className="home-section home-review" aria-labelledby="review-title"><div><p className="home-kicker">BUILT AROUND THE DOCUMENT</p><h2 id="review-title">Review the source<br />and the findings together.</h2><p>Inspect the original page, the content parsed from it, and the facts extracted by AI. Open a cited answer to see its source in context.</p><button className="home-text-action" onClick={enter}>{authenticated ? 'Open your workspace' : 'Explore sample workspace'} <ArrowRight size={17} /></button></div><div className="home-review-list"><div><span>01 / SOURCE</span><strong>Original page view</strong><p>Read the page beside its processed content.</p></div><div><span>02 / STRUCTURE</span><strong>Text, tables & figures</strong><p>Move through parsed sections without losing page context.</p></div><div><span>03 / ANSWER</span><strong>Linked citations</strong><p>Trace an answer back to the original document.</p></div></div></section>
    </main>
    <footer className="home-footer"><span>clarity. <small>Document Intelligence</small></span><a href="https://github.com/dyani368/medical_data_extractor" target="_blank" rel="noreferrer">GitHub ↗</a></footer>
  </div>
}
