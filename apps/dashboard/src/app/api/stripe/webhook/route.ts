import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import Stripe from 'stripe'

const stripe = process.env.STRIPE_SECRET_KEY
  ? new Stripe(process.env.STRIPE_SECRET_KEY)
  : null

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET ?? ''

export async function POST(request: NextRequest) {
  if (!stripe) {
    return NextResponse.json({ error: 'Stripe not configured' }, { status: 503 })
  }

  const body = await request.text()
  const signature = request.headers.get('stripe-signature')

  if (!signature) {
    return NextResponse.json({ error: 'Missing stripe-signature' }, { status: 400 })
  }

  let event: Stripe.Event
  try {
    event = stripe.webhooks.constructEvent(body, signature, webhookSecret)
  } catch (err) {
    console.error('stripe webhook signature verification failed', err)
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 })
  }

  if (event.type === 'checkout.session.completed') {
    const session = event.data.object as Stripe.Checkout.Session
    const customerEmail = session.customer_details?.email
    const stripeCustomerId = session.customer as string
    const subscriptionId = session.subscription as string

    if (customerEmail && stripeCustomerId && subscriptionId) {
      // TODO: upsert user subscription in Supabase
      // await supabase.from('subscriptions').upsert({
      //   email: customerEmail,
      //   stripe_customer_id: stripeCustomerId,
      //   stripe_subscription_id: subscriptionId,
      //   plan: 'pro',
      //   status: 'active',
      //   updated_at: new Date().toISOString(),
      // })
      console.log('checkout.session.completed', { customerEmail, stripeCustomerId, subscriptionId })
    }
  }

  return NextResponse.json({ received: true })
}
