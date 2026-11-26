<script setup lang="ts">
import {ref,onMounted} from 'vue'
import {useRoute} from 'vue-router'
import {api} from '../api'
const route=useRoute(),error=ref(''),data=ref<{crop:string;batch:string;grade:string;quantity:number;harvest_date:string;plot:string;producer:string;variety:string;sow_date:string;stage:string;demo:boolean;notice:string;tasks:{type:string;date:string;status:string}[]}>()
function printPage(){window.print()}
onMounted(async()=>{try{data.value=await api('/public/trace/'+encodeURIComponent(route.path.split('/')[2]||''))}catch(e){error.value=(e as Error).message}})
</script>
<template><main style="max-width:1050px;margin:40px auto;padding:24px"><h1>农知行 · 农产品生产溯源</h1><el-alert v-if="error" :title="error" type="error" :closable="false"/><section v-else-if="data" class="panel"><el-tag v-if="data.demo" type="warning">演示生产记录</el-tag><h2>{{data.crop}} · {{data.batch}}</h2><el-descriptions :column="2" border><el-descriptions-item label="经营主体">{{data.producer}}</el-descriptions-item><el-descriptions-item label="生产地块">{{data.plot}}</el-descriptions-item><el-descriptions-item label="品种">{{data.variety||'未登记'}}</el-descriptions-item><el-descriptions-item label="等级">{{data.grade}}</el-descriptions-item><el-descriptions-item label="播种日期">{{data.sow_date}}</el-descriptions-item><el-descriptions-item label="采收日期">{{data.harvest_date}}</el-descriptions-item><el-descriptions-item label="采收重量">{{data.quantity}} kg</el-descriptions-item><el-descriptions-item label="生长阶段">{{data.stage}}</el-descriptions-item></el-descriptions><h3>农事摘要</h3><el-table :data="data.tasks"><el-table-column prop="type" label="作业类型"/><el-table-column prop="date" label="日期"/><el-table-column prop="status" label="执行状态"/></el-table><el-alert :title="data.notice" :closable="false"/><el-button style="margin-top:20px" @click="printPage">打印生产摘要</el-button></section><el-empty v-else description="正在读取溯源信息"/></main></template>

