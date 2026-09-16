<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, ArrowRight, FileSpreadsheet, Check } from '@lucide/vue'
import { useData } from '@/composables/data'
import { upload, post, type Category, type Schema } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
const router = useRouter()
const { data: categories } = useData<Category[]>('/categories')
const preview = ref<Schema['ImportOut'] | null>(null)
const categoryId = ref(''), mapping = ref<Record<string,string>>({}), busy = ref(false), error = ref<unknown>(null)
const category = computed(() => categories.value?.find(c => c.id === categoryId.value))
const fields = computed(() => [...new Set(['sku', 'name', 'manufacturer', 'model', 'mpn', ...(category.value?.definition.identity_fields || []), ...(category.value?.definition.attributes.map(a => a.key) || [])])])
const known: Record<string,string> = { sku: 'SKU', name: 'Product name', manufacturer: 'Manufacturer', model: 'Model', mpn: 'MPN', size: 'Size', coating: 'Coating', material: 'Material', length_mm: 'Length', pack_quantity: 'Pairs per pack', cut_level: 'Cut rating', touchscreen: 'Touchscreen', certification: 'Certification' }
async function selectFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  busy.value = true; error.value = null
  try {
    preview.value = await upload('/imports/preview', file)
    categoryId.value = categories.value?.[0]?.id || ''
    mapping.value = {}
    for (const [key, column] of Object.entries(known)) if (preview.value?.columns.includes(column)) mapping.value[key] = column
  } catch(e) { error.value = e } finally { busy.value = false }
}
async function confirm() {
  if (!preview.value) return
  busy.value = true; error.value = null
  try { await post('/imports/' + preview.value.id + '/confirm', { category_id: categoryId.value, mapping: mapping.value }); await router.push('/catalog') }
  catch(e) { error.value = e } finally { busy.value = false }
}
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">BRING YOUR DATA</span><h1>Import a product catalog</h1><p>Your original rows are preserved, including columns you don't map.</p></div></div>
  <Notice :error="error" />
  <div class="import-steps"><span :class="{ current: !preview }">1 · Upload CSV</span><ArrowRight :size="15" /><span :class="{ current: preview }">2 · Map & preview</span><ArrowRight :size="15" /><span>3 · Import products</span></div>
  <label class="upload-zone" :class="{ compact: preview }"><input type="file" accept=".csv,text/csv" @change="selectFile" :disabled="busy" aria-label="Upload catalog CSV" /><div class="upload-icon"><FileSpreadsheet :size="28" /></div><strong>{{ busy ? 'Reading your catalog…' : preview ? preview.filename : 'Choose a catalog CSV' }}</strong><span>UTF-8 encoding · up to 10,000 rows · 20 MB maximum</span><span class="button-outline"><Upload :size="15" />{{ preview ? 'Choose another file' : 'Browse files' }}</span></label>
  <template v-if="preview">
    <section class="panel import-mapping"><div class="section-heading"><div><h2>Match your columns</h2><p>{{ preview.rows.length }} rows found · {{ preview.columns.length }} source columns</p></div><label>Category schema<select v-model="categoryId"><option v-for="c in categories" :value="c.id" :key="c.id">{{ c.definition.name }} · v{{ c.version }}</option></select></label></div><div class="mapping-grid"><label v-for="field in fields" :key="field">{{ category?.definition.attributes.find(a => a.key === field)?.label || field }}<span v-if="['sku','manufacturer','model'].includes(field)" class="required">*</span><select v-model="mapping[field]" :aria-label="'Map ' + field"><option value="">Not mapped</option><option v-for="column in preview.columns" :key="column" :value="column">{{ column }}</option></select></label></div></section>
    <section class="panel table-panel"><div class="section-heading"><h2>Preview · first 5 rows</h2><span class="muted">Original source data</span></div><div class="table-scroll"><table><thead><tr><th v-for="column in preview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in preview.rows.slice(0,5)" :key="index"><td v-for="column in preview.columns" :key="column">{{ row[column] || '—' }}</td></tr></tbody></table></div></section>
    <div class="bottom-actions"><p><Check :size="16" />Populated fields are preserved during enrichment.</p><Button :disabled="busy || !categoryId || !mapping.sku || !mapping.manufacturer || !mapping.model" @click="confirm">Import {{ preview.rows.length }} products<ArrowRight :size="16" /></Button></div>
  </template>
</template>
