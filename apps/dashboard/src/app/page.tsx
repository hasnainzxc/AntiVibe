'use client'

import { useState, useCallback, useRef } from 'react'
import Image from 'next/image'
import { ScanTracker } from '@/components/scan-tracker'

/* ────────────────────────────────
   AntiVibe Landing Page — Fly.io 1:1
   Alternating two-column layout: text + illustration, flip each section
   ──────────────────────────────── */

const ALTERNATING_SECTIONS = [
  { title: 'Scans That Find Everything You Need', desc: 'Spin up isolated sandboxes for running AI-generated code in complete safety. Every scan is a self-contained audit, ready in minutes. Checkpoint, test, and pay only for actual scan time.', img: 'sandbox.png', cta: 'Learn More' },
  { title: 'Secrets Detection That Keeps Up', desc: 'Fast regex patterns for low-latency detection, plus entropy analysis and LLM verification for data that needs deeper context. Snapshot environments, persist findings, and scale alongside your codebase.', img: 'secrets.png', cta: 'Learn More' },
  { title: 'Built-In JWT Forgery', desc: 'Private token forging per sandbox, granular endpoint probing, and identity-based attack simulation — all automatic. We forge tokens for dummy tenants and probe cross-tenant access vectors.', img: 'fuzzing.png', cta: 'Learn More' },
  { title: 'Auto-PRs That Do Everything You Need', desc: 'Everything runs on AntiVibe: your scans, agents that scale to millions of lines, and AI-generated code. We create the branch, write the patch, and open the PR — you just review and merge.', img: 'auto-pr.png', cta: 'Learn More' },
  { title: 'Fork Off Scans Like They\u2019re Processes', desc: 'AntiVibe scans start fast enough to run on every PR, execute only when you need them, and scale into tens of thousands of lines. No Terraform required to find what breaks.', img: 'sql-injection.png', cta: 'Learn More' },
  { title: 'Built for BOLA Detection', desc: 'Run clustered endpoint fuzzing, globally-distributed route discovery, and modern auth-pivot systems. AntiVibe pivots on 403s instead of giving up — finding the complex logic flaws static tools miss.', img: 'bola.png', cta: 'Learn More' },
]

const STACKS = ['Next.js', 'Express', 'Python', 'Django', 'Flask', 'React']

const ENTERPRISE_FEATURES = [
  { title: 'AntiVibe Security', desc: 'Every scan runs in an isolated KVM-style microVM with iptables egress DENY ALL.', img: 'secrets.png' },
  { title: 'Sandbox Isolation', desc: 'Sandboxed execution — untrusted code never touches your production infrastructure.', img: 'sandbox.png' },
  { title: 'Guaranteed Response', desc: 'Critical vulnerability alerts delivered within minutes of detection, not hours.', img: 'sql-injection.png' },
  { title: 'SOC2 Aligned', desc: 'Audit-ready scan logs, encrypted PoC captures, and full egress trail for compliance.', img: 'bola.png' },
  { title: 'Memory-safe Stack', desc: 'Scanner built on Python 3.12 with asyncio — no buffer overflows, no memory leaks.', img: 'fuzzing.png' },
  { title: 'CI/CD Integration', desc: 'Drop AntiVibe into your GitHub Actions workflow. Scan on every PR, block on every vuln.', img: 'auto-pr.png' },
]

const TRUSTED_BY = ['VibeLabs', 'ModernAI', 'TechCorp', 'SudoApps', 'NeonDev', 'ShipFast']

