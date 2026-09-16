<script setup lang="ts">
import { AlertCircle } from '@lucide/vue'
defineProps<{ error?: unknown; message?: string }>()
</script>
<template><div v-if="error || message" class="notice" role="alert"><AlertCircle :size="17" /><span>{{ error instanceof Error ? error.message : message || String(error) }}</span></div></template>
