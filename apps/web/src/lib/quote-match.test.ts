import { describe, expect, it } from 'vitest'
import { quoteMatches } from './quote-match'

describe('literal quote matching', () => {
  it('finds a wrapped quote across text items with PDF typography', () => {
    expect(quoteMatches(['MPN: PG-210', 'Material:', 'Nylon', 'Length: 25 cm'], 'Material:\n Nylon')).toEqual({ indices: [1, 2], count: 1 })
    expect(quoteMatches(['Certiﬁcation: none'], 'Certification: none').count).toBe(1)
  })
  it('reports repeated text and refuses near matches', () => {
    expect(quoteMatches(['Material: Nylon', 'Material: Nylon'], 'Material: Nylon').count).toBe(2)
    expect(quoteMatches(['Material: Polyester'], 'Material: Nylon').indices).toEqual([])
    expect(quoteMatches(['Anything'], '').count).toBe(0)
  })
})
