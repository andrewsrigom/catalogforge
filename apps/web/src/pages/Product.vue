<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Sparkles, ArrowRight } from '@lucide/vue'
import { useData } from '@/composables/data'
import { post, type Product, type Schema, type Category } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
import { display, date } from '@/lib/utils'
const route=useRoute(), router=useRouter()
const { data:product,error }=useData<Product>(()=>'/products/'+route.params.id,true)
const { data:categories }=useData<Category[]>('/categories')
const { data:batches }=useData<Schema['BatchOut'][]>('/batches',true)
const { data:history }=useData<{revision:number;values:Record<string,unknown>;actor_id:string;created_at:string}[]>(()=>'/products/'+route.params.id+'/history',true)
const schema=computed(()=>categories.value?.find(c=>c.id===product.value?.category_id))
const runs=computed(()=>batches.value?.flatMap(b=>b.runs).filter(r=>r.product_id===product.value?.id) || [])
const busy=ref(false), actionError=ref<unknown>(null)
async function enrich() { if(!product.value)return;busy.value=true;try{ const batch=await post<Schema['BatchOut']>('/batches',{product_ids:[product.value.id]});await router.push('/review/'+batch.runs[0]?.id) }catch(e){actionError.value=e}finally{busy.value=false} }
</script>
<template>
  <RouterLink to="/catalog" class="back-link"><ArrowLeft :size="16" />Product catalog</RouterLink><Notice :error="error || actionError" />
  <template v-if="product"><div class="page-heading"><div><span class="eyebrow">{{ product.sku }}</span><h1>{{ product.name }}</h1><p>{{ product.manufacturer }} · {{ product.model }} · {{ product.mpn }} · Revision {{ product.revision }}</p></div><Button :disabled="busy" @click="enrich"><Sparkles :size="16" />Enrich product</Button></div>
  <div class="product-metrics"><div><strong>{{ product.completeness }}%</strong><span>Required fields populated</span></div><div><strong>{{ product.evidence_coverage }}%</strong><span>Attributes with approved source evidence</span></div><div><strong>{{ product.validation_failures }}</strong><span>Invalid current values</span></div></div>
  <div class="product-detail-grid"><section class="panel table-panel"><div class="section-heading"><h2>Product attributes</h2><span>{{ schema?.definition.name }}</span></div><table><thead><tr><th>Attribute</th><th>Original</th><th>Current value</th><th>Source</th></tr></thead><tbody><tr v-for="attr in schema?.definition.attributes" :key="attr.key"><td>{{ attr.label }}<span v-if="attr.required" class="required">*</span></td><td class="muted">{{ display(product.attributes[attr.key]) }}</td><td><strong>{{ display(product.approved[attr.key] ?? product.attributes[attr.key]) }}</strong><span v-if="display(product.approved[attr.key] ?? product.attributes[attr.key]) !== 'Unknown' && attr.unit"> {{ attr.unit }}</span></td><td><span v-if="attr.key in product.approved" class="status status-approved">Reviewed change</span><span v-else class="muted">{{ display(product.attributes[attr.key])==='Unknown'?'Awaiting evidence':'Imported value' }}</span></td></tr></tbody></table></section>
  <section class="panel product-history"><h2>Enrichment & review</h2><div v-if="!runs.length" class="empty-inline">No enrichment runs for this product yet.</div><RouterLink v-for="run in runs" :key="run.id" :to="'/review/'+run.id" class="product-run"><StatusPill :status="run.status" /><small>{{ date(run.created_at) }}</small><span>View proposals & evidence<ArrowRight :size="14" /></span></RouterLink><h3>Revision history</h3><p v-if="!history?.length" class="muted">Original import · Revision 1</p><div v-for="revision in history" :key="revision.revision" class="revision"><strong>Revision {{ revision.revision }}</strong><small>{{ date(revision.created_at) }}</small><p>{{ Object.keys(revision.values).length }} approved attributes</p></div></section></div>
  <details class="diagnostics"><summary>Preserved original row</summary><pre>{{ JSON.stringify(product.original,null,2) }}</pre></details></template>
</template>
