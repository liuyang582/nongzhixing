<script setup lang="ts">
import {ref,onMounted,computed} from 'vue'
import {ElMessage} from 'element-plus'
import Chart from '../components/Chart.vue'
import {api,type User,type RecordRow,type ModuleSpec} from '../api'
const props=defineProps<{user:User;modules:ModuleSpec[]}>(),emit=defineEmits<{navigate:[id:string]}>()
type Dashboard={counts:Record<string,number>;records:number;demo_records:number;environment:RecordRow[];recent:RecordRow[];available_stock:number;pending_orders:number;sales:number;users:number|null}
const data=ref<Dashboard>(),loading=ref(false)
async function load(){loading.value=true;try{data.value=await api<Dashboard>('/dashboard')}catch(e){ElMessage.error((e as Error).message)}finally{loading.value=false}}
onMounted(load)
const metrics=computed(()=>props.user.role==='admin'?[['用户账号',data.value?.users||0,'包含三类业务角色'],['管理台账',data.value?.records||0,'资料 / 设备 / 系统配置'],['待审核产品',data.value?.counts.pesticides||0,'需核对实际登记标签'],['审核资料',data.value?.counts.dictionary||0,'按来源与版本管理']]:[['业务记录',data.value?.records||0,`其中 ${data.value?.demo_records||0} 条演示样本`],['地块档案',data.value?.counts.lands||0,'登记与实测面积分开'],['可用库存',`${data.value?.available_stock||0} kg`,'已扣除订单预占'],['待出库订单',data.value?.pending_orders||0,'需人工确认出库']])
const environmentOption=computed(()=>({color:['#246b47','#d9a746','#658dab'],tooltip:{trigger:'axis'},legend:{bottom:0},grid:{left:45,right:45,top:20,bottom:60},xAxis:{type:'category',data:data.value?.environment.map(r=>r.created_at.slice(11,16))||[]},yAxis:[{type:'value',name:'℃'},{type:'value',name:'%'}],series:[{name:'温度',type:'line',smooth:true,data:data.value?.environment.map(r=>r.data.temperature)||[]},{name:'空气湿度',type:'line',smooth:true,yAxisIndex:1,data:data.value?.environment.map(r=>r.data.humidity)||[]},{name:'土壤湿度',type:'line',smooth:true,yAxisIndex:1,data:data.value?.environment.map(r=>r.data.soil)||[]}]}))
const countOption=computed(()=>({color:['#246b47'],tooltip:{trigger:'axis'},grid:{left:100,right:30,top:15,bottom:30},xAxis:{type:'value',minInterval:1},yAxis:{type:'category',data:props.modules.slice(0,7).map(m=>m.title)},series:[{name:'记录数',type:'bar',barWidth:14,itemStyle:{borderRadius:[0,5,5,0]},data:props.modules.slice(0,7).map(m=>data.value?.counts[m.id]||0)}]}))
const title=computed(()=>({farmer:'农业生产经营看板',regulator:'辖区农情工作台',admin:'系统管理工作台'}[props.user.role]))
</script>
<template><div class="page-title"><div><h1>{{title}}</h1><p>{{user.org}} · 数据由业务台账汇总，演示样本单独标注</p></div><el-button @click="load" :loading="loading">刷新数据</el-button></div>
<div class="metrics"><div class="metric" v-for="m in metrics" :key="String(m[0])"><div class="metric-label">{{m[0]}}</div><div class="metric-value">{{m[1]}}</div><div class="metric-note">{{m[2]}}</div></div></div>
<div class="columns"><section class="panel"><div class="flex between"><h2>{{user.role==='farmer'?'环境监测趋势':'业务记录分布'}}</h2><el-tag type="warning" v-if="user.role==='farmer'">含模拟数据</el-tag></div><Chart :option="(user.role==='farmer'?environmentOption:countOption) as never"/></section><section class="panel"><h2>工作入口</h2><div class="tags"><el-button v-for="m in modules.slice(0,8)" :key="m.id" @click="emit('navigate',m.id)">{{m.title}}</el-button></div><div class="timeline-note" style="margin-top:24px"><strong>生产记录与智能辅助分开</strong><p class="muted">AI 建议经过人工确认再进入农事任务；登记核验、库存数量及权限由后端处理。</p></div><el-button type="primary" @click="emit('navigate','ai')">进入农业智能助手</el-button></section></div>
<section class="panel"><h2>近期更新</h2><el-table :data="data?.recent||[]" empty-text="暂无业务记录"><el-table-column prop="title" label="记录" min-width="220"/><el-table-column prop="status" label="状态" width="110"/><el-table-column label="来源" width="130"><template #default="{row}"><el-tag :type="row.demo?'warning':'success'">{{row.demo?'演示样本':'用户录入'}}</el-tag></template></el-table-column><el-table-column label="更新时间" min-width="170"><template #default="{row}">{{row.updated_at.replace('T',' ').slice(0,19)}}</template></el-table-column></el-table></section>
</template>
