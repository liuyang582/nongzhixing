from pathlib import Path
import shutil
root=Path(__file__).parent
backup=root/'template-backup'
if not backup.exists():
    backup.mkdir()
    for name in ['app.js','app.json','app.wxss']:
        shutil.copy2(root/'miniprogram'/name,backup/name)
    shutil.copytree(root/'miniprogram/pages',backup/'pages')
files={
'utils/config.js':'''// 开发工具使用本机代理；真机须设置可访问的 HTTPS 后端 /api 地址。
module.exports = { baseUrl: 'http://127.0.0.1:5173/api' }
''',
'utils/api.js':'''const config = require('./config')
function logout() { wx.removeStorageSync('nx-token'); getApp().globalData.user = null }
function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('nx-token')
    wx.request({ url: config.baseUrl.replace(/\\/$/, '') + path,
      method: options.method || 'GET', data: options.data,
      header: { 'content-type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      timeout: 20000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) return resolve(res.data)
        if (res.statusCode === 401 && path !== '/auth/login') { logout(); wx.reLaunch({url:'/pages/login/index'}) }
        const detail = res.data && res.data.detail
        reject(new Error(typeof detail === 'string' ? detail : '请求失败，请检查权限与输入'))
      }, fail() { reject(new Error('无法连接后端，请检查服务地址、合法域名和网络')) }
    })
  })
}
async function session() {
  if (!wx.getStorageSync('nx-token')) { wx.reLaunch({url:'/pages/login/index'}); return null }
  const user = await request('/auth/me'); getApp().globalData.user = user; return user
}
module.exports = { request, session, logout }
''',
'app.js':'''App({ globalData: { user: null } })
''',
'app.json':'''{
  "pages": ["pages/login/index", "pages/index/index", "pages/land/index"],
  "window": {"backgroundColor":"#f4f7f3", "navigationBarBackgroundColor":"#f4f7f3", "navigationBarTitleText":"农知行", "navigationBarTextStyle":"black"},
  "sitemapLocation":"sitemap.json", "style":"v2", "lazyCodeLoading":"requiredComponents"
}
''',
'app.wxss':'''page{background:#f4f7f3;color:#243b2d;font-family:-apple-system,sans-serif;font-size:28rpx}.page{padding:32rpx 28rpx;padding-bottom:calc(36rpx + env(safe-area-inset-bottom))}.hero{padding:26rpx 4rpx 36rpx}.brand{color:#246b47;font-size:30rpx;font-weight:700;letter-spacing:4rpx}.title{font-size:46rpx;font-weight:700;margin:20rpx 0 12rpx}.muted{color:#748277;font-size:24rpx;line-height:1.7}.card{background:#fff;border:1rpx solid #e3ebe3;border-radius:24rpx;padding:30rpx;margin-bottom:24rpx}.row{display:flex;align-items:center;justify-content:space-between;gap:16rpx}.name{font-size:32rpx;font-weight:600;word-break:break-all;flex:1}.badge{background:#edf5ee;color:#246b47;padding:8rpx 14rpx;border-radius:10rpx;font-size:22rpx;flex-shrink:0}.demo{background:#fff5df;color:#986522}.label{color:#748277;font-size:24rpx;margin:24rpx 0 12rpx}input{height:88rpx;background:#f5f8f3;border:1rpx solid #e3ebe3;border-radius:14rpx;padding:0 22rpx;font-size:30rpx}button{font-size:28rpx;min-height:88rpx;border-radius:14rpx;margin:24rpx 0 0;background:#edf5ee;color:#246b47}button::after{border:0}.primary{background:#246b47;color:white}.error{color:#a23a32;background:#fff0ed;padding:22rpx;border-radius:14rpx;line-height:1.6;font-size:26rpx;margin-bottom:20rpx}.empty{text-align:center;padding:50rpx 20rpx;color:#748277}.section-title{font-size:32rpx;font-weight:600;margin-bottom:24rpx}.kv{display:flex;justify-content:space-between;gap:24rpx;padding:18rpx 0;border-bottom:1rpx solid #eef2ec;font-size:26rpx}.kv .key{color:#748277;flex-shrink:0;width:180rpx}.kv .value{word-break:break-all;text-align:right}.note{font-size:24rpx;color:#748277;line-height:1.8;margin-top:22rpx}.map{width:100%;height:600rpx;border-radius:18rpx;overflow:hidden}.link{color:#246b47;font-size:26rpx}.search{margin-bottom:20rpx}.actions{display:flex;gap:20rpx}.actions button{flex:1}.login-footer{text-align:center;margin-top:30rpx}.stats{display:flex;gap:20rpx;margin:24rpx 0}.stat{flex:1;background:#edf5ee;border-radius:16rpx;padding:22rpx}.stat strong{display:block;font-size:40rpx;font-weight:600}
''',
'pages/login/index.json':'{"navigationBarTitleText":"农知行 · 登录"}',
'pages/login/index.js':'''const {request, session} = require('../../utils/api')
Page({data:{username:'',password:'',busy:false,error:''},
  async onLoad(){if(wx.getStorageSync('nx-token')){try{if(await session())wx.reLaunch({url:'/pages/index/index'})}catch(e){this.setData({error:e.message})}}},
  input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value})},
  async login(){if(this.data.busy)return;const username=this.data.username.trim(),password=this.data.password;if(!username||!password){this.setData({error:'请填写账号和密码'});return}this.setData({busy:true,error:''});try{const r=await request('/auth/login',{method:'POST',data:{username,password}});wx.setStorageSync('nx-token',r.token);getApp().globalData.user=r.user;this.setData({password:''});wx.reLaunch({url:'/pages/index/index'})}catch(e){this.setData({error:e.message})}finally{this.setData({busy:false})}}
})
''',
'pages/login/index.wxml':'''<view class="page"><view class="hero"><view class="brand">农知行 · NONGZHIXING</view><view class="title">田间档案，随手查看。</view><view class="muted">连接 PC 生产台账，查看地块边界、位置与种植档案。</view></view><view class="card"><view class="section-title">登录农业工作台</view><view wx:if="{{error}}" class="error">{{error}}</view><view class="label">账号</view><input value="{{username}}" data-field="username" bindinput="input" placeholder="填写现有平台账号" maxlength="64"/><view class="label">密码</view><input value="{{password}}" password data-field="password" bindinput="input" placeholder="填写账号密码" maxlength="128" confirm-type="done" bindconfirm="login"/><button class="primary" loading="{{busy}}" disabled="{{busy}}" bindtap="login">登录工作台</button></view><view class="muted login-footer">共用平台账号 · 按权限查看地块</view></view>
''',
'pages/login/index.wxss':'',
'pages/index/index.json':'{"navigationBarTitleText":"农知行 · 我的地块","enablePullDownRefresh":true}',
'pages/index/index.js':'''const {request,session,logout}=require('../../utils/api')
Page({data:{user:null,rows:[],total:0,demoCount:0,q:'',page:1,busy:false,error:'',allowed:true},
  async onShow(){try{const user=await session();if(!user)return;this.setData({user});const modules=await request('/modules');const allowed=modules.some(m=>m.id==='lands');this.setData({allowed});if(allowed)await this.load(true)}catch(e){this.setData({error:e.message})}},
  searchInput(e){this.setData({q:e.detail.value})}, search(){this.load(true)},
  async load(reset){if(this.data.busy||!this.data.allowed)return;const page=reset?1:this.data.page+1;this.setData({busy:true,error:''});try{const r=await request('/records/lands?size=20&page='+page+'&q='+encodeURIComponent(this.data.q));const rows=reset?r.items:this.data.rows.concat(r.items);this.setData({rows,total:r.total,page,demoCount:rows.filter(x=>x.demo).length})}catch(e){this.setData({error:e.message})}finally{this.setData({busy:false});wx.stopPullDownRefresh()}},
  onPullDownRefresh(){this.load(true)},more(){this.load(false)},
  open(e){wx.navigateTo({url:'/pages/land/index?id='+e.currentTarget.dataset.id})},
  logout(){logout();wx.reLaunch({url:'/pages/login/index'})}
})
''',
'pages/index/index.wxml':'''<view class="page"><view class="hero"><view class="row"><view class="brand">农知行</view><text class="link" bindtap="logout">退出登录</text></view><view class="title">{{user.role==='regulator'?'辖区地块':'我的地块'}}</view><view class="muted">{{user.name}} · {{user.role==='regulator'?user.district:user.org}}</view></view><view wx:if="{{error}}" class="error">{{error}}<button bindtap="search">重试</button></view><view wx:if="{{!allowed}}" class="card muted">当前账号没有地块查看权限，请使用种植户或监管员账号。</view><block wx:else><view class="stats"><view class="stat"><view class="muted">授权地块</view><strong>{{total}}</strong></view><view class="stat"><view class="muted">已载入演示样本</view><strong>{{demoCount}}</strong></view></view><input class="search" value="{{q}}" bindinput="searchInput" bindconfirm="search" confirm-type="search" placeholder="搜索地块名称"/><button bindtap="search" loading="{{busy}}" disabled="{{busy}}">查询地块</button><view style="height:24rpx"></view><view wx:if="{{!rows.length &amp;&amp; !busy}}" class="card empty">暂无地块，请在 PC 端建档后刷新。</view><view wx:for="{{rows}}" wx:key="id" class="card" bindtap="open" data-id="{{item.id}}"><view class="row"><view class="name">{{item.title}}</view><text class="badge {{item.demo?'demo':''}}">{{item.demo?'演示':'用户录入'}}</text></view><view class="kv"><text class="key">作物</text><text class="value">{{item.data.crop||'未登记'}}</text></view><view class="kv"><text class="key">状态</text><text class="value">{{item.status}}</text></view><view class="row" style="margin-top:22rpx"><text class="muted">{{item.data.geometry?'已有边界':'查看定位与档案'}}</text><text class="link">查看档案 →</text></view></view><button wx:if="{{rows.length&lt;total}}" bindtap="more" loading="{{busy}}" disabled="{{busy}}">加载更多</button><view wx:if="{{busy &amp;&amp; !rows.length}}" class="empty">正在读取地块…</view></block><view class="note">地图边界和定位仅供生产管理参考。边界绘制与文件导入在 PC 端完成。</view></view>
''',
'pages/index/index.wxss':'',
'pages/land/index.json':'{"navigationBarTitleText":"地块档案","enablePullDownRefresh":true}',
'pages/land/index.js':'''const {request,session}=require('../../utils/api')
const {mapData}=require('../../utils/geometry')
Page({data:{row:null,fields:[],growth:[],tasks:[],markers:[],polygons:[],points:[],latitude:0,longitude:0,hasLocation:false,busy:false,error:'',relatedError:'',mapError:'',satellite:false},
  onLoad(options){this.id=Number(options.id);this.load()},
  async load(){if(this.data.busy)return;this.setData({busy:true,error:'',relatedError:'',mapError:''});try{if(!await session())return;if(!Number.isInteger(this.id)||this.id<=0)throw new Error('地块编号无效');const modules=await request('/modules');const land=modules.find(m=>m.id==='lands');if(!land)throw new Error('当前账号没有地块权限');const row=await this.find('/records/lands',this.id);if(!row)throw new Error('地块不存在或当前账号无权查看');const geo=mapData(row);const fields=land.fields.map(f=>({label:f.label,value:this.display(row.data[f.key])}));this.setData({row,fields,...geo});if(modules.some(m=>m.id==='growth')){try{const all=await this.all('/records/growth');this.setData({growth:all.filter(x=>Number(x.data.plot_id)===this.id)})}catch(e){this.setData({relatedError:e.message})}}if(modules.some(m=>m.id==='tasks')){try{const all=await this.all('/records/tasks');this.setData({tasks:all.filter(x=>Number(x.data.plot_id)===this.id)})}catch(e){this.setData({relatedError:e.message})}}}catch(e){this.setData({error:e.message})}finally{this.setData({busy:false});wx.stopPullDownRefresh()}},
  async all(path){let rows=[],page=1;while(true){const r=await request(path+'?size=200&page='+page);rows=rows.concat(r.items);if(rows.length>=r.total||!r.items.length)return rows;page++}},
  async find(path,id){let page=1;while(true){const r=await request(path+'?size=200&page='+page);const row=r.items.find(x=>x.id===id);if(row)return row;if(page*200>=r.total||!r.items.length)return null;page++}},
  display(v){return v===null||v===undefined||v===''?'未登记':typeof v==='object'?JSON.stringify(v):String(v)},
  onPullDownRefresh(){this.load()},
  readyMap(){this.fit()},fit(){if(this.data.points.length)wx.createMapContext('land-map',this).includePoints({points:this.data.points,padding:[40,30,40,30],fail:()=>this.setData({mapError:'地图范围调整失败，可手动缩放'})})},
  mapFail(){this.setData({mapError:'地图加载失败，请检查网络；档案仍可查看'})},
  satellite(){this.setData({satellite:!this.data.satellite})},
  openLocation(){if(!this.data.hasLocation)return;wx.openLocation({latitude:this.data.latitude,longitude:this.data.longitude,name:this.data.row.title,scale:16,fail:()=>wx.showToast({title:'无法打开位置，请重试',icon:'none'})})}
})
''',
'pages/land/index.wxml':'''<view class="page"><view wx:if="{{error}}" class="error">{{error}}<button bindtap="load">重试</button></view><view wx:if="{{busy &amp;&amp; !row}}" class="empty">正在读取档案…</view><block wx:if="{{row}}"><view class="hero"><view class="row"><view class="title">{{row.title}}</view><text class="badge {{row.demo?'demo':''}}">{{row.demo?'演示':'用户录入'}}</text></view><view class="muted">{{row.org}} · {{row.status}}</view></view><view class="card"><view class="section-title">边界与位置</view><map wx:if="{{hasLocation}}" id="land-map" class="map" latitude="{{latitude}}" longitude="{{longitude}}" scale="16" markers="{{markers}}" polygons="{{polygons}}" enable-satellite="{{satellite}}" bindupdated="readyMap" binderror="mapFail"/><view wx:else class="empty">尚未登记有效边界或经纬度，请在 PC 端补充。</view><view wx:if="{{mapError}}" class="error">{{mapError}}</view><view wx:if="{{hasLocation}}" class="actions"><button bindtap="openLocation">打开地块位置</button><button bindtap="satellite">{{satellite?'标准地图':'卫星底图'}}</button></view><view class="note">{{polygons.length?'展示已登记的外边界；含孔洞的地块不表示孔洞区域。':'当前仅展示登记位置，不代表已有实测边界。'}}卫星底图不包含自动识别或 NDVI。坐标为近似显示转换，面积以档案记录为准。</view></view><view class="card"><view class="section-title">地块档案</view><view class="kv" wx:for="{{fields}}" wx:key="label"><text class="key">{{item.label}}</text><text class="value">{{item.value}}</text></view><view class="kv"><text class="key">更新时间</text><text class="value">{{row.updated_at}}</text></view></view><view wx:if="{{relatedError}}" class="error">关联记录读取失败：{{relatedError}}</view><view class="card"><view class="section-title">关联生长记录 · {{growth.length}}</view><view wx:if="{{!growth.length}}" class="muted">暂无通过地块编号关联的生长记录。</view><view wx:for="{{growth}}" wx:key="id" class="kv"><text class="key">{{item.title}}</text><text class="value">{{item.data.stage||item.status}} · {{item.demo?'演示':'用户录入'}}</text></view></view><view class="card"><view class="section-title">关联农事任务 · {{tasks.length}}</view><view wx:if="{{!tasks.length}}" class="muted">暂无通过地块编号关联的农事任务。</view><view wx:for="{{tasks}}" wx:key="id" class="kv"><text class="key">{{item.title}}</text><text class="value">{{item.status}} · {{item.demo?'演示':'用户录入'}}</text></view></view></block></view>
''',
'pages/land/index.wxss':''
}
for name,content in files.items():
    p=root/'miniprogram'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8')
