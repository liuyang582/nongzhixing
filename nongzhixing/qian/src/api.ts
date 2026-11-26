export type User = {id:number;username:string;name:string;role:'farmer'|'regulator'|'admin';org:string;district:string;active:boolean}
export type FieldSpec = {key:string;label:string;type:'text'|'number'|'select'|'date'|'textarea';required:boolean;options:string[]}
export type ModuleSpec = {id:string;title:string;group:string;fields:FieldSpec[];roles:string[];note:string}
export type RecordRow = {id:number;module:string;title:string;status:string;data:Record<string,unknown>;demo:boolean;org:string;version:number;created_at:string;updated_at:string}
export type Stock = {id:number;crop:string;batch:string;grade:string;quantity:number;reserved:number;available:number;source:string;demo:boolean}
export type Order = {id:number;stock_id:number;customer:string;quantity:number;price:number;amount:number;status:string;created_at:string}
export type KnowledgeHit = {id:number;doc_id:string;title:string;domain_l1:string;domain_l2:string;crop:string[];region:string[];source:string;stability:string;risk_level:string;score:number;snippet:string}
export type KnowledgeDoc = {id:number;doc_id:string;title:string;domain_l1:string;domain_l2:string;crop:string[];region:string[];stage:string[];operation:string[];keywords:string[];queries:string[];source:string;stability:string;authority:string;confidence:string;risk_level:string;version:string;corpus:boolean;status:string;content:string}
export type AIJob = {id:number;kind:string;question:string;status:string;result:{answer:string;crop?:string;model?:string;plot?:string;plot_id?:number;growth_id?:number;photo_id?:number;land?:unknown;records?:RecordRow[];weather?:unknown;citations?:KnowledgeHit[];knowledge?:KnowledgeHit[]};steps:string[];task_id:number|null;created_at:string}
export const token = () => sessionStorage.getItem('nx-token') || ''
export async function api<T>(path:string, init:RequestInit={}):Promise<T>{
  const headers=new Headers(init.headers)
  if(token())headers.set('Authorization',`Bearer ${token()}`)
  if(init.body && !(init.body instanceof FormData))headers.set('Content-Type','application/json')
  let response:Response
  try{response=await fetch('/api'+path,{...init,headers})}catch{throw new Error('无法连接后端，请确认 FastAPI 已启动')}
  if(!response.ok){
    const body=await response.json().catch(()=>({detail:'服务暂不可用'}))
    if(response.status===401 && path!=='/auth/login'){sessionStorage.removeItem('nx-token');window.dispatchEvent(new Event('nx-unauthorized'))}
    throw new Error(typeof body.detail==='string'?body.detail:body.detail?.[0]?.msg||'请求校验失败')
  }
  return response.json() as Promise<T>
}
export const post=<T>(path:string,data:unknown)=>api<T>(path,{method:'POST',body:JSON.stringify(data)})
export async function download(path:string,name:string){
  const r=await fetch('/api'+path,{headers:{Authorization:`Bearer ${token()}`}})
  if(!r.ok)throw new Error('导出失败，请确认权限与服务状态')
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a')
  a.href=url;a.download=name;a.hidden=true;document.body.appendChild(a)
  try{a.click()}finally{
    a.remove()
    // Allow the browser to consume the object URL before releasing it.
    window.setTimeout(()=>URL.revokeObjectURL(url),30_000)
  }
}
