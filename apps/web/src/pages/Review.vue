<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, ArrowRight, Check, X, Pencil, FileText, ShieldCheck, ExternalLink, RefreshCw, ScanLine, AlertTriangle } from '@lucide/vue'
import { useData } from '@/composables/data'
import { api, post, workspace, session, type Product, type Run, type ReviewDetail, type Candidate, type Schema } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
import EvidenceViewer from '@/components/EvidenceViewer.vue'
import RunTimeline from '@/components/RunTimeline.vue'
import { display, label, date } from '@/lib/utils'

import { reviewRequestFactory } from '@/lib/review-request'

const route = useRoute(), router = useRouter(), query = useQueryClient()
const { data: runs, error: queueError, isPending: queuePending } = useData<Run[]>('/reviews', true)
const { data: products } = useData<Product[]>('/products', true)
const { data: detail, error, isPending } = useQuery({
  queryKey: computed(() => [workspace.value, 'review', route.params.id]),
  queryFn: () => api<ReviewDetail>('/runs/' + route.params.id),
  enabled: computed(() => !!route.params.id), refetchInterval: 2000,
})
const inspectedEvidence = ref<Schema['EvidenceOut'] | null>(null)
const inspectedAttribute = ref(''), inspectedValue = ref('')
function inspectSource(evidence: Schema['EvidenceOut']) {
  if (!focused.value) return
  inspectedAttribute.value = attrLabel(focused.value.attribute_key)
  inspectedValue.value = display(focused.value.normalized_value)
  inspectedEvidence.value = evidence
}
const focusedId = ref(''), selected = ref<string[]>([]), busy = ref(false), actionError = ref<unknown>(null)
const modal = ref(false), editing = ref(false), manualValue = ref(''), reason = ref(''), target = ref<Candidate | null>(null)
const orderedCandidates = computed(() => {
  const priority: Record<string, number> = { conflicting: 0, needs_review: 1, supported: 2, invalid: 3, insufficient_evidence: 4, approved: 5, rejected: 6 }
  return [...(detail.value?.candidates || [])].sort((a,b) => (priority[a.status] ?? 9) - (priority[b.status] ?? 9) || a.attribute_key.localeCompare(b.attribute_key))
})
const proposalFilter = ref('all'), savedNotice = ref(''), unknownDialog = ref(false)
const makeRequest = reviewRequestFactory()
const visibleCandidates = computed(() => orderedCandidates.value.filter(c => proposalFilter.value === 'all' || (proposalFilter.value === 'pending' ? !['approved','rejected'].includes(c.status) : proposalFilter.value === 'resolved' ? ['approved','rejected'].includes(c.status) : c.status === proposalFilter.value)))
const unknowns = computed(() => pending.value.filter(c => c.status === 'insufficient_evidence'))
function moveEvidence(delta: number) {
  const list = visibleCandidates.value
  const index = list.findIndex(c => c.id === focused.value?.id)
  const candidate = list[(index + delta + list.length) % list.length]
  if (candidate) { focusedId.value = candidate.id; document.getElementById('proposal-' + candidate.id)?.scrollIntoView({ block: 'nearest' }) }
}
function shortcut(event: KeyboardEvent) {
  if (!event.altKey || modal.value || unknownDialog.value || inspectedEvidence.value || (event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable]')) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); moveEvidence(event.key === 'ArrowDown' ? 1 : -1) }
}
onMounted(() => window.addEventListener('keydown', shortcut))
onUnmounted(() => window.removeEventListener('keydown', shortcut))
const focused = computed(() => detail.value?.candidates.find(c => c.id === focusedId.value) || orderedCandidates.value[0])
const canReview = computed(() => ['owner','reviewer'].includes(session.value?.workspaces.find(w => w.id === workspace.value)?.role || '') && detail.value?.run.status === 'waiting_review' && !detail.value?.run.stale && !busy.value)
const pending = computed(() => detail.value?.candidates.filter(c => !['approved','rejected'].includes(c.status)) || [])
const supported = computed(() => pending.value.filter(c => c.status === 'supported'))
const events = useQuery({ queryKey: computed(() => [workspace.value, 'events', route.params.id]), queryFn: () => api<Schema['EventOut'][]>('/runs/' + route.params.id + '/events'), enabled: computed(() => !!route.params.id), refetchInterval: 4000 })
watch(() => route.params.id, () => { focusedId.value = ''; selected.value = []; actionError.value = null; savedNotice.value = ''; proposalFilter.value = 'all' })
function validationList(candidate: Candidate, key: string): string[] { const value = candidate.validation[key]; return Array.isArray(value) ? value.map(String) : [] }
function attrLabel(key: string) { return detail.value?.schema_definition.attributes.find(a => a.key === key)?.label || label(key) }
function openDecision(candidate: Candidate, edit = false) {
  target.value = candidate; focusedId.value = candidate.id; editing.value = edit
  manualValue.value = candidate.normalized_value == null ? '' : String(candidate.normalized_value)
  reason.value = ''; modal.value = true
}
async function submit(decisions: Schema['FieldDecision'][]) {
  if (!detail.value?.run.interrupt_id) return
  if (!decisions.length) return
  busy.value = true; actionError.value = null; savedNotice.value = ''
  const runId = detail.value.run.id
  try {
    const result = await post<Schema['ReviewOut']>('/runs/' + runId + '/review', makeRequest({
      interrupt_id: detail.value.run.interrupt_id, product_revision: detail.value.product.revision,
      decisions,
    }))
    modal.value = false; unknownDialog.value = false; selected.value = []
    let applied = false
    for (let i=0;i<60;i++) {
      const status = await api<Schema['ReviewOut']>('/review-decisions/' + result.id)
      if (status.status === 'failed') throw new Error(status.error || 'Review failed')
      if (status.status === 'applied') { applied = true; break }
      if (String(route.params.id) !== runId) break
      await new Promise(resolve => setTimeout(resolve, 250))
    }
    if (!applied && String(route.params.id) === runId) savedNotice.value = 'Your decisions were saved and are still being applied in the background. You can leave this page; progress updates automatically.'
    await query.invalidateQueries()
  } catch(e) { actionError.value = e } finally { busy.value = false }
}
function approve(candidate: Candidate) {
  if (candidate.status === 'conflicting') return openDecision(candidate)
  return submit([{ candidate_id: candidate.id, version: candidate.version, action: 'approve', reason: '' }])
}
function reject(candidate: Candidate) { return submit([{ candidate_id: candidate.id, version: candidate.version, action: 'reject', reason: '' }]) }
function saveDecision() {
  if (!target.value) return
  return submit([{ candidate_id: target.value.id, version: target.value.version, action: editing.value ? 'edit' : 'approve', value: editing.value ? manualValue.value : undefined, reason: reason.value }])
}
function bulkApprove() { return submit(supported.value.filter(c => selected.value.includes(c.id)).map(c => ({ candidate_id: c.id, version: c.version, action: 'approve', reason: '' }))) }
async function revalidate() {
  if (!detail.value) return
  busy.value = true
  try { const batch = await post<Schema['BatchOut']>('/runs/' + detail.value.run.id + '/revalidate'); await router.push('/review/' + batch.runs[0]?.id); await query.invalidateQueries() } catch(e) { actionError.value=e } finally { busy.value=false }
}
</script>
<template>
  <template v-if="!route.params.id">
    <div class="page-heading"><div><span class="eyebrow">HUMAN JUDGMENT, BUILT IN</span><h1>Review workspace</h1><p>Inspect the evidence behind every proposed change.</p></div><span class="workload-chip">{{ runs?.length || 0 }} products waiting</span></div><Notice :error="queueError" />
    <div class="review-intro"><ShieldCheck :size="22" /><div><strong>Nothing is applied without a decision.</strong><p>Supported proposals can be approved together. Conflicts need an explicit choice; unknowns stay unknown.</p></div></div>
    <div v-if="queuePending" class="loading">Loading the review queue…</div><div v-else-if="!queueError && !runs?.length" class="panel empty-state"><ScanLine :size="38" /><h2>Your review queue is clear</h2><p>Start enrichment from your product catalog to prepare new proposals.</p><RouterLink to="/catalog" class="button-primary">Go to product catalog<ArrowRight :size="16" /></RouterLink></div>
    <section v-else-if="runs?.length" class="panel table-panel"><table><thead><tr><th>Product</th><th>Identity</th><th>Workflow state</th><th>Created</th><th></th></tr></thead><tbody><tr v-for="run in runs" :key="run.id"><td><strong>{{ products?.find(p=>p.id===run.product_id)?.name || 'Loading product…' }}</strong><span class="subline mono">{{ products?.find(p=>p.id===run.product_id)?.sku }}</span></td><td>{{ products?.find(p=>p.id===run.product_id)?.mpn }}</td><td><StatusPill :status="run.stale ? 'stale' : run.status" /></td><td class="muted">{{ date(run.created_at) }}</td><td><RouterLink :to="'/review/' + run.id" class="button-outline">Review product<ArrowRight :size="15" /></RouterLink></td></tr></tbody></table></section>
  </template>
  <template v-else>
    <button class="back-link" @click="router.push('/review')"><ArrowLeft :size="16" />Review queue</button>
    <Notice :error="error || actionError" /><div v-if="savedNotice && detail?.run.status === 'resuming'" class="info-strip" role="status">{{ savedNotice }}</div><div v-if="isPending" class="loading">Opening the evidence workspace…</div>
    <template v-if="detail">
      <section v-if="route.query.walkthrough" class="walkthrough-banner"><div><strong>Compare the original, then make the decision.</strong><p>Inspect the PDF beside each conflicting proposal. Choose a value with a reason, then approve the supported length. Your decisions are preserved.</p></div><RouterLink to="/walkthrough" class="button-outline">{{ detail.run.status === 'completed' ? 'See before & after' : 'Back to walkthrough' }}<ArrowRight :size="15"/></RouterLink></section>
      <div class="page-heading review-heading"><div><span class="eyebrow">PRODUCT REVIEW</span><h1>{{ detail.product.name }}</h1><p><span class="mono">{{ detail.product.sku }}</span> · Product revision {{ detail.product.revision }} · {{ pending.length }} unresolved proposals</p></div><div class="actions"><StatusPill :status="detail.run.status" /><Button variant="outline" :disabled="busy" @click="revalidate"><RefreshCw :size="15" />Request more evidence</Button></div></div>
      <Notice v-if="detail.run.error" :message="detail.run.error" /><Notice v-if="detail.run.stale" message="These proposals are stale: the product, schema or source library has changed. Request more evidence to revalidate before approving." />
      <div v-if="detail.run.status === 'completed'" class="success-banner"><Check :size="18" />{{ detail.candidates.some(c => c.status === 'approved') ? 'Review complete. Approved values are now part of the catalog.' : 'Review complete. No values were added to the catalog.' }}<RouterLink :to="'/products/' + detail.product.id">View product<ArrowRight :size="15" /></RouterLink></div>
      <div v-if="detail.run.status === 'resuming' || busy" class="info-strip" role="status">Applying your review decisions…</div>
      <div class="review-layout">
        <aside class="panel identity-panel"><div class="column-heading"><span>01</span><h2>Current record</h2></div><div class="product-monogram">{{ detail.product.variant.size || '—' }}</div><h3>{{ detail.product.manufacturer }}</h3><p class="muted">{{ detail.product.model }} · {{ detail.product.variant.coating }}</p><dl class="identity-list"><div><dt>Part number</dt><dd class="mono">{{ detail.product.mpn || 'Unknown' }}</dd></div><div><dt>Category</dt><dd>{{ detail.schema_definition.name }}</dd></div><div><dt>Completeness</dt><dd>{{ detail.product.completeness }}%</dd></div></dl><div class="mini-heading">CURRENT ATTRIBUTES</div><dl class="current-values"><div v-for="attr in detail.schema_definition.attributes" :key="attr.key"><dt>{{ attr.label }}</dt><dd :class="{ unknown: display(detail.product.approved[attr.key] ?? detail.product.attributes[attr.key]) === 'Unknown' }">{{ display(detail.product.approved[attr.key] ?? detail.product.attributes[attr.key]) }}<span v-if="attr.unit && display(detail.product.approved[attr.key] ?? detail.product.attributes[attr.key]) !== 'Unknown'"> {{ attr.unit }}</span></dd></div></dl><div class="preserved-note"><ShieldCheck :size="16" />Populated original values are preserved.</div></aside>
        <section class="panel proposals-panel"><div class="column-heading"><span>02</span><h2>Proposed changes</h2><small>{{ detail.candidates.length }}</small></div><div class="proposal-toolbar"><label><input type="checkbox" :checked="supported.length > 0 && selected.length === supported.length" @change="selected = selected.length === supported.length ? [] : supported.map(c=>c.id)" :disabled="!canReview" />Select supported</label><Button size="sm" :disabled="!canReview || !selected.length" @click="bulkApprove"><Check :size="14" />Approve {{ selected.length || '' }}</Button></div>
          <div v-if="!detail.candidates.length" class="empty-inline">{{ detail.run.status === 'completed' ? 'No changes were needed.' : 'Proposals appear after product matching and validation.' }}</div>
          <div class="proposal-filters"><label>Show<select v-model="proposalFilter" aria-label="Proposal filter"><option value="all">All proposals</option><option value="pending">Unresolved</option><option value="conflicting">Conflicts</option><option value="supported">Supported</option><option value="insufficient_evidence">Unknown</option><option value="resolved">Reviewed</option></select></label><Button v-if="unknowns.length" variant="outline" size="sm" :disabled="!canReview" @click="unknownDialog = true">Keep {{ unknowns.length }} unknown</Button></div>
          <p v-if="detail.candidates.length && !visibleCandidates.length" class="empty-inline">No proposals match this filter.</p>
          <article v-for="candidate in visibleCandidates" :key="candidate.id" :id="'proposal-' + candidate.id" class="proposal-card" :class="{ focused: focused?.id === candidate.id, 'has-conflict': candidate.status === 'conflicting' }" @click="focusedId = candidate.id">
            <div class="proposal-top"><label><input v-if="candidate.status === 'supported'" v-model="selected" type="checkbox" :value="candidate.id" :disabled="!canReview" :aria-label="'Select ' + attrLabel(candidate.attribute_key)" /><strong>{{ attrLabel(candidate.attribute_key) }}</strong></label><StatusPill :status="candidate.status" /></div>
            <div class="value-diff"><span class="old-value">{{ display(candidate.original_value) }}</span><ArrowRight :size="16" /><strong>{{ display(candidate.normalized_value) }}<small v-if="candidate.normalized_value != null">{{ detail.schema_definition.attributes.find(a=>a.key===candidate.attribute_key)?.unit }}</small></strong></div>
            <p v-if="candidate.manual" class="manual-label">Manual reviewer edit · source does not substantiate this final value</p>
            <p v-if="candidate.conflict.reason" class="conflict-reason"><AlertTriangle :size="14" />{{ candidate.conflict.reason }}</p>
            <p v-if="validationList(candidate,'notes').length" class="validation-note">{{ validationList(candidate,'notes').join(' · ') }}</p>
            <p v-if="validationList(candidate,'errors').length" class="validation-note">{{ validationList(candidate,'errors').join(' · ') }}</p>
            <div class="proposal-bottom"><button class="evidence-link" @click.stop="focusedId = candidate.id"><FileText :size="14" />{{ candidate.evidence.length }} source{{ candidate.evidence.length === 1 ? '' : 's' }}</button><div v-if="!['approved','rejected'].includes(candidate.status)" class="actions">
              <Button variant="ghost" size="sm" :disabled="!canReview" @click.stop="reject(candidate)" :aria-label="'Reject ' + attrLabel(candidate.attribute_key)"><X :size="14" />Reject</Button>
              <Button v-if="display(candidate.original_value) === 'Unknown'" variant="ghost" size="sm" :disabled="!canReview" @click.stop="openDecision(candidate,true)" :aria-label="'Edit ' + attrLabel(candidate.attribute_key)"><Pencil :size="14" />Edit</Button>
              <Button v-if="['supported','conflicting'].includes(candidate.status)" size="sm" :disabled="!canReview" @click.stop="approve(candidate)" :aria-label="'Approve ' + attrLabel(candidate.attribute_key)"><Check :size="14" />{{ candidate.status === 'conflicting' ? 'Choose value' : 'Approve' }}</Button>
            </div></div>
          </article>
        </section>
        <aside class="panel evidence-panel"><div class="column-heading"><span>03</span><h2>Supporting evidence</h2><div class="evidence-nav"><button @click="moveEvidence(-1)" aria-label="Previous proposal" title="Previous proposal (Alt + ↑)">↑</button><button @click="moveEvidence(1)" aria-label="Next proposal" title="Next proposal (Alt + ↓)">↓</button></div></div><template v-if="focused"><div class="evidence-attribute"><span class="mini-heading">{{ attrLabel(focused.attribute_key) }}</span><strong>{{ display(focused.normalized_value) }}</strong></div><div v-if="!focused.evidence.length" class="empty-evidence"><FileText :size="27" /><h3>No supporting passage</h3><p>This field remains unknown. Add relevant documentation and request more evidence, or enter a clearly labeled manual value.</p></div><article v-for="evidence in focused.evidence" :key="evidence.id" class="evidence-card"><div class="source-heading"><FileText :size="17" /><strong>{{ evidence.filename }}</strong></div><p class="source-location">Version {{ evidence.document_version }} · {{ evidence.location.page ? 'Page ' + evidence.location.page : evidence.location.row ? 'Row ' + evidence.location.row : evidence.location.section }}</p><blockquote>{{ evidence.quote }}</blockquote><div class="match-label"><ShieldCheck :size="15" />{{ evidence.identity_basis.kind === 'family' ? 'Explicit family applicability' : 'Exact product match' }}</div><p class="match-reason">{{ evidence.identity_basis.reason }}</p><Button variant="outline" size="sm" @click="inspectSource(evidence)">Inspect original source<ExternalLink :size="13" /></Button><RouterLink :to="'/sources/' + evidence.document_id + '#' + evidence.chunk_id" class="text-link">Open extracted passage<ExternalLink :size="13" /></RouterLink></article></template><div class="evidence-footnote">Evidence is quoted from your uploaded documents. Similar products never establish identity on their own.</div></aside>
      </div>
      <RunTimeline :run-id="detail.run.id" />
      <details class="diagnostics"><summary>Workflow diagnostics</summary><pre>{{ JSON.stringify(detail.run.metrics, null, 2) }}</pre><div v-for="event in events.data.value" :key="event.sequence"><span class="mono">{{ event.sequence }}</span> {{ event.step }} · {{ date(event.created_at) }}</div></details>
    </template>
  </template>
  <EvidenceViewer :evidence="inspectedEvidence" :attribute="inspectedAttribute" :value="inspectedValue" @close="inspectedEvidence = null" />
  <Dialog v-model:open="unknownDialog"><DialogContent><DialogHeader><DialogTitle>Keep {{ unknowns.length }} fields unknown?</DialogTitle><DialogDescription>Reject the proposals without sufficient evidence. No values will be added to your catalog. You can request more evidence later.</DialogDescription></DialogHeader><Notice :error="actionError" /><DialogFooter><Button variant="outline" @click="unknownDialog = false">Cancel</Button><Button :disabled="!canReview" @click="submit(unknowns.map(c => ({ candidate_id: c.id, version: c.version, action: 'reject', reason: 'Kept unknown: insufficient evidence' })))">Confirm unknown fields</Button></DialogFooter></DialogContent></Dialog>
  <Dialog v-model:open="modal"><DialogContent><DialogHeader><DialogTitle>{{ editing ? 'Enter a manual value' : 'Resolve conflicting evidence' }}</DialogTitle><DialogDescription>{{ editing ? 'This value will be validated and labeled as a manual reviewer edit. The source will not be presented as proof of your edit.' : 'Compare the source passages and explain why you selected this value. Alternative candidates will be rejected.' }}</DialogDescription></DialogHeader><label v-if="editing" class="form-label">Reviewed value<Input v-model="manualValue" aria-label="Manual value" /></label><div v-else class="chosen-value">{{ target ? attrLabel(target.attribute_key) : '' }}<strong>{{ display(target?.normalized_value) }}</strong></div><label class="form-label">Decision reason<Textarea v-model="reason" placeholder="Explain the basis for your decision…" aria-label="Decision reason" /></label><Notice :error="actionError" /><DialogFooter><Button variant="outline" @click="modal = false">Cancel</Button><Button :disabled="busy || !reason.trim() || (editing && !manualValue.trim())" @click="saveDecision">{{ editing ? 'Apply manual edit' : 'Approve selected value' }}</Button></DialogFooter></DialogContent></Dialog>
</template>
