<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { ArrowRight, Check, FileText, Play, ShieldCheck } from '@lucide/vue'
import { useData } from '@/composables/data'
import { api, post, session, setSession, workspace, type Schema, type Session } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
import RunTimeline from '@/components/RunTimeline.vue'
import { display } from '@/lib/utils'

const { data, error } = useData<Schema['WalkthroughOut']>('/walkthrough', true)
const query = useQueryClient(), busy = ref(false), actionError = ref<unknown>(null)
const fields = [{ key:'material', label:'Liner material', unit:'' }, { key:'length_mm', label:'Overall length', unit:'mm' }, { key:'pack_quantity', label:'Pairs per pack', unit:'pairs' }]
const open = computed(() => !!data.value?.workspace_id && workspace.value === data.value.workspace_id)
const ready = computed(() => data.value?.sources.length === 2 && data.value.sources.every(s => s.status === 'ready'))
const canCreate = computed(() => ['owner','reviewer'].includes(session.value?.workspaces.find(w => w.id === workspace.value)?.role || ''))
const stage = computed(() => !data.value?.run ? 1 : data.value.run.status === 'completed' ? 4 : data.value.run.status === 'waiting_review' ? 3 : 2)
async function prepare() {
  busy.value = true; actionError.value = null
  try {
    const result = data.value?.workspace_id ? data.value : await post<Schema['WalkthroughOut']>('/walkthrough')
    setSession(await api<Session>('/auth/me'))
    workspace.value = result.workspace_id || ''; localStorage.setItem('catalogforge-workspace', workspace.value)
    await query.invalidateQueries()
  } catch(e) { actionError.value = e } finally { busy.value = false }
}
async function start() {
  busy.value = true; actionError.value = null
  try { await post('/walkthrough/start'); await query.invalidateQueries() }
  catch(e) { actionError.value = e } finally { busy.value = false }
}
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">A HANDS-ON PRODUCT WALKTHROUGH</span><h1>One product. A defensible decision.</h1><p>Compare a technical sheet with a supplier listing, inspect the original, then decide.</p></div><RouterLink to="/product-story" class="text-link">How CatalogForge works <ArrowRight :size="15" /></RouterLink></div>
  <Notice :error="error || actionError" />
  <section class="walkthrough-hero panel"><div><span class="story-chip">ABOUT 3 MINUTES · SYNTHETIC DATA</span><h2>Two documents.<br/>One disagreement to resolve.</h2><p>The technical sheet says Nylon and 12 pairs. A supplier lists Polyester and 6 pairs for the same product. Both agree on length. Follow the evidence before changing the catalog.</p><div class="walkthrough-assurance"><ShieldCheck :size="18"/>Your walkthrough has its own workspace. Existing catalogs are preserved.</div></div><div class="walkthrough-start"><span class="product-glyph">PG<br/><strong>210</strong></span><strong>PrecisionGrip assembly glove</strong><span class="mono">PG-210-M-PU · Size M</span><Button v-if="!open" :disabled="busy || (!data?.workspace_id && (!canCreate || data?.mode !== 'fixture'))" @click="prepare"><Play :size="16" />{{ data?.workspace_id ? 'Resume walkthrough' : 'Start guided walkthrough' }}</Button><span v-else class="match-label"><Check :size="16"/>Your walkthrough is open</span></div></section>
  <p v-if="data?.mode !== 'fixture'" class="info-strip">The guided walkthrough runs in fixture mode, without paid model calls.</p>
  <ol class="walkthrough-steps"><li v-for="(title,index) in ['Meet the record','Prepare proposals','Compare & decide','See the result']" :key="title" :class="{ current: open && stage === index + 1, done: open && stage > index + 1 }"><span>{{ index + 1 }}</span>{{ title }}</li></ol>
  <template v-if="data?.product && open">
    <section class="panel walkthrough-record"><div class="section-heading"><div><h2>{{ stage === 4 ? 'Your decision, reflected in the catalog' : 'The original record stays intact' }}</h2><p>{{ stage === 4 ? 'Only values you approved appear in the current record.' : 'No proposed value is applied before your review.' }}</p></div><StatusPill v-if="data.run" :status="data.run.status" /></div><table><thead><tr><th>Attribute</th><th>Imported value</th><th>Current value</th></tr></thead><tbody><tr v-for="field in fields" :key="field.key"><td>{{ field.label }}</td><td class="muted">{{ display(data.product.attributes[field.key]) }}</td><td><strong>{{ display(data.product.approved[field.key] ?? data.product.attributes[field.key]) }}</strong><span v-if="data.product.approved[field.key] != null"> {{ field.unit }}</span></td></tr></tbody></table></section>
    <section class="walkthrough-guidance panel"><div><span class="eyebrow">{{ stage === 4 ? '04 · COMPLETE' : stage === 3 ? '03 · COMPARE & DECIDE' : data.run ? '02 · PROCESSING' : '02 · PREPARE PROPOSALS' }}</span><h2>{{ stage === 4 ? 'The evidence and decision remain traceable.' : stage === 3 ? 'Resolve the two conflicts in the review workspace.' : data.run ? 'Follow the workflow as it runs.' : 'Read the sources. Then prepare the proposals.' }}</h2><p>{{ stage === 4 ? 'Inspect the decision record below, open the product, or create an export of this workspace.' : stage === 3 ? 'Open the original PDF from a proposal, compare it with the supplier passage and record why you choose each value. Approve the supported length when satisfied.' : data.run ? 'The worker is using the same retrieval, validation and checkpoint pipeline as your catalog.' : 'Wait for both documents to be ready. Enrichment will prepare material, length and packaging for review.' }}</p></div><div class="actions"><Button v-if="!data.run" :disabled="busy || !ready || data.mode !== 'fixture'" @click="start">Prepare proposals <ArrowRight :size="16"/></Button><RouterLink v-else-if="stage === 3" :to="'/review/'+data.run.id+'?walkthrough=1'" class="button-primary">Compare evidence <ArrowRight :size="16"/></RouterLink><RouterLink v-else-if="stage === 4" :to="'/products/'+data.product.id" class="button-primary">View updated product <ArrowRight :size="16"/></RouterLink><RouterLink v-if="stage === 4" to="/exports" class="button-outline">Create export</RouterLink></div></section>
    <div class="walkthrough-sources"><RouterLink v-for="source in data.sources" :key="source.id" :to="'/sources/'+source.id" class="panel"><FileText :size="22"/><div><strong>{{ source.filename }}</strong><small>{{ source.error || 'Version ' + source.version }}</small></div><StatusPill :status="source.status"/></RouterLink></div>
    <RunTimeline v-if="data.run" :run-id="data.run.id" />
  </template>
</template>
