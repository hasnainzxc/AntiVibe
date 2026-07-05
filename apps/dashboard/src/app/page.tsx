import { ArrowRight, GitBranch, Search, ShieldCheck } from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { PricingCard } from '@/components/pricing-card'
import { Input } from '@/components/ui/input'

const steps = [
  {
    icon: GitBranch,
    title: 'Paste a GitHub URL',
    desc: 'Any public or private repo. No config needed.',
  },
  {
    icon: Search,
    title: 'We scan it',
    desc: '3-tier pipeline: static analysis, sandbox execution, and fuzzing.',
  },
  {
    icon: ShieldCheck,
    title: 'Get report + auto-PR',
    desc: 'Actionable findings with auto-generated fix PRs.',
  },
]

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Nav */}
      <header className="sticky top-0 z-50 border-b bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="text-lg font-bold tracking-tight">AntiVibe</span>
          <Link
            href="https://github.com/hairzee/AntiVibe"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            GitHub
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b">
        <div className="absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-primary/5" />
        <div className="relative mx-auto max-w-4xl px-4 py-24 text-center sm:py-32">
          <h1 className="text-4xl font-bold tracking-tight sm:text-6xl">
            Paste a GitHub URL.
            <br />
            <span className="text-primary">Get a security report.</span>
          </h1>
          <p className="mt-6 text-lg text-muted-foreground max-w-2xl mx-auto">
            AntiVibe runs a 3-tier security pipeline on your code — static
            analysis, sandboxed dynamic testing, and fuzzing — then files a fix
            PR automatically.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="#pricing">
              <Button size="lg" className="gap-2">
                See Pricing <ArrowRight className="size-4" />
              </Button>
            </Link>
            <Link href="#free-tier">
              <Button variant="outline" size="lg">
                Start Free — 3 full scans, no credit card
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="border-b py-20">
        <div className="mx-auto max-w-5xl px-4">
          <h2 className="text-3xl font-bold text-center mb-12">How It Works</h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {steps.map((step) => (
              <div key={step.title} className="text-center">
                <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-primary/10">
                  <step.icon className="size-6 text-primary" />
                </div>
                <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                <p className="text-sm text-muted-foreground">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="border-b py-20">
        <div className="mx-auto max-w-5xl px-4 text-center">
          <h2 className="text-3xl font-bold mb-4">Simple Pricing</h2>
          <p className="text-muted-foreground mb-10">One plan. Everything included.</p>
          <div className="flex justify-center">
            <PricingCard />
          </div>
        </div>
      </section>

      {/* Free Tier */}
      <section id="free-tier" className="py-20">
        <div className="mx-auto max-w-lg px-4 text-center">
          <h2 className="text-3xl font-bold mb-4">Try Before You Buy</h2>
          <p className="text-muted-foreground mb-8">
            Enter your email for 3 full scans — no credit card required.
          </p>
          <FreeTierForm />
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t mt-auto py-8">
        <div className="mx-auto max-w-5xl px-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
          <span>&copy; {new Date().getFullYear()} AntiVibe. All rights reserved.</span>
          <div className="flex gap-6">
            <Link href="https://github.com/hairzee/AntiVibe" className="hover:text-foreground">
              GitHub
            </Link>
            <Link href="/docs" className="hover:text-foreground">
              Docs
            </Link>
            <Link href="/privacy" className="hover:text-foreground">
              Privacy
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}

function FreeTierForm() {
  return (
    <form
      action="/api/auth/start-free"
      method="POST"
      className="flex flex-col sm:flex-row gap-3 justify-center"
    >
      <Input
        type="email"
        name="email"
        placeholder="you@example.com"
        required
        className="max-w-xs"
      />
      <Button type="submit" className="gap-2">
        Start Free <ArrowRight className="size-4" />
      </Button>
    </form>
  )
}
