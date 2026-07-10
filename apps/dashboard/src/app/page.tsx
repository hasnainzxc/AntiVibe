'use client'

import { useState, useCallback, useRef } from 'react'
import Image from 'next/image'

/* ────────────────────────────────
   AntiVibe Landing Page — Fly.io 1:1 Replication
   Full section structure matching fly.io landing page
   ──────────────────────────────── */

const FEATURES = [
  { title: 'Static Semantic Scan', desc: 'AST analysis + secret detection with LLM semantic depth. We understand developer intent, not just patterns.', icon: 'M9 2v6h6V2M9 2H5v6h4M15 2h4v6h-4M5 8v12h14V8M5 8h14M9 14h6' },
  { title: 'Isolated Sandbox', desc: 'Spin up your app in an ephemeral microVM with mock seeded DBs. Execute and verify safely in real-time.', icon: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z' },
  { title: 'Agentic Fuzzing', desc: 'Our agent forges identities and never stops at a 403. It finds complex logic flaws that static tools miss.', icon: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
  { title: 'Auto-PR Remediation', desc: 'Not just a report. We create the branch, write the patch, and open the PR — you just review and merge.', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' },
  { title: 'JWT Forgery Engine', desc: 'Simulates complex identity attacks — forge tokens for dummy tenants, probe cross-tenant access vectors.', icon: 'M12 1l3 6 6 1-4 4 1 6-6-3-6 3 1-6-4-4z' },
  { title: 'Secrets Detection', desc: 'Regex patterns + entropy analysis + LLM verification. Catches hardcoded API keys, open Firestore rules, CORS wildcards.', icon: 'M12 15v2m-6 4h12a2 2 0 0 0 2-2v-5a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2zm10-10V7a4 4 0 0 0-8 0v4' },
]

const STACKS = ['Next.js', 'Express', 'Python', 'Django', 'Flask', 'React']

const ENTERPRISE_FEATURES = [
  { title: 'AntiVibe Security', desc: 'Every scan runs in an isolated KVM-style microVM with iptables egress DENY ALL.', img: 'secrets.png' },
  { title: 'Sandbox Isolation', desc: 'Sandboxed execution — untrusted code never touches your production infrastructure.', img: 'sandbox.png' },
  { title: 'Guaranteed Response', desc: 'Critical vulnerability alerts delivered within minutes of detection, not hours.', img: 'sql-injection.png' },
  { title: 'SOC2 Aligned', desc: 'Audit-ready scan logs, encrypted PoC captures, and full egress trail for compliance.', img: 'bola.png' },
  { title: 'Memory-safe Stack', desc: 'Scanner built on Python 3.12 with asyncio — no buffer overflows, no memory leaks in the pipeline.', img: 'fuzzing.png' },
  { title: 'CI/CD Integration', desc: 'Drop AntiVibe into your GitHub Actions workflow. Scan on every PR, block on every vuln.', img: 'auto-pr.png' },
]

const TRUSTED_BY = ['VibeLabs', 'ModernAI', 'TechCorp', 'SudoApps', 'NeonDev', 'ShipFast']

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

      {/* ═══ NAVBAR — Floating Pill (Fly.io style) ═══ */}
      <header className="fixed top-5 left-1/2 -translate-x-1/2 z-50">
        <nav className="flex items-center gap-1 px-2 py-2 rounded-full bg-white/70 backdrop-blur-xl shadow-[0_1px_3px_rgba(0,0,0,0.05)] border border-[#e7e6f4]/60">
          <div className="flex items-center gap-2 px-4 py-1.5">
            <div className="w-6 h-6 rounded-full bg-[#7c3aed] flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <span className="font-body text-[15px] font-semibold text-[#281950]">AntiVibe</span>
          </div>

          <div className="hidden md:flex items-center gap-1 px-2">
            {['Products', 'Docs', 'Pricing'].map((item) => (
              <a key={item} href={`#${item.toLowerCase()}`} className="px-3 py-1.5 rounded-full font-body text-[14px] font-medium text-[#5e537c] hover:text-[#281950] hover:bg-[#f1f2f9]/80 transition-all">
                {item}
              </a>
            ))}
          </div>

          <div className="flex items-center gap-2 px-2">
            <button className="px-4 py-1.5 rounded-full font-body text-[14px] font-medium text-[#5e537c] hover:text-[#281950] transition-colors">Sign In</button>
            <button className="px-4 py-1.5 rounded-full font-body text-[14px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] transition-colors">Get Started</button>
          </div>
        </nav>
      </header>

      <main>

        {/* ═══ HERO — Full Viewport ═══ */}
        <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden pt-20">
          <div className="absolute inset-0 z-0">
            <Image src="/illustrations/hero-thought-cloud.jpg" alt="" fill className="object-cover object-center" priority sizes="100vw" />
          </div>

          <div className="relative z-10 text-center max-w-[720px] px-6">
            <h1 className="font-display text-[clamp(36px,5vw,64px)] font-medium leading-[1.15] tracking-[-0.045em] text-[#281950]">
              Stop the bad vibes.<br />
              <em className="italic font-medium">in your AI code.</em>
            </h1>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] max-w-[560px] mx-auto mt-6">
              For builders who ship fast and need security that keeps up. Paste a repo URL, get a full audit with patches you can merge.
            </p>

            {/* Scan Form */}
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
                {loading ? (<><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Scanning...</>) : (<>Scan your repo<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg></>)}
              </button>
            </div>

            {/* Status / Error / Findings */}
            {error && (
              <div className="mt-4 rounded-xl bg-red-50 border border-red-100 px-4 py-3 text-sm font-body text-red-700 max-w-[480px] mx-auto">{error}</div>
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
                <h3 className="font-display text-[22px] font-medium text-[#281950] text-center">Findings ({findings.length})</h3>
                {findings.map((f: any, i: number) => (
                  <div key={i} className="rounded-xl bg-white/80 backdrop-blur-sm border border-[#e7e6f4] p-4">
                    <pre className="text-xs overflow-auto whitespace-pre-wrap font-mono text-[#5e537c]">{JSON.stringify(f, null, 2)}</pre>
                  </div>
                ))}
              </div>
            )}
            {findings && findings.length === 0 && status === 'completed' && (
              <div className="mt-4 rounded-xl bg-green-50 border border-green-100 px-4 py-3 text-sm font-body text-green-700 max-w-[480px] mx-auto">No findings — scan completed clean.</div>
            )}
          </div>
        </section>

        {/* ═══ "You Ship. We Protect." ═══ */}
        <section className="py-24 md:py-32 border-t border-[#e7e6f4]">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
            <div>
              <p className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#7c3aed] mb-4">The AntiVibe Way</p>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-6">
                You ship. <em className="italic">We protect and test it.</em>
              </h2>
              <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-6">
                For builders who need security that keeps up with their ideas. Every scan runs a three-tier pipeline — static analysis, isolated sandboxing, and autonomous fuzz testing. Land patches you can merge in minutes.
              </p>
              <div className="w-10 h-0.5 bg-[#e7e6f4] mb-6" />
              <a href="#products" className="font-body text-[15px] font-semibold text-[#7c3aed] hover:text-[#6d28d9] transition-colors inline-flex items-center gap-1">
                Check it out!
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
              </a>
            </div>
            <div className="relative">
              <Image src="/illustrations/sandbox.png" alt="AntiVibe Sandbox" width={480} height={480} className="w-full h-auto rounded-2xl" />
            </div>
          </div>
        </section>

        {/* ═══ "Scans That Find Everything You Need" — feature grid ═══ */}
        <section id="products" className="py-24 md:py-32 bg-white border-y border-[#e7e6f4]">
          <div className="max-w-[1200px] mx-auto px-6">
            <div className="max-w-[720px] mb-16">
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-4">
                Scans That Find <em className="italic">Everything You Need</em>
              </h2>
              <p className="font-body text-[18px] leading-[30px] text-[#5e537c]">
                Spin up isolated sandboxes for running AI-generated code in complete safety. Every scan is a self-contained audit, ready in minutes. Checkpoint, test, and pay only for actual scan time.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {FEATURES.map((f, i) => (
                <div key={i} className="p-8 rounded-2xl bg-[#f8f9fe] border border-[#e7e6f4] hover:shadow-lg hover:-translate-y-1 transition-all">
                  <div className="w-12 h-12 rounded-xl bg-white border border-[#e7e6f4] flex items-center justify-center mb-6">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d={f.icon} />
                    </svg>
                  </div>
                  <h3 className="font-display text-[20px] font-medium tracking-[-0.025em] text-[#281950] mb-3">{f.title}</h3>
                  <p className="font-body text-[15px] leading-[24px] text-[#5e537c]">{f.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ "Scan the Stack You Love" ═══ */}
        <section className="py-24 md:py-32">
          <div className="max-w-[1200px] mx-auto px-6 text-center">
            <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-4">
              Scan the Stack You Love
            </h2>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] max-w-[560px] mx-auto mb-12">
              Build with your favorite framework. We detect and scan it automatically — no config needed.
            </p>
            <div className="flex flex-wrap justify-center gap-4 md:gap-8">
              {STACKS.map((stack) => (
                <div key={stack} className="px-8 py-4 rounded-xl bg-white border border-[#e7e6f4] hover:shadow-md transition-all cursor-pointer">
                  <span className="font-display text-[18px] font-semibold text-[#281950]">{stack}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ "Trusted by teams at" ═══ */}
        <section className="py-16 border-y border-[#e7e6f4] bg-white">
          <div className="max-w-[1200px] mx-auto px-6 text-center">
            <p className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#a39ac1] mb-8">
              Trusted by teams at
            </p>
            <div className="flex flex-wrap justify-center gap-8 md:gap-16">
              {TRUSTED_BY.map((name) => (
                <span key={name} className="font-display text-[20px] font-semibold text-[#281950] opacity-40">{name}</span>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ "Enterprise-Ready" ═══ */}
        <section className="py-24 md:py-32 bg-[#191034] text-white">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16">
            <div>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] mb-6">
                Enterprise-Ready
              </h2>
              <p className="font-body text-[18px] leading-[30px] text-[#a39ac1] mb-8">
                Apps running on AntiVibe are isolated in KVM-style sandboxes, built on a memory-safe stack and running directly on our own infrastructure.
              </p>
              <div className="w-10 h-0.5 bg-white/10 mb-8" />
              <p className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#c8bfff] mb-4">Enterprise Features</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {ENTERPRISE_FEATURES.map((feat, i) => (
                <div key={i} className="flex flex-col gap-3 p-5 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-all">
                  <div className="w-14 h-14 rounded-xl overflow-hidden flex items-center justify-center bg-white/5">
                    <Image src={`/illustrations/${feat.img}`} alt={feat.title} width={56} height={56} className="w-full h-full object-cover" />
                  </div>
                  <h4 className="font-body text-[15px] font-semibold text-white">{feat.title}</h4>
                  <p className="font-body text-[14px] leading-[22px] text-[#a39ac1]">{feat.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ Terminal / Deep Security section ═══ */}
        <section className="py-24 md:py-32">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-6">
                Deep security<br />without the friction.
              </h2>
              <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-6">
                Not just a report. We create the branch, write the patch, and open the PR — with full context on every fix.
              </p>
              <div className="w-10 h-0.5 bg-[#e7e6f4] mb-6" />
              <a href="#" className="font-body text-[15px] font-semibold text-[#7c3aed] hover:text-[#6d28d9] transition-colors inline-flex items-center gap-1">
                Learn More
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
              </a>
            </div>
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
                  <div className="px-3 py-2 rounded-lg bg-red-500/10 border-l-2 border-red-400 text-red-200">VULNERABILITY: Broken Object Level Authorization</div>
                  <div className="text-green-300">Generating fix: auth_middleware.ts...</div>
                  <div className="text-green-300">Opening PR: #402 Fix BOLA vulnerability</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ═══ Final CTA — "Ship Whatever You Can Think Up" ═══ */}
        <section id="pricing" className="py-24 md:py-40 bg-gradient-to-b from-[#f1f2f9] to-[#e7e6f4]">
          <div className="max-w-[720px] mx-auto px-6 text-center">
            <h2 className="font-display text-[clamp(32px,4vw,48px)] font-medium leading-[1.15] tracking-[-0.045em] text-[#281950] mb-6">
              Ship Whatever You Can Think Up <em className="italic">(and let us catch what breaks)</em>
            </h2>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-10 max-w-[480px] mx-auto">
              AntiVibe is the platform that gets out of your way. Scan any code without fear. See how fast you can ship safely.
            </p>
            <button className="px-8 py-4 rounded-full font-body text-[16px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] active:scale-95 transition-all inline-flex items-center gap-2 shadow-lg shadow-[#7c3aed]/20">
              Spin Up a Scan
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
            </button>
          </div>
        </section>

      </main>

      {/* ═══ FOOTER — Full Fly.io structure ═══ */}
      <footer className="bg-[#191034] text-white pt-20 pb-10">
        <div className="max-w-[1200px] mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-12 mb-16">
            {/* Brand */}
            <div className="col-span-2 md:col-span-1">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-6 h-6 rounded-full bg-[#7c3aed] flex items-center justify-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <span className="font-display text-[20px] font-semibold">AntiVibe</span>
              </div>
              <p className="font-body text-[14px] leading-[22px] text-[#a39ac1]">Agentic DevSecOps for vibe-coded apps.</p>
            </div>

            {/* Company */}
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Company</h4>
              <ul className="space-y-3">
                {['About', 'Pricing', 'Articles', 'Blog', 'Docs'].map((item) => (
                  <li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>

            {/* Resources */}
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Resources</h4>
              <ul className="space-y-3">
                {['Docs', 'Customers', 'Support', 'Status', 'GitHub', 'Twitter', 'Community'].map((item) => (
                  <li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>

            {/* Legal */}
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Legal</h4>
              <ul className="space-y-3">
                {['Security', 'Privacy', 'Terms of Service', 'Acceptable Use'].map((item) => (
                  <li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>
          </div>

          <div className="pt-8 border-t border-white/10">
            <p className="font-body text-[13px] text-[#a39ac1]">
              &copy; 2026 AntiVibe. Isolated, agentic security for modern AI stacks.
            </p>
          </div>
        </div>
      </footer>
    </div>
  )
}