coords=Path('qian/src/amap-coordinates.mjs').read_text(encoding='utf-8').split('export function gcjToWgs')[0].replace('export function','function')
coords+='''
function valid(p){return Array.isArray(p)&&p.length>=2&&typeof p[0]==='number'&&typeof p[1]==='number'&&Number.isFinite(p[0])&&Number.isFinite(p[1])&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90}
function point(p){const c=wgsToGcj(p);return {longitude:c[0],latitude:c[1]}}
function mapData(row){
 const data=row.data||{},g=data.geometry;let polygons=[],points=[]
 const parts=g&&g.type==='Polygon'?[g.coordinates]:g&&g.type==='MultiPolygon'?g.coordinates:[]
 if(Array.isArray(parts))for(const rings of parts){const ring=Array.isArray(rings)&&rings[0];if(!Array.isArray(ring)||ring.length<3||!ring.every(valid))continue;const ps=ring.map(point);polygons.push({points:ps,strokeWidth:2,strokeColor:'#246b47',fillColor:'#52a56a44',zIndex:1});points=points.concat(ps)}
 const pos=valid([data.longitude,data.latitude])?point([data.longitude,data.latitude]):points[0]
 return {polygons,points:points.length?points:pos?[pos]:[],markers:pos?[{id:row.id,latitude:pos.latitude,longitude:pos.longitude,title:row.title,callout:{content:row.title,display:'ALWAYS',padding:8,borderRadius:8}}]:[],latitude:pos?pos.latitude:0,longitude:pos?pos.longitude:0,hasLocation:!!pos}
}
module.exports={wgsToGcj,mapData}
'''
(root/'miniprogram/utils/geometry.js').write_text(coords,encoding='utf-8')
for name in ['pages/index/index.js','pages/land/index.js']:
    p=root/'miniprogram'/name;s=p.read_text(encoding='utf-8')
    s=s.replace("const allowed=modules.some(m=>m.id==='lands')", "const allowed=user.role==='regulator'||modules.some(m=>m.id==='lands')")
    s=s.replace('if(!await session())return;', 'const user=await session();if(!user)return;')
    s=s.replace("const land=modules.find(m=>m.id==='lands');", "const land=modules.find(m=>m.id==='lands')||(user.role==='regulator'?{fields:[{key:'crop',label:'作物'},{key:'area',label:'登记面积（亩）'},{key:'measured_area',label:'测算面积（亩）'},{key:'latitude',label:'纬度'},{key:'longitude',label:'经度'},{key:'note',label:'档案说明'}]}:null);")
    s=s.replace("if(modules.some(m=>m.id==='growth'))", "if(user.role==='regulator'||modules.some(m=>m.id==='growth'))")
    s=s.replace("if(modules.some(m=>m.id==='tasks'))", "if(user.role==='regulator'||modules.some(m=>m.id==='tasks'))")
    s=s.replace('readyMap(){this.fit()}', 'readyMap(){if(this.fitted)return;this.fitted=true;this.fit()}')
    p.write_text(s,encoding='utf-8')
