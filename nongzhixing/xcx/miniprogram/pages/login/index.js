const {request, session} = require('../../utils/api')
Page({data:{username:'',password:'',busy:false,error:''},
  async onLoad(){if(wx.getStorageSync('nx-token')){try{if(await session())wx.reLaunch({url:'/pages/home/index'})}catch(e){this.setData({error:e.message})}}},
  input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value})},
  async login(){if(this.data.busy)return;const username=this.data.username.trim(),password=this.data.password;if(!username||!password){this.setData({error:'请填写账号和密码'});return}this.setData({busy:true,error:''});try{const r=await request('/auth/login',{method:'POST',data:{username,password}});wx.setStorageSync('nx-token',r.token);getApp().globalData.user=r.user;this.setData({password:''});wx.reLaunch({url:'/pages/home/index'})}catch(e){this.setData({error:e.message})}finally{this.setData({busy:false})}}
})
