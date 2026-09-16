// Retain the same key when a network failure leaves submission acknowledgement uncertain.
export function reviewRequestFactory() {
  let signature = '', key = ''
  return <T extends object>(body: T): T & { idempotency_key: string } => {
    const next = JSON.stringify(body)
    if (next !== signature) { signature = next; key = crypto.randomUUID() }
    return { ...body, idempotency_key: key }
  }
}
