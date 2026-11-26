const {session,logout}=require('../../utils/api')
Page({data:{user:null,error:''},async onShow(){try{this.setData({user:await session(),error:''})}catch(e){this.setData({error:e.message})}},go(e){wx.navigateTo({url:e.currentTarget.dataset.url})},logout(){logout();wx.reLaunch({url:'/pages/login/index'})}})
