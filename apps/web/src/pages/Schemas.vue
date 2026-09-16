<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Plus, Save, Trash2, ListChecks } from '@lucide/vue'
import { useData } from '@/composables/data'
import { api, session, workspace, type Category, type Schema } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import Notice from '@/components/Notice.vue'
const { data: categories, error } = useData<Category[]>('/categories')
const query = useQueryClient(), selected = ref(''), busy = ref(false), actionError = ref<unknown>(null), saved = ref('')
const draft = ref<Schema['CategoryDefinition']>({ name: '', identity_fields: ['manufacturer','model','mpn','size','coating'], attributes: [] })
const isReviewer = computed(() => ['owner','reviewer'].includes(session.value?.workspaces.find(w=>w.id===workspace.value)?.role || ''))
function load(id: string) { selected.value = id; const category = categories.value?.find(c=>c.id===id); if(category) draft.value = JSON.parse(JSON.stringify(category.definition)); saved.value = '' }
watch(categories, list => { if(list?.length && !selected.value) load(list[0]!.id) }, { immediate: true })
function newCategory() { selected.value='new'; draft.value={name:'New category',identity_fields:['manufacturer','model','mpn','size'],attributes:[]}; add() }
function add() { draft.value.attributes.push({ key: 'attribute_' + (draft.value.attributes.length+1), label:'New attribute', type:'string', required:false, allowed_values:[], aliases:[], description:'', unit:null, minimum:null, maximum:null }) }
function list(value: string) { return value.split(',').map(v=>v.trim()).filter(Boolean) }
async function save() {
  busy.value=true; actionError.value=null; saved.value=''
  try { const result = await api<Category>('/categories' + (selected.value==='new' ? '' : '/' + selected.value), {method:selected.value==='new'?'POST':'PUT',body:JSON.stringify(draft.value)}); selected.value=result.id; saved.value='Saved as version ' + result.version + '. Existing proposals must be revalidated.'; await query.invalidateQueries() } catch(e) { actionError.value=e } finally { busy.value=false }
}
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">STRUCTURE YOUR PRODUCT DATA</span><h1>Category schemas</h1><p>Define what a complete, valid product record looks like.</p></div><Button variant="outline" :disabled="!isReviewer" @click="newCategory"><Plus :size="16" />New category</Button></div><Notice :error="error || actionError" /><div v-if="saved" class="success-banner">{{ saved }}</div>
  <section class="panel schema-editor"><div class="section-heading"><label>Category<select :value="selected" @change="load(($event.target as HTMLSelectElement).value)"><option v-for="c in categories" :key="c.id" :value="c.id">{{ c.definition.name }} · v{{ c.version }}</option><option v-if="selected==='new'" value="new">New category</option></select></label><Button :disabled="busy || !isReviewer || !draft.attributes.length" @click="save"><Save :size="16" />{{ busy?'Saving…':'Save new version' }}</Button></div>
  <div class="schema-basics"><label>Category name<Input v-model="draft.name" :disabled="!isReviewer" /></label><label>Product identity fields<Input :model-value="draft.identity_fields?.join(', ')" @update:model-value="draft.identity_fields=list(String($event))" :disabled="!isReviewer" /><small>Manufacturer and model are required. Include size and coating when variants differ.</small></label></div>
  <div class="section-heading"><h2>Attribute definitions</h2><span class="muted">Schema versions are immutable</span></div>
  <div v-for="(attr,index) in draft.attributes" :key="index" class="attribute-editor"><div class="attribute-editor-primary"><label>Key<Input v-model="attr.key" :disabled="!isReviewer" /></label><label>Display name<Input v-model="attr.label" :disabled="!isReviewer" /></label><label>Type<select v-model="attr.type" :disabled="!isReviewer"><option>string</option><option>number</option><option>boolean</option><option>enum</option></select></label><label class="checkbox-label"><input v-model="attr.required" type="checkbox" :disabled="!isReviewer" />Required</label><Button variant="ghost" size="icon" :disabled="!isReviewer" @click="draft.attributes.splice(index,1)" :aria-label="'Remove ' + attr.label"><Trash2 :size="16" /></Button></div>
    <details><summary>Extraction description, aliases & constraints</summary><div class="attribute-editor-details"><label>Description<Textarea v-model="attr.description" :disabled="!isReviewer" /></label><label>Aliases, separated by commas<Input :model-value="attr.aliases?.join(', ')" @update:model-value="attr.aliases=list(String($event))" :disabled="!isReviewer" /></label><label v-if="attr.type==='enum'">Allowed values<Input :model-value="attr.allowed_values?.join(', ')" @update:model-value="attr.allowed_values=list(String($event))" :disabled="!isReviewer" /></label><template v-if="attr.type==='number'"><label>Canonical unit<select v-model="attr.unit" :disabled="!isReviewer"><option :value="null">No unit</option><option v-for="unit in ['mm','cm','m','g','kg','items','pairs']" :key="unit">{{ unit }}</option></select></label><label>Minimum<input v-model.number="attr.minimum" type="number" :disabled="!isReviewer" /></label><label>Maximum<input v-model.number="attr.maximum" type="number" :disabled="!isReviewer" /></label></template></div></details>
  </div><Button variant="outline" :disabled="!isReviewer" @click="add"><Plus :size="16" />Add attribute</Button><p class="schema-note"><ListChecks :size="17" />Physical units can be converted. Items per box or pairs per pack always need explicit source evidence.</p></section>
</template>
