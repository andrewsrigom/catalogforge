<script setup lang="ts">
import { computed, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api, workspace, session, type Schema } from '@/api/client'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
const props = defineProps<{ runId: string }>()
const { data, error, isPending } = useQuery({ queryKey: computed(() => [workspace.value, 'timeline', props.runId]), queryFn: () => api<Schema['RunTimelineOut']>(`/runs/${props.runId}/timeline`), enabled: computed(() => !!props.runId && !!session.value), refetchInterval: 4000 })
const chosen = ref(''), showAll = ref(false)
const checkpoint = computed(() => data.value?.checkpoints.find(c => c.id === chosen.value) || data.value?.checkpoints.at(-1))
const visibleEvents = computed(() => showAll.value ? data.value?.events : data.value?.events.slice(-12))
const phases = [
  { name: 'Inspect', match: ['Inspecting missing attributes'] },
  { name: 'Find & match', match: ['Finding supporting passages', 'Checking product match'] },
  { name: 'Extract', match: ['Extracting proposed values'] },
  { name: 'Validate', match: ['Validating values and evidence'] },
  { name: 'Human review', match: ['Preparing review', 'Waiting for review'] },
  { name: 'Apply', match: ['Applying approved changes', 'Refreshing catalog'] },
]
function seen(phase: typeof phases[number]) { return data.value?.events.some(e => phase.match.includes(e.step)) }
function time(value: string) { return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
function eventKind(step: string) { return /failed|attention/i.test(step) ? 'failure' : /resumed/i.test(step) ? 'resume' : /review/i.test(step) ? 'review' : '' }
</script>
<template>
  <section class="panel run-timeline" aria-label="Execution timeline">
    <div class="section-heading"><div><span class="eyebrow">PERSISTED EXECUTION HISTORY</span><h2>From source to decision</h2><p>Events and checkpoints recorded by this workflow.</p></div><StatusPill v-if="data" :status="data.status" /></div>
    <Notice :error="error" /><p v-if="isPending" class="loading">Reading execution history…</p>
    <template v-if="data">
      <ol class="execution-phases"><li v-for="(phase,index) in phases" :key="phase.name" :class="{ recorded: seen(phase), waiting: phase.name === 'Human review' && data.status === 'waiting_review' }"><span>{{ String(index + 1).padStart(2,'0') }}</span><strong>{{ phase.name }}</strong><small>{{ phase.name === 'Human review' && data.status === 'waiting_review' ? 'Awaiting decision' : seen(phase) ? 'Recorded' : 'Not reached' }}</small></li></ol>
      <div class="timeline-columns"><div class="event-log"><div class="timeline-subheading"><h3>Activity</h3><span>{{ data.attempt }} delivery attempt{{ data.attempt === 1 ? '' : 's' }}</span></div><p v-if="!data.events.length" class="empty-inline">Waiting for the worker to start.</p><ol><li v-for="event in visibleEvents" :key="event.sequence" :class="eventKind(event.step)"><span class="event-marker"/><div><strong>{{ event.step }}</strong><p v-if="event.details.error">{{ event.details.error }}</p><small v-if="event.details.attempt">Attempt {{ event.details.attempt }}</small></div><time :datetime="event.created_at">{{ time(event.created_at) }}</time></li></ol><button v-if="data.events.length > 12" class="text-link" @click="showAll = !showAll">{{ showAll ? 'Show recent events' : 'Show all ' + data.events.length + ' events' }}</button></div>
      <aside class="checkpoint-panel"><div class="timeline-subheading"><h3>Saved checkpoints</h3><span>{{ data.checkpoints.length }}</span></div><p class="muted">Inspect a saved position without changing the workflow.</p><label v-if="data.checkpoints.length">Checkpoint<select v-model="chosen" aria-label="Saved checkpoint"><option value="">Latest checkpoint</option><option v-for="point in data.checkpoints" :value="point.id" :key="point.id">Step {{ point.step }} · {{ time(point.created_at) }}</option></select></label><dl v-if="checkpoint" class="checkpoint-details"><div><dt>Recorded</dt><dd>{{ new Date(checkpoint.created_at).toLocaleString() }}</dd></div><div><dt>Next nodes</dt><dd>{{ checkpoint.next_nodes.join(' → ') || 'No next node scheduled' }}</dd></div><div><dt>Human interrupt</dt><dd>{{ checkpoint.interrupted ? 'Waiting for a decision' : 'No pending interrupt' }}</dd></div><div><dt>Checkpoint ID</dt><dd class="mono">{{ checkpoint.id }}</dd></div></dl><p v-else class="empty-inline">The first checkpoint appears when processing starts.</p><p v-if="data.truncated" class="muted">Showing the latest 200 events and 100 checkpoints.</p></aside></div>
      <div v-if="data.reviews.length" class="decision-ledger"><h3>Decision record</h3><article v-for="review in data.reviews" :key="review.id"><div><time :datetime="review.created_at">{{ new Date(review.created_at).toLocaleString() }}</time><StatusPill :status="review.status" /></div><ul><li v-for="decision in review.decisions" :key="decision.candidate_id"><strong>{{ decision.attribute_key.replaceAll('_',' ') }}</strong> · {{ decision.action }}<p v-if="decision.reason">{{ decision.reason }}</p></li></ul></article></div>
    </template>
  </section>
</template>
