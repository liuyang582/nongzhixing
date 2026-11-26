<script setup lang="ts">
import {ref,onMounted} from 'vue'
import {ElMessage} from 'element-plus'
import {api,download} from '../api'
const rows=ref<{id:number;name:string;size:number;org:string;created_at:string}[]>([]),busy=ref(false)
async function load(){try{rows.value=await api('/files')}catch(e){ElMessage.error((e as Error).message)}}
onMounted(load)
async function upload(event:Event){const f=(event.target as HTMLInputElement).files?.[0];if(!f)return;const data=new FormData();data.append('file',f);busy.value=true;try{await api('/files',{method:'POST',body:data});ElMessage.success('附件已保存');load()}catch(e){ElMessage.error((e as Error).message)}finally{busy.value=false}}
async function getFile(id:number,name:string){try{await download('/files/'+id,name)}catch(e){ElMessage.error((e as Error).message)}}
</script>
<template><div class="page-title"><div><h1>附件管理</h1><p>保存土壤报告、合同、票据、图片与灾情资料，按主体与辖区隔离</p></div></div><section class="panel" v-loading="busy"><div class="toolbar"><label>上传附件 <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.xlsx,.docx,.zip" @change="upload"/></label><span class="muted">单文件最大 10 MB</span></div><el-table :data="rows"><el-table-column prop="name" label="文件" min-width="220"/><el-table-column label="大小"><template #default="{row}">{{(row.size/1024).toFixed(1)}} KB</template></el-table-column><el-table-column prop="org" label="数据范围"/><el-table-column prop="created_at" label="上传时间" min-width="170"/><el-table-column label="操作"><template #default="{row}"><el-button link type="primary" @click="getFile(row.id,row.name)">下载</el-button></template></el-table-column></el-table></section></template>
