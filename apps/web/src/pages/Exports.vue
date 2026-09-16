<script setup lang="ts">
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { Download, FileArchive, ShieldCheck } from '@lucide/vue'
import { useData } from '@/composables/data'
import { post, download, type Schema } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import { date } from '@/lib/utils'
const { data: exports, error } = useData<Schema['ExportOut'][]>('/exports')
const query=useQueryClient(), busy=ref(false), actionError=ref<unknown>(null)
async function create() { busy.value=true; try { await post('/exports',{idempotency_key:crypto.randomUUID()}); await query.invalidateQueries() } catch(e) { actionError.value=e } finally { busy.value=false } }
async function getFile(id:string) { try { await download('/exports/'+id+'/file','catalogforge-'+id.slice(0,8)+'.zip') } catch(e) { actionError.value=e } }
</script>
<template>
  <div class="page-heading"><div><span class="eyebrow">READY FOR THE NEXT STEP</span><h1>Catalog exports</h1><p>Original data and approved changes, with the supporting evidence.</p></div><Button :disabled="busy" @click="create"><Download :size="16" />{{ busy?'Creating snapshot…':'Create export' }}</Button></div><Notice :error="error || actionError" />
  <div class="export-info"><span class="icon-tile"><FileArchive :size="25" /></span><div><h2>A complete, auditable package</h2><p>Each ZIP contains the catalog CSV, an evidence report in JSON, and export notes. Unapproved proposals are excluded. Manual edits are labeled separately.</p><span><ShieldCheck :size="15" />Exports are immutable snapshots of your workspace.</span></div></div>
  <section class="panel table-panel"><div class="section-heading"><h2>Export history</h2></div><div v-if="!exports?.length" class="empty-state"><Download :size="32" /><h2>No exports yet</h2><p>Create your first snapshot when you're ready.</p></div><table v-else><thead><tr><th>Export package</th><th>Created</th><th>Products</th><th></th></tr></thead><tbody><tr v-for="item in exports" :key="item.id"><td class="document-name"><FileArchive :size="20" />catalogforge-{{ item.id.slice(0,8) }}.zip</td><td>{{ date(item.created_at) }}</td><td>{{ item.row_count }}</td><td><Button variant="outline" size="sm" @click="getFile(item.id)"><Download :size="14" />Download</Button></td></tr></tbody></table></section>
</template>
