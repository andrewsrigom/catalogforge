import { cpSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const base = new URL('../', import.meta.url)
for (const directory of ['cmaps', 'standard_fonts', 'wasm']) {
  const target = fileURLToPath(new URL(`public/pdfjs/${directory}`, base))
  mkdirSync(target, { recursive: true })
  cpSync(fileURLToPath(new URL(`node_modules/pdfjs-dist/${directory}`, base)), target, { recursive: true })
}
cpSync(fileURLToPath(new URL('node_modules/pdfjs-dist/LICENSE', base)), fileURLToPath(new URL('public/pdfjs/LICENSE', base)))
