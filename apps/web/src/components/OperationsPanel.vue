<script setup lang="ts">
import { computed } from 'vue'
import { useData } from '@/composables/data'
import Notice from '@/components/Notice.vue'

type Budget = { scope: string; calls: number; charged_tokens: number; charged_cost_micros: number; limits: { calls: number; tokens: number; cost_micros: number | null } }
type Operations = {
  worker: { healthy: boolean; last_seen: string | null }
  queue: { counts: { runs: Record<string, number>; documents: Record<string, number> }; pending_dispatch: number; oldest_wait_seconds: number }
  failures: { kind: string; id: string; error: string; created_at: string }[]
  next_step: string
  provider_usage: { operation: string; status: string; calls: number; charged_tokens: number; charged_cost_micros: number }[]
  unknown_usage_calls: number
  budgets: Budget[]
}
const { data, error, isPending } = useData<Operations>('/operations', true)
const budget = computed(() => data.value?.budgets.find(b => b.scope === 'workspace'))
const count = (state: string) => (data.value?.queue.counts.runs[state] || 0) + (data.value?.queue.counts.documents[state] || 0)
const usd = (micros: number) => (micros / 1_000_000).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })
</script>

<template>
  <section class="panel settings-card operations-panel" aria-labelledby="operations-heading">
    <h2 id="operations-heading">Processing health & usage</h2>
    <Notice :error="error" />
    <p v-if="isPending">Checking worker and workspace queue…</p>
    <template v-if="data">
      <span class="status" :class="data.worker.healthy ? 'status-ready' : 'status-failed'">{{ data.worker.healthy ? 'Worker responding' : 'Worker unavailable' }}</span>
      <dl>
        <div><dt>Last worker heartbeat</dt><dd>{{ data.worker.last_seen ? new Date(data.worker.last_seen).toLocaleTimeString() : 'Not observed' }}</dd></div>
        <div><dt>Queued in this workspace</dt><dd>{{ count('queued') }}</dd></div>
        <div><dt>Processing / resuming</dt><dd>{{ count('processing') + count('resuming') }}</dd></div>
        <div><dt>Waiting for review</dt><dd>{{ data.queue.counts.runs.waiting_review || 0 }}</dd></div>
        <div><dt>Age of oldest queued item</dt><dd>{{ data.queue.oldest_wait_seconds }} seconds</dd></div>
        <div><dt>Awaiting dispatch</dt><dd>{{ data.queue.pending_dispatch }}</dd></div>
      </dl>
      <p class="info-strip">{{ data.next_step }}</p>
      <div v-if="data.failures.length" class="stack">
        <h3>Failed items</h3>
        <div v-for="failure in data.failures" :key="failure.id">
          <RouterLink class="text-link" :to="failure.kind === 'documents' ? '/sources' : '/runs'">{{ failure.kind === 'documents' ? 'Inspect source' : 'Inspect run' }}</RouterLink>
          <p>{{ failure.error }}</p>
        </div>
      </div>
      <h3>AI consumption · selected workspace</h3>
      <p v-if="!budget">No real-provider calls recorded. Fixture processing does not consume an API budget.</p>
      <template v-else>
        <dl>
          <div><dt>Attempted calls</dt><dd>{{ budget.calls }} / {{ budget.limits.calls }}</dd></div>
          <div><dt>Accounted tokens, including reservations</dt><dd>{{ budget.charged_tokens.toLocaleString() }} / {{ budget.limits.tokens.toLocaleString() }}</dd></div>
          <div><dt>USD budget</dt><dd>{{ budget.limits.cost_micros === null ? 'No monetary limit configured' : `${usd(budget.charged_cost_micros)} / ${usd(budget.limits.cost_micros)}` }}</dd></div>
        </dl>
        <p>Failed or interrupted calls with unknown usage retain their full reservation. {{ data.unknown_usage_calls }} calls have no confirmed token usage. Restarting the worker does not reset these limits.</p>
        <details><summary>Usage by operation</summary>
          <ul><li v-for="usage in data.provider_usage" :key="`${usage.operation}:${usage.status}`">{{ usage.operation }} · {{ usage.status }}: {{ usage.calls }} calls, {{ usage.charged_tokens.toLocaleString() }} accounted tokens</li></ul>
        </details>
      </template>
    </template>
  </section>
</template>

<style scoped>
.operations-panel { margin-top: 24px; }
.operations-panel h3 { margin: 24px 0 10px; font-weight: 600; }
.operations-panel details { margin-top: 16px; }
.operations-panel li { margin: 8px 0; overflow-wrap: anywhere; }
.operations-panel p { overflow-wrap: anywhere; }
</style>
