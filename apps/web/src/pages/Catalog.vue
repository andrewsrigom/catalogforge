<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Upload, Sparkles, ArrowUpRight, SlidersHorizontal, Package } from '@lucide/vue'
import { useData } from '@/composables/data'
import { post, type Product, type Category, type Schema } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import Notice from '@/components/Notice.vue'
const router = useRouter()
const { data: products, error, isPending } = useData<Product[]>('/products', true)
const { data: categories } = useData<Category[]>('/categories')
const search = ref(''), filter = ref('all'), selected = ref<string[]>([]), dialog = ref(false), busy = ref(false), actionError = ref<unknown>(null), attributes = ref<string[]>([])
const filtered = computed(() => (products.value || []).filter(p => (!search.value || [p.sku,p.name,p.manufacturer,p.model,p.mpn].join(' ').toLowerCase().includes(search.value.toLowerCase())) && (filter.value === 'all' || (filter.value === 'incomplete' ? p.missing.length > 0 : p.validation_failures > 0))))
const allSelected = computed(() => filtered.value.length > 0 && filtered.value.every(p => selected.value.includes(p.id)))
const compatibleAttributes = computed(() => {
  const ids = new Set((products.value || []).filter(p => selected.value.includes(p.id)).map(p => p.category_id))
  const schemas = (categories.value || []).filter(c => ids.has(c.id))
  return (schemas[0]?.definition.attributes || []).filter(a => schemas.every(c => c.definition.attributes.some(other => other.key === a.key)))
})
function toggleAll() { selected.value = allSelected.value ? [] : filtered.value.map(p => p.id) }
async function enrich() {
  busy.value = true; actionError.value = null
  try { await post<Schema['BatchOut']>('/batches', { product_ids: selected.value, attributes: attributes.value }); dialog.value = false; await router.push('/runs') }
  catch (e) { actionError.value = e } finally { busy.value = false }
}
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">YOUR PRODUCT RECORDS</span><h1>Product catalog</h1><p>See what's missing. Build on what you already know.</p></div><div class="actions"><RouterLink to="/import" class="button-outline"><Upload :size="16" />Import CSV</RouterLink><Button :disabled="!selected.length" @click="dialog = true"><Sparkles :size="16" />Enrich selected<span v-if="selected.length" class="button-count">{{ selected.length }}</span></Button></div></div>
  <Notice :error="error || actionError" />
  <section class="panel table-panel"><div class="table-toolbar"><div class="search-field"><Search :size="17" /><Input v-model="search" aria-label="Search products" placeholder="Search products, models or part numbers…" /></div><div class="filter-control"><SlidersHorizontal :size="15" /><select v-model="filter" aria-label="Catalog filter"><option value="all">All products</option><option value="incomplete">Missing attributes</option><option value="invalid">Validation issues</option></select></div><span class="table-count">{{ filtered.length }} products</span></div>
    <div v-if="isPending" class="loading">Loading products…</div><div v-else-if="!filtered.length" class="empty-state"><Package /><h2>No matching products</h2><p>Import a catalog or adjust your filters.</p><RouterLink to="/import" class="button-primary">Import catalog</RouterLink></div>
    <div v-else class="table-scroll"><table><thead><tr><th class="checkbox-cell"><input type="checkbox" :checked="allSelected" @change="toggleAll" aria-label="Select all products" /></th><th>Product / SKU</th><th>Manufacturer & model</th><th>Variant</th><th>Completeness</th><th>Validation</th><th></th></tr></thead><tbody><tr v-for="product in filtered" :key="product.id" :class="{ 'selected-row': selected.includes(product.id) }"><td><input v-model="selected" type="checkbox" :value="product.id" :aria-label="'Select ' + product.sku" /></td><td><RouterLink :to="'/products/' + product.id" class="product-name">{{ product.name }}</RouterLink><span class="subline mono">{{ product.sku }}</span></td><td><strong>{{ product.manufacturer }}</strong><span class="subline">{{ product.model }}<span class="muted"> · {{ product.mpn }}</span></span></td><td><span class="variant-tag">{{ product.variant.size || '—' }}</span><span class="muted">{{ product.variant.coating }}</span></td><td><div class="completeness"><span>{{ product.completeness }}%</span><div class="progress-track"><span :style="{ width: product.completeness + '%' }"></span></div></div><span class="subline">{{ product.missing.length }} missing attributes</span></td><td><span class="validation-label" :class="{ warning: product.validation_failures > 0 }">{{ product.validation_failures ? product.validation_failures + ' issue(s)' : 'No invalid values' }}</span></td><td><RouterLink :to="'/products/' + product.id" class="icon-button" :aria-label="'Open ' + product.sku"><ArrowUpRight :size="17" /></RouterLink></td></tr></tbody></table></div>
    <div class="table-footer"><span>{{ selected.length }} selected</span><span>Completeness measures required fields. Evidence coverage is tracked separately.</span></div>
  </section>
  <Dialog v-model:open="dialog"><DialogContent><DialogHeader><DialogTitle>Enrich {{ selected.length }} selected products</DialogTitle><DialogDescription>Choose attributes to investigate. Existing values stay intact; contradictions are flagged for review.</DialogDescription></DialogHeader><fieldset class="attribute-picker"><legend>Leave all unchecked to inspect all attributes</legend><label v-for="attr in compatibleAttributes" :key="attr.key"><input v-model="attributes" type="checkbox" :value="attr.key" />{{ attr.label }}</label></fieldset><Notice :error="actionError" /><DialogFooter><Button variant="outline" @click="dialog = false">Cancel</Button><Button :disabled="busy" @click="enrich">{{ busy ? 'Starting…' : 'Start enrichment' }}<Sparkles :size="16" /></Button></DialogFooter></DialogContent></Dialog>
</template>
