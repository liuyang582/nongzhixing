<script setup lang="ts">
import {ref,onMounted,watch} from 'vue'
import {useRouter} from 'vue-router'
const router=useRouter()
import {ElMessage} from 'element-plus'
import {api,post,type AIJob,type User} from '../api'
const props=defineProps<{user:User;initialCrop?:string}>()
const question=ref(''),kind=ref('chat'),crop=ref('番茄'),image=ref(''),loading=ref(false),jobs=ref<AIJob[]>([]),selected=ref<AIJob>(),error=ref(''),confirming=ref(false)
const kinds=[['chat','农业问答'],['farm','农事建议'],['planting','种植方案辅助'],['market','产销分析']]
watch(()=>props.initialCrop,name=>{if(name){crop.value=name;kind.value='planting';question.value=`请为${name}整理种植方案所需条件、阶段管理重点和病虫害预防检查。资料不足时明确列出需要补充的地区、品种和土壤信息，不编造参数。`}},{immediate:true})
async function load(){try{jobs.value=await api<AIJob[]>('/ai/jobs')}catch(e){ElMessage.error((e as Error).message)}}
onMounted(load)
function chooseFile(event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024){ElMessage.error('请选择不超过 10 MB 的 JPG、PNG 或 WebP 图片');return}const reader=new FileReader();reader.onload=()=>{image.value=String(reader.result);kind.value='diagnosis'};reader.readAsDataURL(file)}
async function analyze(){if(question.value.trim().length<2){ElMessage.warning('请描述至少两个字的问题');return}if(kind.value==='diagnosis'&&!image.value){ElMessage.warning('请先上传作物照片');return}loading.value=true;error.value='';selected.value=undefined;try{selected.value=await post<AIJob>('/ai/analyze',{question:question.value,kind:kind.value,crop:crop.value,image:image.value});await load()}catch(e){error.value=(e as Error).message}finally{loading.value=false}}
async function confirm(){if(!selected.value)return;confirming.value=true;try{const result=await post<{task_id:number}>(`/ai/jobs/${selected.value.id}/confirm`,{});ElMessage.success(`已创建人工复核任务 #${result.task_id}`);await load();selected.value=jobs.value.find(j=>j.id===selected.value?.id)}catch(e){ElMessage.error((e as Error).message)}finally{confirming.value=false}}
</script>
<template><div class="page-title"><div><h1>农业智能助手</h1><p>千问多模态＋LangChain＋LangGraph · 内部知识库检索增强 · 分析记录保存至数据库</p></div><div class="flex"><el-button @click="router.push('/workspace/knowledge')">浏览知识库</el-button><el-tag type="success">qwen3.5-omni-plus</el-tag></div></div>
<div class="columns ai-columns"><section class="panel"><h2>提交问题与资料</h2><el-form label-position="top"><el-form-item label="分析类型"><el-select v-model="kind"><el-option v-for="k in kinds" :key="k[0]" :label="k[1]" :value="k[0]"/></el-select></el-form-item><el-form-item label="作物"><el-input v-model="crop" maxlength="64" placeholder="例如 番茄 / 水稻"/></el-form-item><el-form-item label="问题描述（必填）"><el-input v-model="question" type="textarea" :rows="5" maxlength="4000" show-word-limit placeholder="说明品种、地区、生长阶段、发生时间、近期农事和异常现象"/></el-form-item><el-button v-if="user.role==='farmer'" @click="router.push('/workspace/planting-flow')">进入地块照片分析与任务流程</el-button><el-alert v-if="error" :title="error" type="error" :closable="false" style="margin:16px 0"/><el-button type="primary" :loading="loading" @click="analyze" style="margin-top:20px">{{loading?'正在分析，请稍候':'开始 AI 分析'}}</el-button></el-form><p class="muted">上传照片将发送给你配置的模型服务。结果为初筛，不自动施药，不保证增产或价格。</p></section>
<section class="panel"><h2>分析结果与流程</h2><template v-if="selected"><el-tag :type="selected.status==='待确认'?'warning':'success'">{{selected.status}}</el-tag><el-steps :active="selected.steps.length" finish-status="success" direction="vertical" style="margin:20px 0"><el-step v-for="s in selected.steps" :key="s" :title="s"/></el-steps><div class="prewrap ai-answer" role="region" aria-label="AI 分析回答" tabindex="0">{{selected.result.answer}}</div><div v-if="selected.result.citations?.length" class="knowledge-refs"><h3>参考知识</h3><article v-for="(hit,index) in selected.result.citations" :key="hit.id" class="knowledge-ref"><strong>[{{index+1}}] {{hit.title}}</strong><div class="tags"><el-tag size="small">{{hit.doc_id}}</el-tag><el-tag size="small" type="info">{{hit.domain_l2}}</el-tag><el-tag size="small" type="warning">{{hit.stability}}</el-tag><el-tag size="small" :type="hit.risk_level==='高'?'danger':hit.risk_level==='中'?'warning':'success'">风险 {{hit.risk_level}}</el-tag></div><p>{{hit.snippet}}</p><p class="muted">来源：{{hit.source||'未标注'}}</p></article></div><el-alert v-else title="知识库未检索到直接依据，回答中的结论需补充资料或农技复核。" type="warning" :closable="false" style="margin-top:16px"/><div class="danger-note" style="margin-top:20px">用药必须核验具体产品登记与标签；建议不会直接控制设备或扣减库存。</div><el-button v-if="selected.status==='待确认'&&user.role==='farmer'" type="primary" :loading="confirming" @click="confirm" style="margin-top:16px">确认并创建人工复核任务</el-button></template><el-empty v-else :description="loading?'正在读取授权数据并调用千问…':'提交问题后显示真实模型回答'"/></section></div>
<section class="panel"><h2>历史分析记录</h2><el-table :data="jobs" @row-click="selected=$event" style="cursor:pointer"><el-table-column prop="question" label="问题" min-width="260" show-overflow-tooltip/><el-table-column prop="kind" label="类型"/><el-table-column prop="status" label="状态"/><el-table-column label="时间"><template #default="{row}">{{row.created_at.slice(0,19).replace('T',' ')}}</template></el-table-column></el-table></section>
</template>

<style scoped>
.ai-columns{align-items:start}
.ai-answer{max-height:clamp(280px,55vh,640px);overflow-y:auto;padding-right:8px}
.ai-answer:focus-visible{outline:2px solid var(--el-color-primary);outline-offset:4px}
.knowledge-refs{margin-top:20px;padding-top:16px;border-top:1px solid var(--el-border-color-lighter)}
.knowledge-refs h3{margin:0 0 12px}
.knowledge-ref{padding:12px;margin-bottom:10px;background:#f7faf7;border:1px solid #e2ece2;border-radius:10px}
.knowledge-ref p{margin:8px 0 0;line-height:1.7}
</style>
