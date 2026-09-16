import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api, workspace, session, ApiError } from '@/api/client'

export function useData<T>(path: MaybeRefOrGetter<string>, polling = false) {
  return useQuery({
    queryKey: computed(() => [workspace.value, toValue(path)]),
    queryFn: () => api<T>(toValue(path)),
    refetchInterval: polling ? 2000 : false,
    enabled: computed(() => !!session.value && !!workspace.value),
    retry: (count, error) => count < 1 && (!(error instanceof ApiError) || error.status >= 500),
  })
}
