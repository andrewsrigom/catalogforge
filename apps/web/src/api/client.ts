import { ref } from 'vue'
import type { components } from './schema'

export type Schema = components['schemas']
export type Product = Schema['ProductOut']
export type Category = Schema['CategoryOut']
export type Run = Schema['RunOut']
export type Candidate = Schema['CandidateOut']
export type ReviewDetail = Schema['ReviewDetail']
export type Session = Schema['SessionOut']
export const session = ref<Session | null>(null)
export const authNotice = ref('')
export class ApiError extends Error { constructor(message: string, readonly status: number) { super(message) } }
export const workspace = ref(localStorage.getItem('catalogforge-workspace') || '')

async function responseFor(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && options.body) headers.set('Content-Type', 'application/json')
  if (workspace.value) headers.set('x-workspace-id', workspace.value)
  if (session.value) headers.set('x-csrf-token', session.value.csrf)
  const activeSession = session.value
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    if (response.status === 401 && activeSession && session.value?.csrf === activeSession.csrf) {
      session.value = null
      authNotice.value = 'Your session expired. Sign in again to continue. Saved work is preserved.'
    }
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    const message = typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail)
    throw new ApiError(message || 'Request failed', response.status)
  }
  return response
}
export async function apiBytes(path: string, signal?: AbortSignal): Promise<Uint8Array> {
  return new Uint8Array(await (await responseFor(path, { signal })).arrayBuffer())
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await responseFor(path, options)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
export function post<T>(path: string, data?: unknown): Promise<T> {
  return api<T>(path, { method: 'POST', ...(data !== undefined ? { body: JSON.stringify(data) } : {}) })
}
export async function upload<T>(path: string, file: File): Promise<T> {
  const body = new FormData()
  body.append('file', file)
  return api<T>(path, { method: 'POST', body })
}
export async function download(path: string, filename: string) {
  const activeSession = session.value
  const response = await fetch('/api' + path, { headers: { 'x-workspace-id': workspace.value }, credentials: 'same-origin' })
  if (!response.ok) {
    if (response.status === 401 && activeSession && session.value?.csrf === activeSession.csrf) { session.value = null; authNotice.value = 'Your session expired. Sign in again to download.' }
    throw new ApiError('Download failed. Check your workspace access.', response.status)
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function setSession(value: Session) {
  authNotice.value = ''
  session.value = value
  if (!value.workspaces.some(w => w.id === workspace.value)) workspace.value = value.workspaces[0]?.id || ''
  localStorage.setItem('catalogforge-workspace', workspace.value)
}
