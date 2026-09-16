<script setup lang="ts">
import { label } from '@/lib/utils'
defineProps<{ status: string }>()
</script>
<template><span class="status" :class="'status-' + status"><span class="status-dot"></span>{{ label(status) }}</span></template>
