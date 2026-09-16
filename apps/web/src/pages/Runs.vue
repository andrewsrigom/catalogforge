<script setup lang="ts">
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { GitBranch, RefreshCw, X, ArrowRight } from '@lucide/vue'
import { useData } from '@/composables/data'
import { post, type Schema, type Product } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
import { date } from '@/lib/utils'
const { data: batches, error, isPending } = useData<Schema['BatchOut'][]>('/batches', true)
const { data: products } = useData<Product[]>('/products')
const query=useQueryClient(), actionError=ref<unknown>(null), busy=ref('')
async function action(id:string, op:string) { busy.value=id; actionError.value=null; try { await post('/runs/'+id+'/'+op); await query.invalidateQueries() } catch(e) { actionError.value=e } finally { busy.value='' } }
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">DURABLE, VISIBLE PROGRESS</span><h1>Enrichment runs</h1><p>Each product moves independently from retrieval to review.</p></div><RouterLink to="/catalog" class="button-primary">Start from catalog<ArrowRight :size="16" /></RouterLink></div><Notice :error="error || actionError" /><div v-if="isPending" class="loading">Loading runs…</div><div v-else-if="!batches?.length" class="panel empty-state"><GitBranch :size="36" /><h2>No enrichment runs yet</h2><p>Select products in the catalog to begin.</p></div>
  <section v-for="batch in batches" :key="batch.id" class="panel table-panel batch-panel"><div class="section-heading"><div><h2>{{ batch.title }}</h2><p>{{ date(batch.created_at) }} · {{ batch.runs.length }} products</p></div><span class="batch-completion">{{ batch.runs.filter(r=>r.status==='completed').length }} / {{ batch.runs.length }} completed</span></div><div class="table-scroll"><table><thead><tr><th>Product</th><th>Current step</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="run in batch.runs" :key="run.id"><td><RouterLink :to="'/products/'+run.product_id" class="product-name">{{ products?.find(p=>p.id===run.product_id)?.name || run.product_id.slice(0,8) }}</RouterLink><span class="subline mono">{{ products?.find(p=>p.id===run.product_id)?.sku }}</span></td><td>{{ run.step }}<span v-if="run.error" class="subline error-text">{{ run.error }}</span></td><td><StatusPill :status="run.status" /></td><td><div class="actions"><RouterLink :to="'/review/'+run.id" class="text-link">{{ run.status==='waiting_review'?'Review':'Inspect' }}<ArrowRight :size="14" /></RouterLink><Button v-if="run.status==='failed'" variant="outline" size="sm" :disabled="busy===run.id" @click="action(run.id,'retry')"><RefreshCw :size="14" />Retry</Button><Button v-if="!['completed','cancelled'].includes(run.status)" variant="ghost" size="sm" :disabled="busy===run.id" @click="action(run.id,'cancel')" :aria-label="'Cancel run '+run.id"><X :size="14" />Cancel</Button></div></td></tr></tbody></table></div></section>
</template>
