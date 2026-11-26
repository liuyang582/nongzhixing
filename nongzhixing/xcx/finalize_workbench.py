from pathlib import Path
r=Path(__file__).parent/'miniprogram'
p=r/'pages/ai/index.js';s=p.read_text(encoding='utf-8')
s=s.replace('this.setData({user});await this.history();', "this.setData({user,kinds:user.role==='farmer'?['农业问答','农事建议','种植方案','产销分析','照片诊断']:['农业问答','农事建议','种植方案','产销分析']});await this.history();")
s=s.replace("},input(e){this.setData", "},async refresh(){try{await this.history();this.setData({error:''})}catch(e){this.setData({error:e.message})}},input(e){this.setData",1)
p.write_text(s,encoding='utf-8')
p=r/'pages/ai/index.wxml';s=p.read_text(encoding='utf-8').replace('bindtap="history"','bindtap="refresh"');p.write_text(s,encoding='utf-8')
p=r/'pages/service/index.js';s=p.read_text(encoding='utf-8').replace('card(p,p.month)', 'card({...p,id:p.month},p.month)');p.write_text(s,encoding='utf-8')
p=r/'pages/manage/index.js';s=p.read_text(encoding='utf-8').replace("record(e){wx.navigateTo({url:'/pages/records/index?module='+e.currentTarget.dataset.id})}", "record(e){const id=e.currentTarget.dataset.id;wx.navigateTo({url:id==='lands'?'/pages/index/index':id==='harvest'?'/pages/service/index?kind=harvest':'/pages/records/index?module='+id})}");p.write_text(s,encoding='utf-8')
p=r/'pages/editor/index.js';s=p.read_text(encoding='utf-8').replace("if(v[f.key]==='')delete v[f.key]", "if(v[f.key]==='')v[f.key]=null");p.write_text(s,encoding='utf-8')
print('入口、AI 刷新与可选字段清空逻辑已校正')