p=root/'miniprogram/pages/index/index.wxml';s=p.read_text(encoding='utf-8').replace('<strong>', '<view class="stat-value">').replace('</strong>', '</view>');p.write_text(s,encoding='utf-8')
p=root/'miniprogram/app.wxss';s=p.read_text(encoding='utf-8').replace('.stat strong', '.stat-value');p.write_text(s,encoding='utf-8')
print('小程序页面已生成；原模板保存在 xcx/template-backup')
p=root/'miniprogram/pages/login/index.wxml';s=p.read_text(encoding='utf-8').replace(' password data-field', ' password="{{true}}" data-field');p.write_text(s,encoding='utf-8')
p=root/'miniprogram/utils/geometry.js';s=p.read_text(encoding='utf-8').replace('markers:pos?[{id:row.id,', "markers:pos?[{iconPath:'/images/icons/home-active.png',width:28,height:28,id:row.id,");p.write_text(s,encoding='utf-8')
for name in ['index','land']:
    p=root/'miniprogram/pages'/name/'index.wxml';s=p.read_text(encoding='utf-8').replace('wx:else>', 'wx:else="">').replace('wx:else ', 'wx:else="" ').replace('&amp;&amp;', '&&').replace('rows.length&lt;total','total > rows.length');p.write_text(s,encoding='utf-8')
