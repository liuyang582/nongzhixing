// 微信宿主契约回归：不访问真实账号、数据库、文件或设备权限。
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const results = []
function harness() {
  const storage = new Map([['nx-token', 'synthetic-token']]), calls = [], app = {globalData:{user:{id:1}}}
  const wx = {
    getStorageSync:k=>storage.get(k), removeStorageSync:k=>storage.delete(k),
    reLaunch:o=>calls.push(['reLaunch',o]),
    request:o=>{ calls.push(['request',o]); o.success({statusCode:200,data:{ok:true}}) },
    downloadFile:o=>{calls.push(['download',o]);o.success({statusCode:200,tempFilePath:'/synthetic/file'})},
    openDocument:o=>{calls.push(['document',o]);o.success()},
    previewImage:o=>calls.push(['image',o]),
    shareFileMessage:o=>{calls.push(['share',o]);o.success()},
    uploadFile:o=>{calls.push(['upload',o]);o.success({statusCode:200,data:'{"id":1}'})}
  }
  const module = {exports:{}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../miniprogram/utils/api.js'),'utf8'),{module,wx,getApp:()=>app,require:()=>({baseUrl:'http://isolated.invalid/api/'})})
  return {api:module.exports,wx,storage,calls,app}
}
async function test(name,run) {await run();results.push(name);console.log('PASS '+name)}
;(async()=>{
 await test('请求拼接地址、传递认证并保留超时',async()=>{const h=harness();await h.api.request('/ai/analyze',{method:'POST',data:{question:'synthetic'},timeout:180000});const o=h.calls[0][1];assert.equal(o.url,'http://isolated.invalid/api/ai/analyze');assert.equal(o.header.Authorization,'Bearer synthetic-token');assert.equal(o.timeout,180000)})
 await test('会话过期清除本地状态并返回登录',async()=>{const h=harness();h.wx.request=o=>o.success({statusCode:401,data:{detail:'expired'}});await assert.rejects(h.api.request('/auth/me'),/expired/);assert.equal(h.storage.has('nx-token'),false);assert.equal(h.app.globalData.user,null);assert.equal(h.calls[0][1].url,'/pages/login/index')})
 await test('登录失败不触发循环跳转',async()=>{const h=harness();h.wx.request=o=>o.success({statusCode:401,data:{detail:'bad login'}});await assert.rejects(h.api.request('/auth/login'),/bad login/);assert.equal(h.calls.length,0)})
 await test('422字段错误可关联到表单字段',async()=>{const h=harness();h.wx.request=o=>o.success({statusCode:422,data:{detail:[{loc:['body','quantity'],msg:'invalid quantity'}]}});await assert.rejects(h.api.request('/orders'),e=>e.fields.quantity==='invalid quantity')})
 await test('AI网络中断提示检查历史避免重复提交',async()=>{const h=harness();h.wx.request=o=>o.fail();await assert.rejects(h.api.request('/ai/analyze'),/历史.*重复提交/)})
 await test('分页读取保留已有查询条件',async()=>{const h=harness();let n=0;h.wx.request=o=>{assert.match(o.url,/status=done&size=200&page=/);o.success({statusCode:200,data:{items:[{id:++n}],total:2}})};assert.equal((await h.api.all('/records/tasks?status=done')).length,2);assert.equal(n,2)})
 await test('分页空结果终止而非无限请求',async()=>{const h=harness();let n=0;h.wx.request=o=>{n++;o.success({statusCode:200,data:{items:[],total:100}})};assert.equal((await h.api.all('/records/tasks')).length,0);assert.equal(n,1)})
 await test('文档下载传递认证并启用预览菜单',async()=>{const h=harness();await h.api.download('/reports/tasks/pdf','任务.pdf');assert.equal(h.calls[0][1].header.Authorization,'Bearer synthetic-token');assert.equal(h.calls[1][1].fileType,'pdf');assert.equal(h.calls[1][1].showMenu,true)})
 await test('二维码下载使用图片预览',async()=>{const h=harness();await h.api.download('/traces/1/qr','二维码.png');assert.equal(h.calls[1][0],'image')})
 await test('下载拒绝权限错误文件',async()=>{const h=harness();h.wx.downloadFile=o=>o.success({statusCode:403,tempFilePath:'/synthetic/denied'});await assert.rejects(h.api.download('/reports/tasks/pdf','任务.pdf'),/权限/);assert.equal(h.calls.length,0)})
 await test('原生预览失败明确反馈',async()=>{const h=harness();h.wx.openDocument=o=>o.fail();await assert.rejects(h.api.download('/reports/tasks/pdf','任务.pdf'),/无法预览/)})
 await test('附件上传解析成功及损坏响应',async()=>{const h=harness();assert.equal((await h.api.upload({path:'/synthetic/attachment'})).id,1);h.wx.uploadFile=o=>o.success({statusCode:200,data:'broken'});await assert.rejects(h.api.upload({path:'/synthetic/attachment'}),/无法解析/)})
 fs.writeFileSync(path.join(__dirname,'../../outputs/小程序宿主契约验收.json'),JSON.stringify({environment:'模拟微信宿主，不等同于设备端验收',passed:results.length,results},null,2))
 console.log('TOTAL '+results.length+' PASS')
})().catch(e=>{console.error(e.message);process.exitCode=1})
