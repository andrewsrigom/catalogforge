<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { BookOpen, LayoutDashboard, Package, Files, ListChecks, GitBranch, ScanLine, Download, Settings, ChevronDown, LogOut, ArrowRight, ShieldCheck } from '@lucide/vue'
import { api, post, session, authNotice, setSession, workspace, type Session } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import Notice from '@/components/Notice.vue'
import BrandMark from '@/components/BrandMark.vue'

const route = useRoute()
const router = useRouter()
const query = useQueryClient()
const booting = ref(true)
const email = ref('reviewer@catalogforge.local')
const password = ref('CatalogForge-demo-2026!')
const busy = ref(false)
const error = ref<unknown>(null)
const nav = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/catalog', label: 'Product catalog', icon: Package },
  { to: '/sources', label: 'Source library', icon: Files },
  { to: '/schemas', label: 'Category schemas', icon: ListChecks },
  { to: '/runs', label: 'Enrichment runs', icon: GitBranch },
  { to: '/review', label: 'Review workspace', icon: ScanLine },
  { to: '/walkthrough', label: 'Guided walkthrough', icon: GitBranch },
  { to: '/examples', label: 'Guided examples', icon: BookOpen },
  { to: '/exports', label: 'Exports', icon: Download },
]
watch(session, value => { if (!value) { query.cancelQueries(); query.clear() } })
const selectedWorkspace = computed(() => session.value?.workspaces.find(w => w.id === workspace.value))
onMounted(async () => {
  try { setSession(await api<Session>('/auth/me')) } catch { /* Explicit sign-in screen. */ }
  booting.value = false
})
async function signIn() {
  busy.value = true; error.value = null
  try { query.clear(); setSession(await post<Session>('/auth/login', { email: email.value, password: password.value })); await router.push(route.meta.public ? '/walkthrough' : route.fullPath) }
  catch (e) { error.value = e } finally { busy.value = false }
}
async function signOut() {
  try { await post('/auth/logout'); session.value = null; query.clear() } catch (e) { error.value = e }
}
function switchWorkspace() { localStorage.setItem('catalogforge-workspace', workspace.value); query.clear(); router.push('/') }
</script>
<template>
  <RouterView v-if="route.meta.public" />
  <div v-else-if="booting" class="boot"><BrandMark /> Opening CatalogForge…</div>
  <div v-else-if="!session" class="login-layout">
    <section class="login-story">
      <div class="brand"><BrandMark />CatalogForge</div>
      <div class="login-copy"><span class="eyebrow">KNOW WHAT'S BEHIND EVERY VALUE</span><h1>Product data.<br />With the proof.</h1><p>Turn incomplete product records into structured, evidence-backed catalog data.</p>
        <div class="proof-card"><span class="proof-label">FG-100 · Protective work glove</span><div class="proof-row"><span>Overall length</span><strong>230 mm</strong></div><div class="proof-evidence"><ShieldCheck :size="18" /><span>“Length: 23 cm”<small>Technical record · Exact product match</small></span></div></div>
      </div>
      <span class="story-footer">Original records preserved. Every change reviewed.</span>
    </section>
    <section class="login-form"><div><div class="brand brand-login-mobile"><BrandMark />CatalogForge</div><span class="eyebrow">YOUR CATALOG WORKSPACE</span><h2>Welcome back</h2><p class="muted">Sign in to review evidence and enrich your catalog.</p><Notice :error="error" :message="authNotice" />
      <form @submit.prevent="signIn" class="form-stack"><label>Email<Input v-model="email" type="email" autocomplete="username" required /></label><label>Password<Input v-model="password" type="password" autocomplete="current-password" required /></label><Button type="submit" :disabled="busy">{{ busy ? 'Signing in…' : 'Sign in to workspace' }}<ArrowRight :size="16" /></Button></form>
      <p class="demo-login">Local demonstration account prefilled.<br />Synthetic products and source documents.</p>
    </div></section>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <RouterLink to="/" class="brand"><BrandMark />CatalogForge</RouterLink>
      <label class="workspace-label"><span>WORKSPACE</span><select v-model="workspace" @change="switchWorkspace" aria-label="Workspace"><option v-for="w in session.workspaces" :key="w.id" :value="w.id">{{ w.name }}</option></select></label>
      <div class="nav-section-label">WORKSPACE</div>
      <nav aria-label="Main navigation"><RouterLink v-for="item in nav" :key="item.to" :to="item.to" :class="{ active: item.to === '/' ? route.path === '/' : route.path.startsWith(item.to) }"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></RouterLink></nav>
      <div class="sidebar-bottom"><RouterLink to="/product-story" class="settings-link"><BookOpen :size="18" />About CatalogForge</RouterLink><RouterLink to="/settings" class="settings-link"><Settings :size="18" />Settings</RouterLink>
        <div class="user-card"><span class="avatar">{{ session.name.split(' ').map(n => n[0]).join('') }}</span><div><strong>{{ session.name }}</strong><small>{{ selectedWorkspace?.role }}</small></div><button @click="signOut" class="icon-button" aria-label="Sign out"><LogOut :size="16" /></button></div>
      </div>
    </aside>
    <div class="workspace-main">
      <header class="topbar"><div><span class="muted">Workspace</span><span class="breadcrumb-slash">/</span><strong>{{ route.meta.title }}</strong></div><span class="topbar-note"><ShieldCheck :size="15" />Evidence before approval</span></header>
      <main><Notice :error="error" /><RouterView :key="workspace" /></main>
    </div>
  </div>
</template>
