import { expect, it } from 'vitest'
import { reviewRequestFactory } from './review-request'
it('reuses the request key after uncertain delivery but changes it for another decision',()=>{
 const make=reviewRequestFactory();const original={run_id:'run',interrupt_id:'interrupt',decisions:[{candidate_id:'a',action:'approve'}]}
 expect(make(original).idempotency_key).toBe(make({...original}).idempotency_key)
 expect(make({...original,interrupt_id:'next'}).idempotency_key).not.toBe(make(original).idempotency_key)
})
