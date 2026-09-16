<script setup lang="ts">
import { ArrowUpRight, ArrowRight, Package, ScanLine, Files, GitBranch, Check, Upload, Sparkles } from '@lucide/vue'
import { useData } from '@/composables/data'
import type { Schema } from '@/api/client'
import Notice from '@/components/Notice.vue'
import { date } from '@/lib/utils'
type Overview = { products: number; sources_ready: number; processing: number; waiting_review: number; conflicts: number; approved_fields: number; failed: number; events: Schema['EventOut'][] }
const { data, error, isPending } = useData<Overview>('/overview', true)
const { data: config } = useData<{ mode: string }>('/settings')
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">CATALOG OPERATIONS</span><h1>A clearer picture of your products.</h1><p>Fill the gaps. Follow the evidence. Keep control of every change.</p></div><RouterLink to="/import" class="button-primary"><Upload :size="16" />Import catalog</RouterLink></div>
  <div v-if="config?.mode === 'fixture'" class="fixture-banner"><Sparkles :size="16" /><strong>Fixture mode</strong><span>Deterministic synthetic data · No paid model calls · Results are not a model-quality evaluation.</span></div>
  <Notice :error="error" />
  <div v-if="isPending" class="loading">Loading your workspace…</div>
  <template v-if="data">
    <section class="metric-grid">
      <RouterLink v-for="metric in [{ label: 'Products in catalog', value: data.products, icon: Package, to: '/catalog', note: 'Original records preserved' }, { label: 'Ready source documents', value: data.sources_ready, icon: Files, to: '/sources', note: 'Available for evidence retrieval' }, { label: 'Products awaiting review', value: data.waiting_review, icon: ScanLine, to: '/review', note: 'Your decision is the next step' }, { label: 'Products processing', value: data.processing, icon: GitBranch, to: '/runs', note: 'Durable background workflows' }]" :key="metric.label" :to="metric.to" class="metric-card">
        <div><span>{{ metric.label }}</span><component :is="metric.icon" :size="18" /></div><strong>{{ metric.value }}</strong><small>{{ metric.note }}</small>
      </RouterLink>
    </section>
    <div class="overview-grid">
      <section class="panel review-callout"><div class="panel-title"><span class="icon-tile"><ScanLine :size="20" /></span><span>YOUR REVIEW WORKSPACE</span></div><h2>Good data starts<br />with a clear decision.</h2><p>Compare proposed attributes with the exact source passage. Resolve disagreements before a value reaches your catalog.</p><div class="review-totals"><div><strong>{{ data.waiting_review }}</strong><span>Products to review</span></div><div><strong>{{ data.conflicts }}</strong><span>Conflicting proposals</span></div><div><strong>{{ data.approved_fields }}</strong><span>Approved fields</span></div></div><RouterLink to="/review" class="button-primary">Open review workspace<ArrowRight :size="16" /></RouterLink></section>
      <section class="panel activity-panel"><div class="section-heading"><h2>Recent workflow activity</h2><RouterLink to="/runs">View runs<ArrowUpRight :size="15" /></RouterLink></div><div v-if="!data.events.length" class="empty-inline">Import a catalog and add documents to begin. Activity will appear here.</div><div v-for="event in data.events" :key="event.sequence" class="activity-row"><span class="activity-dot"><Check :size="13" /></span><div><strong>{{ event.step }}</strong><small>{{ date(event.created_at) }}</small></div></div></section>
    </div>
    <section class="workflow-strip"><div><span class="step-number">01</span><strong>Import your catalog</strong><p>Keep the original data intact.</p></div><ArrowRight :size="18" /><div><span class="step-number">02</span><strong>Add product evidence</strong><p>PDFs, text files and source sheets.</p></div><ArrowRight :size="18" /><div><span class="step-number">03</span><strong>Review and export</strong><p>Only approved changes move forward.</p></div></section>
    <Notice v-if="data.failed" :message="data.failed + ' product run(s) need attention. Open Enrichment runs to inspect and retry.'" />
  </template>
</template>
