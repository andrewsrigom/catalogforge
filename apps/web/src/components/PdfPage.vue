<script setup lang="ts">
import { onBeforeUnmount, ref, watch, nextTick } from 'vue'
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask, TextLayer } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import 'pdfjs-dist/web/pdf_viewer.css'
import { apiBytes } from '@/api/client'
import { quoteMatches } from '@/lib/quote-match'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'

const props = defineProps<{ documentId: string; page?: number; quote?: string }>()
const canvas = ref<HTMLCanvasElement>(), layer = ref<HTMLDivElement>()
const currentPage = ref(1), pages = ref(0), zoom = ref(1), loading = ref(false), error = ref<unknown>(null)
const matches = ref(0), rendered = ref(false)
let pdf: PDFDocumentProxy | undefined, task: PDFDocumentLoadingTask | undefined
let renderTask: RenderTask | undefined, textLayer: TextLayer | undefined
let generation = 0, drawing = 0, controller: AbortController | undefined

async function draw() {
  const active = ++drawing, source = pdf
  renderTask?.cancel(); textLayer?.cancel()
  rendered.value = false; matches.value = 0
  if (!source || !canvas.value || !layer.value) return
  try {
    error.value = null
    const page = await source.getPage(Math.max(1, Math.min(currentPage.value || 1, source.numPages)))
    if (active !== drawing) return
    const lib = await import('pdfjs-dist')
    const viewport = page.getViewport({ scale: zoom.value })
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    canvas.value.width = Math.ceil(viewport.width * ratio)
    canvas.value.height = Math.ceil(viewport.height * ratio)
    canvas.value.style.width = `${viewport.width}px`; canvas.value.style.height = `${viewport.height}px`
    layer.value.replaceChildren()
    layer.value.style.setProperty('--scale-factor', String(zoom.value))
    layer.value.style.setProperty('--total-scale-factor', String(zoom.value))
    layer.value.style.width = `${viewport.width}px`; layer.value.style.height = `${viewport.height}px`
    renderTask = page.render({ canvas: canvas.value, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] })
    await renderTask.promise
    const content = await page.getTextContent()
    if (active !== drawing) return
    textLayer = new lib.TextLayer({ textContentSource: content, container: layer.value, viewport })
    await textLayer.render()
    if (active !== drawing) return
    const result = quoteMatches(textLayer.textContentItemsStr, props.quote || '')
    matches.value = result.count
    result.indices.forEach(index => textLayer?.textDivs[index]?.classList.add('citation-highlight'))
    rendered.value = true
  } catch (e) {
    if (active === drawing && !(e instanceof Error && ['RenderingCancelledException', 'AbortException'].includes(e.name))) error.value = e
  }
}
watch(() => props.documentId, async () => {
  const active = ++generation
  ++drawing; controller?.abort(); renderTask?.cancel(); textLayer?.cancel()
  const previous = task; task = undefined; pdf = undefined
  void previous?.destroy()
  controller = new AbortController(); loading.value = true; error.value = null; rendered.value = false; pages.value = 0
  try {
    const bytes = await apiBytes(`/sources/${props.documentId}/file`, controller.signal)
    if (active !== generation) return
    const lib = await import('pdfjs-dist'); lib.GlobalWorkerOptions.workerSrc = workerUrl
    if (active !== generation) return
    task = lib.getDocument({ data: bytes, cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/' })
    const loaded = await task.promise
    if (active !== generation) { void loaded.loadingTask.destroy(); return }
    pdf = loaded
    pages.value = pdf.numPages
    currentPage.value = Math.max(1, Math.min(props.page || 1, pages.value))
    loading.value = false
    await nextTick(); await draw()
  } catch (e) { if (active === generation && !(e instanceof Error && e.name === 'AbortError')) error.value = e }
  finally { if (active === generation) loading.value = false }
}, { immediate: true })
watch([currentPage, zoom, () => props.quote], () => { if (!loading.value) void draw() })
watch(() => props.page, value => { if (pages.value) currentPage.value = Math.max(1, Math.min(value || 1, pages.value)) })
onBeforeUnmount(() => { ++generation; ++drawing; controller?.abort(); renderTask?.cancel(); textLayer?.cancel(); void task?.destroy() })
</script>

<template>
  <div class="pdf-viewer">
    <div class="pdf-toolbar">
      <Button variant="outline" size="sm" :disabled="currentPage <= 1 || loading" @click="currentPage--" aria-label="Previous PDF page">←</Button>
      <label>Page <input v-model.number="currentPage" type="number" min="1" :max="pages || 1" :disabled="loading" aria-label="PDF page" @change="currentPage = Math.max(1, Math.min(currentPage || 1, pages || 1))" /></label><span>of {{ pages || '…' }}</span>
      <Button variant="outline" size="sm" :disabled="currentPage >= pages || loading" @click="currentPage++" aria-label="Next PDF page">→</Button>
      <label class="pdf-zoom">Zoom<select v-model.number="zoom" aria-label="PDF zoom"><option :value="0.75">75%</option><option :value="1">100%</option><option :value="1.25">125%</option><option :value="1.5">150%</option></select></label>
    </div>
    <Notice :error="error" />
    <p v-if="loading" class="loading" role="status">Opening original PDF…</p>
    <p v-if="rendered && quote" class="pdf-match-status" role="status">{{ matches === 1 ? 'Quoted passage highlighted on this page.' : matches > 1 ? matches + ' matching passages on this page. Compare the product identity.' : 'The exact quotation could not be located on this page. The extracted passage remains available alongside the original.' }}</p>
    <div v-show="!loading && !error" class="pdf-scroll"><div class="pdf-sheet"><canvas ref="canvas" aria-label="Original PDF page" /><div ref="layer" class="textLayer" :data-rendered="rendered" /></div></div>
  </div>
</template>
