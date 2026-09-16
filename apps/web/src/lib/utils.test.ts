import { describe, expect, it } from 'vitest'
import { display } from './utils'

describe('attribute presentation',()=>{
  it('keeps false and zero visible while distinguishing unknowns',()=>{
    expect(display(false)).toBe('No')
    expect(display(0)).toBe('0')
    expect(display(null)).toBe('Unknown')
    expect(display('')).toBe('Unknown')
  })
})
