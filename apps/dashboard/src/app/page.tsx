'use client'

import { useState, useCallback, useRef } from 'react'
import Image from 'next/image'

/* ────────────────────────────────
   AntiVibe Landing Page — Fly.io 1:1 Replication
   Exact specs from styles.refero.design/style/fly.io
   ──────────────────────────────── */

export default function Home() {
  /* ── Scan State (preserved) ── */
  const [target, setTarget] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [findings, setFindings] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  /* ── Poll Status (preserved) ── */
  const pollStatus = useCallback((id: string) => {
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/scan?scan_id=${encodeURIComponent(id)}`)
        if (!res.ok) {
          clearInterval(pollingRef.current!)
          setLoading(false)
          setStatus('error')
          setError('Failed to poll scan status')
          return
        }
        const data = await res.json()
        setStatus(data.status)
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollingRef.current!)
          setLoading(false)
          if (data.findings) setFindings(data.findings)
          if (data.error) setError(data.error)
        }
      } catch {
        clearInterval(pollingRef.current!)
        setLoading(false)
        setError('Polling failed')
      }
    }, 2000)
  }, [])

  /* ── Handle Scan (preserved) ── */
  const handleScan = useCallback(async () => {
    if (!target.trim()) return
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
    setLoading(true); setError(null); setStatus('starting'); setFindings(null); setScanId(null)
    try {
      const res = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: target.trim() }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || `Server responded with ${res.status}`)
      }
      const data = await res.json()
      setScanId(data.scan_id)
      const s = data.status || 'running'
      setStatus(s)
      if (s !== 'completed' && s !== 'failed') {
        pollStatus(data.scan_id)
      } else {
        setLoading(false)
        if (data.findings) setFindings(data.findings)
        if (data.error) setError(data.error)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(msg); setLoading(false)
    }
  }, [target, pollStatus])

  return (
    <div className="flex flex-col min-h-screen bg-[#f1f2f9]">

      {/* ═══════════════════════════════════════
          NAVBAR — Floating Pill (Fly.io style)
          ═══════════════════════════════════════ */}
      <header className="fixed top-5 left-1/2 -translate-x-1/2 z-50 w-auto">
        <nav className="flex items-center gap-1 px-2 py-2 rounded-full bg-white/70 backdrop-blur-xl shadow-[0_1px_3px_rgba(0,0,0,0.05)] border border-[#e7e6f4]/60">
          {/* Logo */}
          <div className="flex items-center gap-2 px-4 py-1.5">
            <div className="w-6 h-6 rounded-full bg-[#7c3aed] flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <span className="font-body text-[15px] font-semibold text-[#281950]">AntiVibe</span>
          </div>

          {/* Nav Links — center */}
          <div className="hidden md:flex items-center gap-1 px-2">
            {['Products', 'Docs', 'Pricing'].map((item) => (
              <a
                key={item}
                href={`#${item.toLowerCase()}`}
                className="px-3 py-1.5 rounded-full font-body text-[14px] font-medium text-[#5e537c] hover:text-[#281950] hover:bg-[#f1f2f9]/80 transition-all"
              >
                {item}
              </a>
            ))}
          </div>

          {/* Auth — right */}
          <div className="flex items-center gap-2 px-2">
            <button className="px-4 py-1.5 rounded-full font-body text-[14px] font-medium text-[#5e537c] hover:text-[#281950] transition-colors">
              Sign In
            </button>
            <button className="px-4 py-1.5 rounded-full font-body text-[14px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] transition-colors">
              Get Started
            </button>
          </div>
        </nav>
      </header>

      <main>

        {/* ═══════════════════════════════════════
            HERO — Full Viewport, Illustration Bleeds
            ═══════════════════════════════════════ */}
        <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden pt-20">
          
          {/* Background Illustration — full bleed, vibrant, no fade */}
          <div className="absolute inset-0 z-0">
            <Image
              src="/illustrations/hero-thought-cloud.jpg"
              alt=""
              fill
              className="object-cover object-center"
              priority
              sizes="100vw"
            />
          </div>

          {/* Content — centered, z-10, clear zone */}
          <div className="relative z-10 text-center max-w-[720px] px-6">
            
            {/* Headline — Fly.io exact style */}
            <h1 
              className="font-display text-[clamp(36px,5vw,64px)] font-medium leading-[1.15] tracking-[-0.045em] text-[#281950]"
            >
              Stop the bad vibes.
              <br />
              <em className="italic font-medium">in your AI code.</em>
            </h1>

            {/* Body — Fly.io exact style */}
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] max-w-[560px] mx-auto mt-6">
              The platform for devs who just want to ship safely. Paste a repo URL, get a full security audit with patches you can merge.
            </p>

            {/* Scan Form — integrated as CTA */}
            <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3 max-w-[480px] mx-auto">
              <input
                type="text"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="github.com/user/repo"
                className="w-full sm:flex-1 px-5 py-3 rounded-full border border-[#e7e6f4] bg-white/90 backdrop-blur-sm font-body text-[15px] text-[#281950] placeholder:text-[#a39ac1] focus:outline-none focus:ring-2 focus:ring-[#7c3aed]/30 focus:border-[#7c3aed] transition-all"
                onKeyDown={(e) => e.key === 'Enter' && handleScan()}
              />
              <button
                onClick={handleScan}
                disabled={loading || !target.trim()}
                className="w-full sm:w-auto px-6 py-3 rounded-full font-body text-[15px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] active:scale-95 disabled:opacity-50 disabled:active:scale-100 transition-all flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Scanning...
                  </>
                ) : (
                  <>
                    Scan your repo
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                  </>
                )}
              </button>
            </div>

            {/* Status / Error / Findings */}
            {error && (
              <div className="mt-4 rounded-xl bg-red-50 border border-red-100 px-4 py-3 text-sm font-body text-red-700 max-w-[480px] mx-auto">
                {error}
              </div>
            )}

            {status && !error && status !== 'idle' && (
              <div className="mt-4 flex items-center justify-center gap-2 text-sm font-body text-[#5e537c]">
                <span className={`inline-block w-2 h-2 rounded-full ${status === 'completed' ? 'bg-green-500' : status === 'failed' ? 'bg-red-500' : 'bg-amber-400 animate-pulse'}`} />
                <span className="font-medium">{status}</span>
                {scanId && <span className="text-xs opacity-60 font-mono">ID: {scanId}</span>}
              </div>
            )}

            {findings && findings.length > 0 && (
              <div className="mt-6 space-y-3 text-left max-w-[560px] mx-auto">
                <h3 className="font-display text-[22px] font-medium text-[#281950] text-center">
                  Findings ({findings.length})
                </h3>
                {findings.map((f, i) => (
                  <div key={i} className="rounded-xl bg-white/80 backdrop-blur-sm border border-[#e7e6f4] p-4">
                    <pre className="text-xs overflow-auto whitespace-pre-wrap font-mono text-[#5e537c]">{JSON.stringify(f, null, 2)}</pre>
                  </div>
                ))}
              </div>
            )}

            {findings && findings.length === 0 && status === 'completed' && (
              <div className="mt-4 rounded-xl bg-green-50 border border-green-100 px-4 py-3 text-sm font-body text-green-700 max-w-[480px] mx-auto">
                No findings — scan completed clean.
              </div>
            )}
          </div>
        </section>

        {/* ═══════════════════════════════════════
            TRUSTED BY
            ═══════════════════════════════════════ */}
        <section className="py-16 border-t border-[#e7e6f4]">
          <div className="max-w-[1200px] mx-auto px-6 flex flex-col md:flex-row items-center justify-center gap-8 md:gap-16">
            <p className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#a39ac1]">
              Trusted by vibe-coders at
            </p>
            <div className="flex flex-wrap justify-center gap-8 md:gap-12 opacity-30 grayscale">
              {['VibeLabs', 'ModernAI', 'TechCorp', 'SudoApps'].map((name) => (
                <span key={name} className="font-display text-[20px] font-semibold text-[#281950]">{name}</span>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            FEATURES — 3-Tier Pipeline
            ═══════════════════════════════════════ */}
        <section id="products" className="py-24 md:py-32">
          <div className="max-w-[1200px] mx-auto px-6">
            <div className="text-center mb-16">
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950]">
                The 3-Tier Audit Pipeline
              </h2>
              <div className="w-20 h-0.5 bg-[#7c3aed] mx-auto mt-4 rounded-full" />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {[
                { title: 'Static Semantic Scan', desc: 'AST analysis + secret detection with LLM semantic depth. We understand developer intent, not just patterns.', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
                { title: 'Isolated Sandbox', desc: 'Spin up your app in an ephemeral microVM with mock seeded DBs. Execute and verify safely in real-time.', icon: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z' },
                { title: 'Agentic Fuzzing', desc: 'Our agent forges identities and never stops at a 403. It finds complex logic flaws that static tools miss.', icon: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
              ].map((feature, i) => (
                <div key={i} className="p-8 rounded-2xl bg-white border border-[#e7e6f4] hover:shadow-lg hover:-translate-y-1 transition-all">
                  <div className="w-12 h-12 rounded-xl bg-[#f1f2f9] flex items-center justify-center mb-6">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d={feature.icon} />
                    </svg>
                  </div>
                  <h3 className="font-display text-[22px] font-medium tracking-[-0.025em] text-[#281950] mb-3">
                    {feature.title}
                  </h3>
                  <p className="font-body text-[16px] leading-[26px] text-[#5e537c]">
                    {feature.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            DEEP SECURITY
            ═══════════════════════════════════════ */}
        <section className="py-24 md:py-32 bg-[#191034] text-white">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] mb-8">
                Deep security<br />without the friction.
              </h2>
              <div className="space-y-6">
                <div className="flex gap-4 items-start">
                  <div className="shrink-0 w-10 h-10 rounded-lg bg-[#7c3aed]/20 flex items-center justify-center">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c8bfff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-body text-[16px] font-semibold mb-1">Auto-Patching Agent</h4>
                    <p className="font-body text-[15px] leading-[24px] text-[#a39ac1]">
                      We create the branch and open the PR for you to review, with full context on every fix.
                    </p>
                  </div>
                </div>
                <div className="flex gap-4 items-start">
                  <div className="shrink-0 w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#c8bfff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-body text-[16px] font-semibold mb-1">JWT Forgery Engine</h4>
                    <p className="font-body text-[15px] leading-[24px] text-[#a39ac1]">
                      Simulates complex identity attacks to ensure your auth is rock solid across all API versions.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Terminal Window */}
            <div className="relative">
              <div className="rounded-2xl bg-[#1e1b2e] border border-white/10 p-6 shadow-2xl">
                <div className="flex gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-[#ff5f56]" />
                  <div className="w-3 h-3 rounded-full bg-[#ffbd2e]" />
                  <div className="w-3 h-3 rounded-full bg-[#27c93f]" />
                </div>
                <div className="space-y-1.5 font-mono text-[13px] leading-[20px]">
                  <div className="text-[#c8bfff]">@antivibe/detective-bird running...</div>
                  <div className="text-white/60">Analyzing /api/user/v1/profile...</div>
                  <div className="px-3 py-2 rounded-lg bg-red-500/10 border-l-2 border-red-400 text-red-200">
                    VULNERABILITY: Broken Object Level Authorization
                  </div>
                  <div className="text-green-300">Generating fix: auth_middleware.ts...</div>
                  <div className="text-green-300">Opening PR: #402 Fix BOLA vulnerability</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            CTA
            ═══════════════════════════════════════ */}
        <section id="pricing" className="py-24 md:py-32">
          <div className="max-w-[720px] mx-auto px-6 text-center">
            <h2 className="font-display text-[clamp(32px,4vw,48px)] font-medium leading-[1.15] tracking-[-0.045em] text-[#281950] mb-4">
              Ready to secure the vibe?
            </h2>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-8 max-w-[480px] mx-auto">
              No credit card required. Start with one free scan to see what&apos;s lurking in your AI-generated routes.
            </p>
            <button className="px-8 py-3.5 rounded-full font-body text-[16px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] active:scale-95 transition-all inline-flex items-center gap-2">
              Claim 1 Free Scan
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7"/>
              </svg>
            </button>
            <p className="mt-4 font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#a39ac1]">
              Trusted by 2,000+ developers
            </p>
          </div>
        </section>

      </main>

      {/* ═══════════════════════════════════════
          FOOTER
          ═══════════════════════════════════════ */}
      <footer className="border-t border-[#e7e6f4] py-16">
        <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-12">
          <div className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-6 h-6 rounded-full bg-[#7c3aed] flex items-center justify-center">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
              </div>
              <span className="font-display text-[20px] font-semibold text-[#281950]">AntiVibe</span>
            </div>
            <p className="font-body text-[14px] leading-[22px] text-[#5e537c]">
              &copy; 2024 AntiVibe. Isolated, agentic security for modern AI stacks.
            </p>
          </div>
          <div>
            <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#281950] mb-4">Product</h4>
            <ul className="space-y-3">
              {['Features', 'Pricing', 'CLI Docs'].map((item) => (
                <li key={item}><a href="#" className="font-body text-[14px] text-[#5e537c] hover:text-[#7c3aed] transition-colors">{item}</a></li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#281950] mb-4">Company</h4>
            <ul className="space-y-3">
              {['About', 'Security', 'Blog'].map((item) => (
                <li key={item}><a href="#" className="font-body text-[14px] text-[#5e537c] hover:text-[#7c3aed] transition-colors">{item}</a></li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#281950] mb-4">Legal</h4>
            <ul className="space-y-3">
              {['Privacy', 'Terms'].map((item) => (
                <li key={item}><a href="#" className="font-body text-[14px] text-[#5e537c] hover:text-[#7c3aed] transition-colors">{item}</a></li>
              ))}
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}
