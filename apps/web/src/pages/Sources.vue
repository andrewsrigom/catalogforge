<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { FileText, Upload, ArrowLeft, Download, RefreshCw } from '@lucide/vue'
import { useData } from '@/composables/data'
import { upload, post, download, api, workspace, type Schema } from '@/api/client'
import { useQuery } from '@tanstack/vue-query'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
import { date } from '@/lib/utils'
const route = useRoute(), router = useRouter(), query = useQueryClient()
const { data: sources, error, isPending } = useData<Schema['SourceOut'][]>('/sources', true)
const { data: detail, error: detailError } = useQuery({ queryKey: computed(() => [workspace.value, 'source', route.params.id]), queryFn: () => api<Schema['SourceDetail']>('/sources/' + route.params.id), enabled: computed(() => !!route.params.id), refetchInterval: 2000 })
const actionError = ref<unknown>(null), busy = ref(false)
async function add(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  busy.value = true; actionError.value = null
  try { for (const file of files) await upload('/sources', file); await query.invalidateQueries() }
  catch(e) { actionError.value = e } finally { busy.value = false }
}
async function retry(id: string) { try { await post('/sources/' + id + '/retry'); await query.invalidateQueries() } catch(e) { actionError.value = e } }
async function getFile() { if (detail.value) try { await download('/sources/' + detail.value.document.id + '/file', detail.value.document.filename) } catch(e) { actionError.value = e } }
</script>
<template>
  <template v-if="route.params.id">
    <button class="back-link" @click="router.push('/sources')"><ArrowLeft :size="16" />All sources</button><Notice :error="detailError || actionError" />
    <div v-if="detail"><div class="page-heading"><div><span class="eyebrow">EXTRACTED DOCUMENT</span><h1>{{ detail.document.filename }}</h1><p>Version {{ detail.document.version }} · {{ detail.chunks.length }} passages · {{ date(detail.document.created_at) }}</p></div><Button variant="outline" @click="getFile"><Download :size="16" />Download original</Button></div><div class="source-detail-bar"><StatusPill :status="detail.document.status" /><span>{{ detail.document.active ? 'Active source version' : 'Superseded source version' }}</span></div><Notice v-if="detail.document.error" :message="detail.document.error" /><div v-if="!detail.chunks.length" class="empty-state">Extracted passages will appear after document ingestion completes.</div><article v-for="chunk in detail.chunks" :key="chunk.id" :id="chunk.id" class="panel passage-card" :class="{ highlighted: route.hash === '#' + chunk.id }"><div><strong>{{ chunk.location.page ? 'Page ' + chunk.location.page : chunk.location.row ? 'Row ' + chunk.location.row : chunk.location.section }}</strong><span class="mono muted">{{ chunk.id.slice(0,8) }}</span></div><pre>{{ chunk.text }}</pre></article></div>
  </template>
  <template v-else>
    <div class="page-heading"><div><span class="eyebrow">THE EVIDENCE LIBRARY</span><h1>Source documents</h1><p>Product facts begin here. Add documents your team can verify.</p></div><label class="button-primary upload-button"><Upload :size="16" />{{ busy ? 'Uploading…' : 'Add documents' }}<input type="file" multiple accept=".pdf,.txt,.csv" @change="add" :disabled="busy" aria-label="Add source documents" /></label></div>
    <Notice :error="error || actionError" /><div class="info-strip"><FileText :size="17" /><span>Text-based PDFs, TXT and CSV · Scanned PDFs are unsupported · Duplicate content is reused within this workspace.</span></div>
    <section class="panel table-panel"><div class="section-heading"><h2>All documents <span class="counter">{{ sources?.length || 0 }}</span></h2><span class="muted">Ingestion progress updates automatically</span></div><div v-if="isPending" class="loading">Loading sources…</div><div v-else-if="!sources?.length" class="empty-state"><FileText :size="34" /><h2>Your evidence library is empty</h2><p>Add technical records, specification sheets or product documentation.</p></div><div v-else class="table-scroll"><table><thead><tr><th>Document</th><th>Version</th><th>Ingestion</th><th>Added</th><th></th></tr></thead><tbody><tr v-for="source in sources" :key="source.id"><td><RouterLink :to="'/sources/' + source.id" class="document-name"><span class="file-icon"><FileText :size="19" /></span>{{ source.filename }}</RouterLink><span v-if="source.error" class="subline error-text">{{ source.error }}</span></td><td>v{{ source.version }}<span class="subline">{{ source.active ? 'Active' : 'Superseded' }}</span></td><td><StatusPill :status="source.status" /></td><td class="muted">{{ date(source.created_at) }}</td><td><Button v-if="source.status === 'failed'" variant="outline" size="sm" @click="retry(source.id)"><RefreshCw :size="14" />Retry</Button><RouterLink v-else :to="'/sources/' + source.id" class="text-link">View passages</RouterLink></td></tr></tbody></table></div></section>
  </template>
</template>
