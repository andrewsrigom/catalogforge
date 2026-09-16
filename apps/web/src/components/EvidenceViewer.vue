<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api, download, workspace, session, type Schema } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
const PdfPage = defineAsyncComponent(() => import('./PdfPage.vue'))
const props = defineProps<{ evidence: Schema['EvidenceOut'] | null; attribute: string; value: string }>()
const emit = defineEmits<{ close: [] }>()
const isPdf = computed(() => props.evidence?.filename.toLowerCase().endsWith('.pdf'))
const { data, error } = useQuery({ queryKey: computed(() => [workspace.value, 'evidence-source', props.evidence?.document_id]), queryFn: () => api<Schema['SourceDetail']>('/sources/' + props.evidence?.document_id), enabled: computed(() => !!props.evidence && !!session.value) })
const chunk = computed(() => data.value?.chunks.find(c => c.id === props.evidence?.chunk_id))
const actionError = defineModel<unknown>('error')
async function original() { if (props.evidence) try { await download('/sources/' + props.evidence.document_id + '/file', props.evidence.filename) } catch(e) { actionError.value = e } }
</script>
<template>
  <Dialog :open="!!evidence" @update:open="value => { if (!value) emit('close') }"><DialogContent class="document-modal"><DialogHeader><DialogTitle>Inspect original source</DialogTitle><DialogDescription>{{ evidence?.filename }} · Version {{ evidence?.document_version }}</DialogDescription></DialogHeader>
    <div v-if="evidence" class="document-inspector">
      <aside class="citation-context"><span class="eyebrow">ATTRIBUTE → QUOTATION → SOURCE</span><h2>{{ attribute }}</h2><strong class="citation-value">{{ value }}</strong><blockquote>{{ evidence.quote }}</blockquote><p>{{ evidence.identity_basis.reason }}</p><span class="source-location">{{ evidence.location.page ? 'Cited page ' + evidence.location.page : evidence.location.row ? 'Row ' + evidence.location.row : evidence.location.section }}</span><p v-if="data && !data.document.active" class="warning-text">This source version has been superseded. The original citation is preserved.</p><Button variant="outline" size="sm" @click="original">Download original</Button><Notice :error="error || actionError" /><details v-if="chunk"><summary>Read extracted passage</summary><pre class="source-passage">{{ chunk.text }}</pre></details></aside>
      <PdfPage v-if="isPdf" :document-id="evidence.document_id" :page="Number(evidence.location.page) || 1" :quote="evidence.quote" />
      <section v-else class="text-source-reader"><span class="eyebrow">EXTRACTED SOURCE PASSAGE</span><h2>{{ evidence.filename }}</h2><template v-if="chunk"><pre class="source-passage">{{ chunk.text.split(evidence.quote)[0] }}<mark v-if="chunk.text.includes(evidence.quote)">{{ evidence.quote }}</mark>{{ chunk.text.includes(evidence.quote) ? chunk.text.slice(chunk.text.indexOf(evidence.quote) + evidence.quote.length) : '' }}</pre></template><p v-else>Loading the cited passage…</p><p class="muted">The original CSV or text file is available through Download original.</p></section>
    </div>
  </DialogContent></Dialog>
</template>
