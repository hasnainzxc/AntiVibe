import { describe, it, expect } from 'vitest'
import { Severity, Stack, AuthStack, isSeverity, isStack, isAuthStack, assertScan, assertFinding } from '../index'
import { validScan } from '../../__fixtures__/scan'

describe('shared-types', () => {
  it('Severity has 5 levels', () => {
    expect(Object.keys(Severity).length).toBe(5)
  })

  it('Stack has exactly 6 values (Metis whitelist lock)', () => {
    expect(Object.keys(Stack).length).toBe(6)
    expect(Object.values(Stack)).toContain('nextjs')
    expect(Object.values(Stack)).toContain('express')
    expect(Object.values(Stack)).toContain('firebase')
    expect(Object.values(Stack)).toContain('fastapi')
    expect(Object.values(Stack)).toContain('flask')
    expect(Object.values(Stack)).toContain('sveltekit')
  })

  it('AuthStack has exactly 5 values', () => {
    expect(Object.keys(AuthStack).length).toBe(5)
  })

  it('isSeverity validates correctly', () => {
    expect(isSeverity('critical')).toBe(true)
    expect(isSeverity('garbage')).toBe(false)
  })

  it('isStack validates whitelist', () => {
    expect(isStack('nextjs')).toBe(true)
    expect(isStack('golang')).toBe(false)
  })

  it('assertScan validates shape', () => {
    expect(() => assertScan(validScan)).not.toThrow()
    expect(() => assertScan(null)).toThrow()
    expect(() => assertScan({ id: 123 })).toThrow()
  })

  it('valid fixture compiles and passes type guard', () => {
    assertScan(validScan)
    expect(validScan.status).toBe('pending')
  })
})
