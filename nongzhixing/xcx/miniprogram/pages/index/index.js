const {request,session,logout}=require('../../utils/api')
Page({data:{user:null,rows:[],total:0,demoCount:0,q:'',page:1,busy:false,error:'',allowed:true},
  async onShow(){try{const user=await session();if(!user)return;this.setData({user});const modules=await request('/modules');const allowed=user.role==='regulator'||modules.some(m=>m.id==='lands');this.setData({allowed});if(allowed)await this.load(true)}catch(e){this.setData({error:e.message})}},
  searchInput(e){this.setData({q:e.detail.value})}, search(){this.load(true)},
  async load(reset){if(this.data.busy||!this.data.allowed)return;const page=reset?1:this.data.page+1;this.setData({busy:true,error:''});try{const r=await request('/records/lands?size=20&page='+page+'&q='+encodeURIComponent(this.data.q));const rows=reset?r.items:this.data.rows.concat(r.items);this.setData({rows,total:r.total,page,demoCount:rows.filter(x=>x.demo).length})}catch(e){this.setData({error:e.message})}finally{this.setData({busy:false});wx.stopPullDownRefresh()}},
  onPullDownRefresh(){this.load(true)},more(){this.load(false)},
  open(e){wx.navigateTo({url:'/pages/land/index?id='+e.currentTarget.dataset.id})},
  logout(){logout();wx.reLaunch({url:'/pages/login/index'})}
})
