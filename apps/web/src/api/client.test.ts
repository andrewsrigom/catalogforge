import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { api, session, authNotice, ApiError, type Session } from './client'
const user={id:'reviewer',csrf:'old-session',workspaces:[]} as unknown as Session
beforeEach(()=>{session.value=user;authNotice.value=''})
afterEach(()=>{vi.unstubAllGlobals();session.value=null})
it('expired authenticated requests return to login with a useful message',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'Expired'}),{status:401})))
 await expect(api('/products')).rejects.toBeInstanceOf(ApiError)
 expect(session.value).toBeNull();expect(authNotice.value).toContain('Saved work is preserved')
})
it('a late failure from an old session cannot sign out a newly authenticated user',async()=>{
 let finish!:(value:Response)=>void
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>finish=resolve)))
 const request=api('/products');session.value={...user,csrf:'new-session'}
 finish(new Response(JSON.stringify({detail:'Expired'}),{status:401}))
 await expect(request).rejects.toThrow('Expired');expect(session.value?.csrf).toBe('new-session')
})
