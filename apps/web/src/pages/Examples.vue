<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { BookOpen, Download, ArrowRight, Check, Play, Files } from '@lucide/vue'
import { useData } from '@/composables/data'
import { api, post, download, workspace, session, setSession, type Schema, type Session } from '@/api/client'
import { Button } from '@/components/ui/button'
import Notice from '@/components/Notice.vue'
import StatusPill from '@/components/StatusPill.vue'
const router=useRouter(), query=useQueryClient()
const {data,error,isPending}=useData<Schema['ExampleCollection']>('/examples',true)
const busy=ref(''),actionError=ref<unknown>(null),filter=ref('all')
const canInstall=computed(()=>['owner','reviewer'].includes(session.value?.workspaces.find(w=>w.id===workspace.value)?.role || ''))
const cases=computed(()=>(data.value?.cases || []).filter(c=>filter.value==='all' || (filter.value==='ready' ? c.status==='waiting_review' : !c.run_id)))
async function openCollection() {
  busy.value='install'; actionError.value=null
  try {
    const result=data.value?.workspace_id ? data.value : await post<Schema['ExampleCollection']>('/examples/install')
    setSession(await api<Session>('/auth/me'))
    workspace.value=result.workspace_id || ''; localStorage.setItem('catalogforge-workspace',workspace.value)
    await query.invalidateQueries()
  } catch(e){actionError.value=e} finally{busy.value=''}
}
async function run(example: Schema['ExampleCase']) {
  if(example.run_id) return router.push('/review/'+example.run_id)
  busy.value=example.sku;actionError.value=null
  try { const run=await post<Schema['RunOut']>('/examples/'+example.sku+'/run'); await query.invalidateQueries(); await router.push('/review/'+run.id) }
  catch(e){actionError.value=e}finally{busy.value=''}
}
async function getFile(filename:string){try{await download('/examples/files/'+filename,filename)}catch(e){actionError.value=e}}
</script>
<template>
 <div class="page-heading"><div><span class="eyebrow">LEARN BY REVIEWING</span><h1>Everyday examples</h1><p>Practice the decisions that make a catalog trustworthy.</p></div><Button variant="outline" @click="getFile('northstar-examples.zip')"><Download :size="16"/>Download example kit</Button></div>
 <section class="walkthrough-entry panel"><div><strong>A complete decision in about three minutes</strong><p>One product, two sources and a guided review from start to finish.</p></div><RouterLink to="/walkthrough" class="button-primary">Open guided walkthrough<ArrowRight :size="15"/></RouterLink></section>
 <Notice :error="error || actionError"/><div v-if="isPending" class="loading">Loading the example collection…</div>
 <template v-if="data">
  <section class="examples-hero panel"><div><span class="eyebrow">NORTHSTAR SAFETY · FICTIONAL COLLECTION</span><h2>Twelve products.<br/>Twelve useful decisions.</h2><p>{{ data.description }}</p><p class="muted">All specifications are synthetic training data. Your existing catalog stays in its own workspace.</p></div><div class="examples-start"><BookOpen :size="32"/><strong>{{ data.workspace_id ? data.sources_ready + ' / ' + data.sources_total + ' sources ready' : 'A separate practice workspace' }}</strong><span>PDF datasheets · supplier CSV · technical bulletins</span><Button v-if="workspace !== data.workspace_id" :disabled="!!busy || (!data.workspace_id && (!canInstall || data.mode !== 'fixture'))" @click="openCollection">{{ data.workspace_id ? 'Open example workspace' : 'Set up guided examples' }}<ArrowRight :size="16"/></Button><span v-else class="match-label"><Check :size="16"/>Example workspace is open</span></div></section>
  <Notice v-if="data.mode !== 'fixture'" message="Guided examples run in fixture mode, without paid model calls. Switch AI_MODE to fixture to set up or run this collection."/>
  <div class="examples-toolbar"><label>Show<select v-model="filter" aria-label="Example filter"><option value="all">All examples</option><option value="ready">Ready for review</option><option value="new">Not started</option></select></label><Button variant="ghost" size="sm" @click="getFile('01-northstar-datasheets.pdf')"><Files :size="16"/>Read sample datasheets</Button></div>
  <div v-if="!cases.length" class="panel empty-inline">No examples match this filter.</div>
  <section class="examples-grid"><article v-for="(example,index) in cases" :key="example.sku" class="panel example-card"><div class="example-top"><span class="example-number">{{ example.sku }}</span><StatusPill v-if="example.run_id" :status="example.status"/><span v-else class="muted">Not started</span></div><h2>{{ example.title }}</h2><p>{{ example.context }}</p><div class="example-outcome"><span>WHAT TO CHECK</span><p>{{ example.outcome }}</p></div><div class="example-bottom"><small>{{ example.name }}</small><Button size="sm" :disabled="!!busy || workspace !== data.workspace_id || (!example.run_id && (data.sources_ready !== data.sources_total || data.mode !== 'fixture'))" @click="run(example)"><Play v-if="!example.run_id" :size="14"/>{{ busy===example.sku ? 'Starting…' : example.run_id ? 'Open review' : 'Try this example' }}<ArrowRight :size="14"/></Button></div></article></section>
 </template>
</template>