export default function Home() {
  const [target, setTarget] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [findings, setFindings] = useState<any[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const pollStatus = useCallback((id: string) => {
    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/scan?scan_id=${encodeURIComponent(id)}`)
        if (!res.ok) { clearInterval(pollingRef.current!); setLoading(false); setStatus('error'); setError('Failed to poll scan status'); return }
        const data = await res.json()
        setStatus(data.status)
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollingRef.current!); setLoading(false)
          if (data.findings) setFindings(data.findings)
          if (data.error) setError(data.error)
        }
      } catch { clearInterval(pollingRef.current!); setLoading(false); setError('Polling failed') }
    }, 2000)
  }, [])

  const handleScan = useCallback(async () => {
    if (!target.trim()) return
    if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
    setLoading(true); setError(null); setStatus('starting'); setFindings(null); setScanId(null)
    try {
      const res = await fetch('/api/scan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo_url: target.trim() }) })
      if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(data.error || `Server responded with ${res.status}`) }
      const data = await res.json()
      setScanId(data.scan_id); const s = data.status || 'running'; setStatus(s)
      if (s !== 'completed' && s !== 'failed') { pollStatus(data.scan_id) } else { setLoading(false); if (data.findings) setFindings(data.findings); if (data.error) setError(data.error) }
    } catch (err: unknown) { const msg = err instanceof Error ? err.message : 'Unknown error'; setError(msg); setLoading(false) }
  }, [target, pollStatus])

  return (
    <div className="flex flex-col min-h-screen bg-[#f1f2f9]">

      {/* ═══ NAVBAR — Floating Pill ═══ */}
      <header className="fixed top-5 left-1/2 -translate-x-1/2 z-50">
        <nav className="flex items-center gap-1 px-2 py-2 rounded-full bg-white/75 bg-gradient-to-r from-pink-200/40 via-violet-200/40 to-indigo-200/40 border border-white/50 shadow-lg shadow-gray-800/5 ring-1 ring-gray-800/[.075] backdrop-blur-xl">
          <div className="flex items-center gap-2 px-4 py-1.5">
            <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[#ba7bf0] to-[#5046e4] flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <span className="font-body text-[15px] font-semibold text-[#281950]">AntiVibe</span>
          </div>
          <div className="hidden md:flex items-center gap-1 px-2">
            {['Products', 'Docs', 'Pricing'].map((item) => (
              <a key={item} href={`#${item.toLowerCase()}`} className="px-3 py-1.5 rounded-full font-body text-[14px] font-medium text-[#5e537c] hover:text-violet-600 transition-colors">{item}</a>
            ))}
          </div>
          <div className="flex items-center gap-1 px-2 border-l border-white/30">
            <button className="px-4 py-1.5 rounded-l-full rounded-r-lg font-body text-[14px] font-medium text-[#281950] bg-white/40 hover:text-violet-600 hover:bg-violet-50/40 transition-colors">Sign In</button>
            <button className="px-4 py-1.5 rounded-r-full rounded-l-lg font-body text-[14px] font-semibold text-white bg-[#5046e4] hover:bg-[#4d7cfe] transition-colors">Get Started</button>
          </div>
        </nav>
      </header>

      <main>

        {/* ═══ HERO ═══ */}
        <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden pt-20">
          <div className="absolute inset-0 z-0">
            <Image src="/illustrations/hero-thought-cloud.jpg" alt="" fill className="object-cover object-center" priority sizes="100vw" />
          </div>
          <div className="relative z-10 text-center max-w-[720px] px-6">
            <h1 className="font-display text-[clamp(36px,5vw,64px)] font-medium leading-[1.15] tracking-[-0.045em] text-[#281950]">
              Stop the bad vibes.<br /><em className="italic font-medium">in your AI code.</em>
            </h1>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] max-w-[560px] mx-auto mt-6">
              For builders who ship fast and need security that keeps up. Paste a repo URL, get a full audit with patches you can merge.
            </p>
            <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3 max-w-[480px] mx-auto">
              <input type="text" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="github.com/user/repo"
                className="w-full sm:flex-1 px-5 py-3 rounded-full border border-[#e7e6f4] bg-white/90 backdrop-blur-sm font-body text-[15px] text-[#281950] placeholder:text-[#a39ac1] focus:outline-none focus:ring-2 focus:ring-[#7c3aed]/30 focus:border-[#7c3aed] transition-all"
                onKeyDown={(e) => e.key === 'Enter' && handleScan()} />
              <button onClick={handleScan} disabled={loading || !target.trim()}
                className="w-full sm:w-auto px-6 py-3 rounded-full font-body text-[15px] font-semibold text-white bg-[#7c3aed] hover:bg-[#6d28d9] active:scale-95 disabled:opacity-50 transition-all flex items-center justify-center gap-2">
                {loading ? (<><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Scanning...</>) : (<>Scan your repo<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg></>)}
              </button>
            </div>
          </div>
        </section>

        {/* ═══ SCAN TRACKER ═══ */}
        <ScanTracker
          target={target}
          scanId={scanId}
          status={status}
          findings={findings}
          error={error}
          loading={loading}
        />

        {/* ═══ ALTERNATING TWO-COLUMN SECTIONS ═══ */}
        {ALTERNATING_SECTIONS.map((section, idx) => {
          const isReversed = idx % 2 === 1 // odd sections: image left, text right
          return (
            <section key={idx} className={`py-24 md:py-32 ${idx % 2 === 0 ? 'border-t border-[#e7e6f4]' : 'bg-white border-y border-[#e7e6f4]'}`}>
              <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
                {/* Text Column */}
                <div className={isReversed ? 'md:order-2' : 'md:order-1'}>
                  <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-6">
                    {section.title}
                  </h2>
                  <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-6 max-w-[480px]">
                    {section.desc}
                  </p>
                  <div className="w-10 h-px bg-[#e7e6f4] mb-6" />
                  <a href="#" className="font-body text-[15px] font-semibold text-[#7c3aed] hover:text-[#6d28d9] transition-colors inline-flex items-center gap-1">
                    {section.cta}
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                  </a>
                </div>
                {/* Image Column */}
                <div className={isReversed ? 'md:order-1' : 'md:order-2'}>
                  <div className="relative w-full max-w-[480px] mx-auto">
                    <Image src={`/illustrations/${section.img}`} alt={section.title} width={480} height={480} className="w-full h-auto" />
                  </div>
                </div>
              </div>
            </section>
          )
        })}

        {/* ═══ SCAN THE STACK YOU LOVE ═══ */}
        <section className="py-24 md:py-32 border-t border-[#e7e6f4]">
          <div className="max-w-[1200px] mx-auto px-6 text-center">
            <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-4">
              Scan the Stack You Love
            </h2>
            <p className="font-body text-[18px] leading-[30px] text-[#5e537c] max-w-[560px] mx-auto mb-4">
              Build with your favorite framework. We detect and scan it automatically.
            </p>
            <div className="w-10 h-px bg-[#e7e6f4] mx-auto mb-12" />
            <div className="flex flex-wrap justify-center gap-4 md:gap-8">
              {STACKS.map((stack) => (
                <div key={stack} className="px-6 py-3 rounded-xl bg-white border border-[#e7e6f4] hover:shadow-md transition-all cursor-pointer">
                  <span className="font-display text-[18px] font-semibold text-[#281950]">{stack}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ═══ TRUSTED BY ═══ */}
        <section className="py-16 border-y border-[#e7e6f4] bg-white">
          <div className="max-w-[1200px] mx-auto px-6 text-center">
            <p className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-[#a39ac1] mb-8">Trusted by teams at</p>
            <div className="flex flex-wrap justify-center gap-8 md:gap-16">
              {TRUSTED_BY.map((name) => (<span key={name} className="font-display text-[20px] font-semibold text-[#281950] opacity-40">{name}</span>))}
            </div>
          </div>
        </section>

        {/* ═══ ENTERPRISE-READY ═══ */}
        <section className="py-24 md:py-32 bg-[#191034] text-white">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16">
            <div>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] mb-6">Enterprise-Ready</h2>
              <p className="font-body text-[18px] leading-[30px] text-[#a39ac1] mb-8">
                Apps running on AntiVibe are isolated in KVM-style sandboxes, built on a memory-safe stack and running directly on our own infrastructure.
              </p>
              <div className="w-10 h-px bg-white/10 mb-8" />
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

        {/* ═══ DEEP SECURITY ═══ */}
        <section className="py-24 md:py-32">
          <div className="max-w-[1200px] mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="font-display text-[clamp(28px,3vw,36px)] font-medium leading-[1.2] tracking-[-0.025em] text-[#281950] mb-6">
                Deep security<br />without the friction.
              </h2>
              <p className="font-body text-[18px] leading-[30px] text-[#5e537c] mb-6">
                Not just a report. We create the branch, write the patch, and open the PR — with full context on every fix.
              </p>
              <div className="w-10 h-px bg-[#e7e6f4] mb-6" />
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

        {/* ═══ FINAL CTA ═══ */}
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

      {/* ═══ FOOTER ═══ */}
      <footer className="bg-[#191034] text-white pt-20 pb-10">
        <div className="max-w-[1200px] mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-12 mb-16">
            <div className="col-span-2 md:col-span-1">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[#ba7bf0] to-[#5046e4] flex items-center justify-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </div>
                <span className="font-display text-[20px] font-semibold">AntiVibe</span>
              </div>
              <p className="font-body text-[14px] leading-[22px] text-[#a39ac1]">Agentic DevSecOps for vibe-coded apps.</p>
            </div>
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Company</h4>
              <ul className="space-y-3">
                {['About', 'Pricing', 'Articles', 'Blog', 'Docs'].map((item) => (<li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>))}
              </ul>
            </div>
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Resources</h4>
              <ul className="space-y-3">
                {['Docs', 'Customers', 'Support', 'Status', 'GitHub', 'Twitter', 'Community'].map((item) => (<li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>))}
              </ul>
            </div>
            <div>
              <h4 className="font-body text-[12px] font-semibold tracking-[0.05em] uppercase text-white mb-4">Legal</h4>
              <ul className="space-y-3">
                {['Security', 'Privacy', 'Terms of Service', 'Acceptable Use'].map((item) => (<li key={item}><a href="#" className="font-body text-[14px] text-[#a39ac1] hover:text-white transition-colors">{item}</a></li>))}
              </ul>
            </div>
          </div>
          <div className="pt-8 border-t border-white/10">
            <p className="font-body text-[13px] text-[#a39ac1]">&copy; 2026 AntiVibe. Isolated, agentic security for modern AI stacks.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}