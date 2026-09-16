/** Match literal text after typography/whitespace normalization; never approximate a citation. */
export function quoteMatches(items: string[], quote: string) {
  const normalize = (value: string) => value.normalize('NFKC').replace(/\u00ad/g, '').replace(/\s+/g, ' ').trim().toLowerCase()
  const ranges: { start: number; end: number }[] = []
  let text = ''
  for (const item of items) {
    const value = normalize(item)
    if (text && value) text += ' '
    const start = text.length
    text += value
    ranges.push({ start, end: text.length })
  }
  const target = normalize(quote)
  const indices = new Set<number>()
  let count = 0
  if (target) for (let at = text.indexOf(target); at !== -1; at = text.indexOf(target, at + target.length)) {
    count++
    ranges.forEach((range, index) => { if (range.start < at + target.length && range.end > at) indices.add(index) })
  }
  return { indices: [...indices], count }
}
