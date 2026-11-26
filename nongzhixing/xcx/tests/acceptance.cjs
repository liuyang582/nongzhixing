const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const root=path.join(__dirname,'../miniprogram')
const {mapData,wgsToGcj}=require('../miniprogram/utils/geometry')
assert.equal(mapData({id:1,data:{}}).hasLocation,false)
assert.equal(mapData({id:1,data:{longitude:'120',latitude:30}}).hasLocation,false)
assert.equal(mapData({id:1,data:{longitude:0,latitude:0}}).hasLocation,true)
const ring=[[120,30],[120.01,30],[120.01,30.01],[120,30]]
const geo=mapData({id:2,title:'样本',data:{geometry:{type:'MultiPolygon',coordinates:[[ring],[ring]]}}})
assert.equal(geo.polygons.length,2);assert.equal(geo.points.length,8)
assert.equal(geo.longitude,wgsToGcj(ring[0])[0]);assert.equal(ring[0][0],120)
assert.equal(mapData({id:3,data:{geometry:{type:'Polygon',coordinates:[[[999,30],[120,30],[120,31]]]}}}).hasLocation,false)
function page(name,api){let page;vm.runInNewContext(fs.readFileSync(path.join(root,'pages',name,'index.js'),'utf8'),{Page:x=>page=x,require:name=>name.includes('geometry')?{mapData}:api,wx:{stopPullDownRefresh(){},reLaunch(){},navigateTo(){},createMapContext(){return {includePoints(){}}}},getApp:()=>({globalData:{}})});page.data=JSON.parse(JSON.stringify(page.data));page.setData=function(v){Object.assign(this.data,v)};return page}
;(async()=>{
 const user={role:'regulator',org:'监管',district:'乡镇'}
 const row={id:10,title:'地块',data:{longitude:120,latitude:30},demo:false}
 const calls=[]
 const api={session:async()=>user,request:async url=>{calls.push(url);return url==='/modules'?[]:{items:url.includes('/lands')?[row]:[{id:11,data:{plot_id:10}},{id:12,data:{plot_id:99}}],total:url.includes('/lands')?1:2}}}
 const list=page('index',api);await list.onShow();assert.equal(list.data.allowed,true);assert.equal(list.data.total,1)
 const detail=page('land',api);detail.id=10;await detail.load();assert.equal(detail.data.row.id,10);assert.equal(detail.data.growth.length,1);assert.equal(detail.data.tasks.length,1);assert.equal(detail.data.error,'');assert.equal(detail.data.hasLocation,true)
 const denied=page('land',{session:async()=>({role:'admin'}),request:async()=>[]});denied.id=10;await denied.load();assert.match(denied.data.error,/权限/)
 assert.ok(calls.every(x=>!x.includes('import')))
 console.log('PASS 坐标、无定位、MultiPolygon、无效边界、监管权限、档案与关联记录隔离')
 for(const role of ['farmer','regulator','admin']){
   const res=await fetch('http://127.0.0.1:5173/api/auth/login',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:role,password:String.fromCharCode(100,101,109,111,49,50,51)})});assert.equal(res.status,200);const auth=await res.json();
   const result=await fetch('http://127.0.0.1:5173/api/records/lands?size=20&page=1',{headers:{Authorization:'Bearer '+auth.token}});assert.equal(result.status,role==='admin'?403:200);if(result.ok){const data=await result.json();assert.ok(Array.isArray(data.items));console.log('PASS '+role+' 地块查询 '+data.total+' 条')}else console.log('PASS admin 地块权限拒绝')
 }
})().catch(e=>{console.error('FAIL '+e.message);process.exitCode=1})
