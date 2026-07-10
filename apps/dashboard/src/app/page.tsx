'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import Image from 'next/image'
import { Shield, Terminal, Cloud, Brain, CheckCircle, FileCode, Lock, Search, Star, Bug, ChevronRight, Zap } from 'lucide-react'

/* ────────────────────────────────
   AntiVibe Landing Page — Stitch Design Replication
   Exact 1:1 of https://stitch.withgoogle.com/projects/127707556099249343
   Preserves all scan functionality from original page.tsx
   ──────────────────────────────── */

export default function Home() {
  /* ── Scan State (preserved from original) ── */
  const [target, setTarget] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [findings, setFindings] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const terminalRef = useRef<HTMLDivElement>(null)

  /* ── Terminal animation ── */
  useEffect(() => {
    if (!terminalRef.current) return
    const lines = terminalRef.current.querySelectorAll('.terminal-line')
    lines.forEach((el, index) => {
      const htmlEl = el as HTMLElement
      htmlEl.style.opacity = '0'
      htmlEl.style.transform = 'translateY(5px)'
      setTimeout(() => {
        htmlEl.style.transition = 'all 0.4s ease-out'
        htmlEl.style.opacity = '1'
        htmlEl.style.transform = 'translateY(0)'
      }, 800 + (index * 200))
    })
  }, [])

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
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    setLoading(true)
    setError(null)
    setStatus('starting')
    setFindings(null)
    setScanId(null)
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
      setError(msg)
      setLoading(false)
    }
  }, [target, pollStatus])

  /* ── Design Tokens (exact from Stitch) ── */
  const surface = '#fcf8ff'
  const onSurface = '#181445'
  const primary = '#4104da'
  const onPrimary = '#ffffff'
  const surfaceVariant = '#e3dfff'
  const outline = '#787588'
  const outlineVariant = '#c9c4d9'
  const lavenderAccent = '#f5f3ff'
  const mintAccent = '#d1fae5'
  const peachAccent = '#ffedd5'
  const inverseSurface = '#2d2a5b'
  const secondaryFixedDim = '#d0bcff'
  const securityPass = '#10B981'
  const securityFail = '#EF4444'
  const securityWarning = '#F59E0B'

  return (
    <div className="flex flex-col min-h-screen" style={{ backgroundColor: surface, color: onSurface, fontFamily: 'var(--font-hanken), sans-serif' }}>

      {/* ═══════════════════════════════════════
          NAVBAR — Fixed, Glassmorphism
          ═══════════════════════════════════════ */}
      <header className="fixed top-0 w-full z-50 flex justify-between items-center px-4 md:px-12 h-20 border-b" style={{ backgroundColor: 'rgba(252,248,255,0.8)', backdropFilter: 'blur(20px)', borderColor: 'rgba(201,196,217,0.3)' }}>
        <div className="flex items-center gap-2" style={{ fontFamily: 'var(--font-libre), serif', fontSize: '24px', fontWeight: 700, color: primary }}>
          <Shield className="w-6 h-6" style={{ color: primary }} />
          AntiVibe
        </div>
        <nav className="hidden md:flex gap-6 items-center">
          <a href="#pipeline" className="font-semibold hover:text-[#4104da] transition-colors" style={{ color: onSurface }}>Products</a>
          <a href="#security" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Docs</a>
          <a href="#cta" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Pricing</a>
        </nav>
        <div className="flex items-center gap-4">
          <button className="hidden md:block hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Login</button>
          <button className="px-5 py-2.5 rounded-lg font-bold hover:brightness-110 transition-all" style={{ backgroundColor: primary, color: onPrimary }}>Get Started</button>
        </div>
      </header>

      <main className="pt-20">

        {/* ═══════════════════════════════════════
            HERO SECTION — 95vh, Illustration Background
            ═══════════════════════════════════════ */}
        <section className="relative min-h-[95vh] flex flex-col items-center justify-center pt-32 pb-20 overflow-hidden">
          {/* Background Illustration */}
          <div className="absolute inset-0 z-0 flex justify-center items-center pointer-events-none opacity-40">
            <Image
              src="/illustrations/hero-thought-cloud.jpg"
              alt="AntiVibe Hero Illustration"
              width={1440}
              height={900}
              className="w-full max-w-[1440px] h-auto object-cover hero-bleed-image"
              priority
            />
          </div>

          <div className="relative z-10 max-w-[900px] px-4 text-center">
            {/* Mascot Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-2 mb-8 rounded-full border" style={{ backgroundColor: lavenderAccent, borderColor: 'rgba(65,4,218,0.2)', color: primary, fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px', fontWeight: 600, letterSpacing: '0.05em' }}>
              <Zap className="w-4 h-4" />
              ELITE AGENTIC SECURITY
            </div>

            <h1 className="mb-8 leading-tight" style={{ fontFamily: 'var(--font-libre), serif', fontSize: 'clamp(40px, 5vw, 64px)', fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.02em', color: onSurface }}>
              Stop the <span className="italic" style={{ color: primary }}>bad vibes</span><br className="hidden md:block" /> in your AI code.
            </h1>

            <p className="mb-12 max-w-2xl mx-auto" style={{ fontFamily: 'var(--font-hanken), sans-serif', fontSize: '18px', lineHeight: '28px', color: '#474556' }}>
              AntiVibe audits your codebase in an isolated Fly.io sandbox. We forge JWTs, fuzz your BOLA/IDOR endpoints, and open the PR to fix it.
            </p>

            {/* ── Scan Form (preserved functionality, styled to match) ── */}
            <div className="flex flex-col sm:flex-row gap-4 justify-center items-center mb-8">
              <div className="relative flex-1 max-w-md">
                <input
                  type="text"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder="github.com/user/repo or /path/to/repo"
                  className="w-full px-6 py-4 rounded-lg border font-medium transition-all focus:outline-none focus:ring-2"
                  style={{
                    fontFamily: 'var(--font-jetbrains), monospace',
                    fontSize: '14px',
                    borderColor: outlineVariant,
                    backgroundColor: '#ffffff',
                    color: onSurface,
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && handleScan()}
                />
                <div className="absolute -top-3 -right-3 hidden md:block animate-bounce">
                  <div className="px-2 py-1 rounded-md border text-sm" style={{ backgroundColor: mintAccent, borderColor: 'rgba(65,4,218,0.2)', color: primary, fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px' }}>
                    Fast & Isolated!
                  </div>
                </div>
              </div>
              <button
                onClick={handleScan}
                disabled={loading || !target.trim()}
                className="px-8 py-4 rounded-lg font-bold text-lg transition-all hover:scale-[1.02] active:scale-95 disabled:opacity-50 flex items-center gap-3 hard-shadow"
                style={{ backgroundColor: primary, color: onPrimary }}
              >
                {loading ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Scanning...
                  </>
                ) : (
                  <>
                    <Cloud className="w-5 h-5" />
                    Scan Private Repo
                  </>
                )}
              </button>
            </div>

            {/* Status / Error / Findings (preserved) */}
            {error && (
              <div className="mb-6 rounded-lg border px-4 py-3 text-sm" style={{ borderColor: 'rgba(186,26,26,0.2)', backgroundColor: 'rgba(186,26,26,0.05)', color: '#ba1a1a' }}>
                {error}
              </div>
            )}

            {status && !error && status !== 'idle' && (
              <div className="mb-6 flex items-center justify-center gap-2 text-sm" style={{ color: '#474556' }}>
                <span className={`inline-block w-2 h-2 rounded-full ${status === 'completed' ? 'bg-[#10B981]' : status === 'failed' ? 'bg-[#EF4444]' : 'bg-[#F59E0B] animate-pulse'}`} />
                Status: <span className="font-semibold">{status}</span>
                {scanId && <span className="text-xs opacity-60" style={{ fontFamily: 'var(--font-jetbrains), monospace' }}>ID: {scanId}</span>}
              </div>
            )}

            {findings && findings.length > 0 && (
              <div className="space-y-3 text-left max-w-2xl mx-auto">
                <h3 className="text-lg font-semibold text-center" style={{ fontFamily: 'var(--font-libre), serif', color: onSurface }}>
                  Findings ({findings.length})
                </h3>
                {findings.map((f, i) => (
                  <div key={i} className="rounded-lg border p-4" style={{ borderColor: outlineVariant, backgroundColor: '#ffffff' }}>
                    <pre className="text-xs overflow-auto whitespace-pre-wrap" style={{ fontFamily: 'var(--font-jetbrains), monospace', color: '#474556' }}>{JSON.stringify(f, null, 2)}</pre>
                  </div>
                ))}
              </div>
            )}

            {findings && findings.length === 0 && status === 'completed' && (
              <div className="rounded-lg border px-4 py-3 text-sm" style={{ borderColor: 'rgba(16,185,129,0.2)', backgroundColor: 'rgba(16,185,129,0.05)', color: '#10B981' }}>
                No findings — scan completed clean.
              </div>
            )}
          </div>
        </section>

        {/* ═══════════════════════════════════════
            SOCIAL PROOF
            ═══════════════════════════════════════ */}
        <section className="py-12 border-y" style={{ backgroundColor: surface, borderColor: 'rgba(201,196,217,0.2)' }}>
          <div className="max-w-[1200px] mx-auto px-4 md:px-12 flex flex-col md:flex-row items-center justify-between gap-8">
            <p style={{ fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px', fontWeight: 700, letterSpacing: '0.05em', color: outline }}>
              TRUSTED BY VIBE-CODERS AT
            </p>
            <div className="flex flex-wrap justify-center gap-10 md:gap-16 opacity-40 grayscale">
              {['TECH_CORP', 'VIBELABS', 'MODERN_AI', 'SUDO_APPS'].map((name) => (
                <div key={name} style={{ fontFamily: 'var(--font-libre), serif', fontSize: '24px', fontWeight: 700 }}>{name}</div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            3-TIER AUDIT PIPELINE
            ═══════════════════════════════════════ */}
        <section id="pipeline" className="max-w-[1200px] mx-auto px-4 md:px-12 py-24 md:py-40">
          <div className="text-center mb-24 relative">
            <h2 style={{ fontFamily: 'var(--font-libre), serif', fontSize: 'clamp(28px, 3vw, 48px)', fontWeight: 600, lineHeight: 1.2, color: onSurface }}>
              The 3-Tier Audit Pipeline
            </h2>
            <div className="h-1 w-24 rounded-full mx-auto mt-4" style={{ backgroundColor: primary }} />
            <p className="mt-4 max-w-xl mx-auto" style={{ color: '#474556' }}>
              Engineered for depth, speed, and autonomous remediation.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Tier 1: Static Semantic Scan */}
            <div className="p-6 border rounded-xl transition-all hover:shadow-xl hover:-translate-y-1 group" style={{ backgroundColor: '#ffffff', borderColor: 'rgba(201,196,217,0.4)' }}>
              <div className="w-14 h-14 rounded-2xl flex items-center justify-center mb-6" style={{ backgroundColor: lavenderAccent }}>
                <Terminal className="w-7 h-7" style={{ color: primary }} />
              </div>
              <h3 style={{ fontFamily: 'var(--font-libre), serif', fontSize: '22px', fontWeight: 600, marginBottom: '16px', color: onSurface }}>
                1. Static Semantic Scan
              </h3>
              <p className="leading-relaxed mb-6" style={{ color: '#474556' }}>
                AST analysis + secret detection with LLM semantic depth. We don&apos;t just match patterns; we understand developer intent.
              </p>
              <div className="p-4 rounded-lg overflow-hidden" style={{ backgroundColor: inverseSurface }}>
                <div className="terminal-dots mb-2"><span /><span /><span /></div>
                <div style={{ fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px', color: secondaryFixedDim }}>$ antivibe scan . --deep</div>
                <div style={{ fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px', color: '#ba1a1a', marginTop: '4px' }}>[!] Semantic match: Security Risk</div>
              </div>
            </div>

            {/* Tier 2: Isolated Sandbox */}
            <div className="p-6 border rounded-xl transition-all hover:shadow-xl hover:-translate-y-1 group" style={{ backgroundColor: '#ffffff', borderColor: 'rgba(201,196,217,0.4)' }}>
              <div className="w-full aspect-square mb-6 rounded-2xl overflow-hidden flex items-center justify-center relative" style={{ backgroundColor: 'rgba(209,250,229,0.2)' }}>
                <Image src="/illustrations/sandbox.png" alt="Isolated Sandbox" width={300} height={300} className="w-4/5 h-4/5 object-contain" />
              </div>
              <h3 style={{ fontFamily: 'var(--font-libre), serif', fontSize: '22px', fontWeight: 600, marginBottom: '16px', color: onSurface }}>
                2. Isolated Sandbox
              </h3>
              <p className="leading-relaxed" style={{ color: '#474556' }}>
                We spin up your app in an ephemeral Fly.io microVM with mock seeded DBs to execute and verify code safely in real-time.
              </p>
            </div>

            {/* Tier 3: Agentic Fuzzing */}
            <div className="p-6 border rounded-xl transition-all hover:shadow-xl hover:-translate-y-1 group" style={{ backgroundColor: '#ffffff', borderColor: 'rgba(201,196,217,0.4)' }}>
              <div className="w-full aspect-square mb-6 rounded-2xl overflow-hidden flex items-center justify-center" style={{ backgroundColor: 'rgba(255,237,213,0.2)' }}>
                <Image src="/illustrations/fuzzing.png" alt="Agentic Fuzzing" width={300} height={300} className="w-4/5 h-4/5 object-contain" />
              </div>
              <h3 style={{ fontFamily: 'var(--font-libre), serif', fontSize: '22px', fontWeight: 600, marginBottom: '16px', color: onSurface }}>
                3. Agentic Fuzzing
              </h3>
              <p className="leading-relaxed" style={{ color: '#474556' }}>
                Our agent forges identities and never stops at a 403. It finds the complex logic flaws that static tools always miss.
              </p>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            DEEP SECURITY / TERMINAL SECTION
            ═══════════════════════════════════════ */}
        <section id="security" className="py-24 md:py-40 overflow-hidden" style={{ backgroundColor: '#1e1b4b', color: '#ffffff' }}>
          <div className="max-w-[1200px] mx-auto px-4 md:px-12 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
            <div>
              <h2 style={{ fontFamily: 'var(--font-libre), serif', fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.02em', marginBottom: '32px' }}>
                Deep security<br />without the friction.
              </h2>
              <div className="space-y-8">
                <div className="flex gap-4 items-start">
                  <div className="shrink-0 w-14 h-14 rounded-xl flex items-center justify-center" style={{ backgroundColor: 'rgba(90,56,241,0.2)' }}>
                    <Image src="/illustrations/auto-pr.png" alt="Auto-PR" width={40} height={40} className="w-10 h-10" />
                  </div>
                  <div>
                    <h4 className="font-bold text-lg mb-1">Auto-Patching Agent</h4>
                    <p className="leading-relaxed" style={{ color: '#c9c4d9' }}>
                      Not just a report. We create the branch and open the PR for you to review, with full context on the fix.
                    </p>
                  </div>
                </div>
                <div className="flex gap-4 items-start">
                  <div className="shrink-0 w-14 h-14 rounded-xl flex items-center justify-center border" style={{ backgroundColor: 'rgba(255,255,255,0.05)', borderColor: 'rgba(255,255,255,0.1)' }}>
                    <Lock className="w-7 h-7" style={{ color: secondaryFixedDim }} />
                  </div>
                  <div>
                    <h4 className="font-bold text-lg mb-1">JWT Forgery Engine</h4>
                    <p className="leading-relaxed" style={{ color: '#c9c4d9' }}>
                      Simulates complex identity attacks to ensure your auth is rock solid across all API versions.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Terminal Window */}
            <div className="relative">
              <div className="p-6 rounded-xl border shadow-2xl" style={{ backgroundColor: '#1e1e2e', borderColor: 'rgba(255,255,255,0.1)' }}>
                <div className="flex gap-2 mb-6">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: '#ff5f56' }} />
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: '#ffbd2e' }} />
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: '#27c93f' }} />
                </div>
                <div ref={terminalRef} className="space-y-2" style={{ fontFamily: 'var(--font-jetbrains), monospace', fontSize: '14px', lineHeight: '20px' }}>
                  <div className="terminal-line" style={{ color: secondaryFixedDim }}>@antivibe/detective-bird running...</div>
                  <div className="terminal-line" style={{ color: 'rgba(255,255,255,0.7)' }}>Analyzing /api/user/v1/profile...</div>
                  <div className="terminal-line p-2 border-l-2" style={{ backgroundColor: 'rgba(186,26,26,0.2)', borderColor: '#ba1a1a', color: '#ffdad6' }}>
                    VULNERABILITY: Broken Object Level Authorization (BOLA)
                  </div>
                  <div className="terminal-line" style={{ color: mintAccent }}>Generating fix: auth_middleware.ts...</div>
                  <div className="terminal-line" style={{ color: mintAccent }}>Opening PR: #402 Fix BOLA vulnerability</div>
                </div>
              </div>
              {/* Bird Mascot Artifact */}
              <div className="absolute -right-6 -bottom-6">
                <div className="p-3 rounded-full border shadow-xl" style={{ backgroundColor: surface, borderColor: onSurface }}>
                  <Search className="w-8 h-8" style={{ color: primary }} />
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════════════════════════════
            BOTTOM CTA — Sketchy Border
            ═══════════════════════════════════════ */}
        <section id="cta" className="max-w-[1200px] mx-auto px-4 md:px-12 py-24 md:py-32 text-center">
          <div className="sketchy-border p-12 md:p-16 relative overflow-hidden" style={{ backgroundColor: 'rgba(245,243,255,0.5)' }}>
            <h2 style={{ fontFamily: 'var(--font-libre), serif', fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 700, lineHeight: 1.1, letterSpacing: '-0.02em', marginBottom: '24px', color: onSurface }}>
              Ready to secure the vibe?
            </h2>
            <p className="mb-10 max-w-xl mx-auto" style={{ fontSize: '18px', lineHeight: '28px', color: '#474556' }}>
              No credit card required. Start with one free scan to see what&apos;s lurking in your AI-generated routes. Just $19/mo for pro.
            </p>
            <div className="flex flex-col items-center gap-4">
              <button className="px-14 py-5 rounded-lg font-bold text-xl transition-all hover:scale-[1.02] active:scale-95 hard-shadow" style={{ backgroundColor: primary, color: onPrimary }}>
                Claim 1 Free Scan
              </button>
              <p style={{ fontFamily: 'var(--font-jetbrains), monospace', fontSize: '12px', fontWeight: 700, letterSpacing: '0.05em', color: '#474556' }}>
                TRUSTED BY 2,000+ DEVELOPERS
              </p>
            </div>
            {/* Floating Decorative Artifacts */}
            <div className="absolute top-10 right-10 opacity-10 rotate-12 pointer-events-none hidden md:block">
              <Shield className="w-32 h-32" style={{ color: onSurface }} />
            </div>
            <div className="absolute bottom-10 left-10 opacity-10 -rotate-12 pointer-events-none hidden md:block">
              <Bug className="w-32 h-32" style={{ color: onSurface }} />
            </div>
          </div>
        </section>

      </main>

      {/* ═══════════════════════════════════════
          FOOTER
          ═══════════════════════════════════════ */}
      <footer className="w-full py-16 px-4 md:px-12 border-t" style={{ backgroundColor: surface, borderColor: 'rgba(201,196,217,0.3)' }}>
        <div className="max-w-[1200px] mx-auto grid grid-cols-2 md:grid-cols-4 gap-12">
          <div className="col-span-2 md:col-span-1">
            <div className="mb-6" style={{ fontFamily: 'var(--font-libre), serif', fontSize: '24px', fontWeight: 700, color: primary }}>
              AntiVibe
            </div>
            <p className="text-sm leading-relaxed" style={{ color: '#474556' }}>
              &copy; 2024 AntiVibe.<br />Isolated, agentic security for modern AI stacks.
            </p>
          </div>
          <div>
            <h4 className="font-bold mb-6 uppercase text-xs tracking-widest" style={{ color: onSurface }}>Product</h4>
            <ul className="space-y-4 text-sm">
              <li><a href="#pipeline" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Features</a></li>
              <li><a href="#cta" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Pricing</a></li>
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>CLI Docs</a></li>
            </ul>
          </div>
          <div>
            <h4 className="font-bold mb-6 uppercase text-xs tracking-widest" style={{ color: onSurface }}>Company</h4>
            <ul className="space-y-4 text-sm">
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>About</a></li>
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Security</a></li>
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Blog</a></li>
            </ul>
          </div>
          <div>
            <h4 className="font-bold mb-6 uppercase text-xs tracking-widest" style={{ color: onSurface }}>Legal</h4>
            <ul className="space-y-4 text-sm">
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Privacy</a></li>
              <li><a href="#" className="hover:text-[#4104da] transition-colors" style={{ color: '#474556' }}>Terms</a></li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}
