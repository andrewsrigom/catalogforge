import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }
export function display(value: unknown): string {
  if (value === undefined || value === null || value === '') return 'Unknown'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}
export function label(value: string): string { return value.replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase()) }
export function date(value: string): string { return new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }
