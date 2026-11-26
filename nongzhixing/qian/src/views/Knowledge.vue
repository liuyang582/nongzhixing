<script setup lang="ts">
import {ref,reactive,computed,watch} from 'vue'
import {ElMessage,ElMessageBox,type FormInstance} from 'element-plus'
import {api,post,download,type User,type KnowledgeHit,type KnowledgeDoc} from '../api'
const props=defineProps<{user:User}>()
const domains=[['A','基础农艺'],['B','作物栽培'],['C','植物保护'],['D','设施农业与智慧农业'],['E','区域特色农业'],['F','政策法规与标准'],['G','质量安全与追溯']]
const tabs=ref('search'),loading=ref(false),error=ref(''),query=ref(''),crop=ref(''),region=ref(''),domain=ref(''),hits=ref<KnowledgeHit[]>([]),detail=ref<KnowledgeDoc|null>(null),detailBusy=ref(false)
const docs=ref<KnowledgeDoc[]>([]),total=ref(0),page=ref(1),manageQuery=ref(''),dialog=ref(false),saving=ref(false),formRef=ref<FormInstance>()
const form=reactive({title:'',domain_l1:'A',domain_l2:'',crop:'',region:'',stage:'',operation:'',keywords:'',queries:'',source:'',content:'',stability:'稳定',authority:'B',confidence:'高',risk_level:'低',version:'v1.0',status:'启用'})
const editing=ref(0)
const canManage=computed(()=>props.user.role==='admin')
function domainName(code:string){return domains.find(x=>x[0]===code)?.[1]||code||'未分类'}
function splitList(value:string){return [...new Set(value.split(/[,，、;；/\n]+/).map(x=>x.trim()).filter(Boolean))]}
function joinList(value:string[]|undefined){return (value||[]).join('、')}
async function search(){
  if(query.value.trim().length<2){ElMessage.warning('请至少输入两个字的问题或关键词');return}
  loading.value=true;error.value=''
  try{
    const result=await post<{items:KnowledgeHit[]}>('/knowledge/search',{q:query.value.trim(),crop:crop.value,region:region.value,domain_l1:domain.value,limit:10})
    hits.value=result.items
  }catch(e){error.value=(e as Error).message;hits.value=[]}finally{loading.value=false}
}
async function openDoc(id:number){
  detailBusy.value=true
  try{detail.value=await api<KnowledgeDoc>('/knowledge/docs/'+id)}catch(e){ElMessage.error((e as Error).message)}finally{detailBusy.value=false}
}
async function loadDocs(){
  if(!canManage.value)return
  loading.value=true;error.value=''
  try{
    const result=await api<{items:KnowledgeDoc[];total:number}>('/knowledge/docs?size=20&page='+page.value+'&q='+encodeURIComponent(manageQuery.value))
    docs.value=result.items;total.value=result.total
  }catch(e){error.value=(e as Error).message}finally{loading.value=false}
}
function resetForm(){
  Object.assign(form,{title:'',domain_l1:'A',domain_l2:'',crop:'',region:'',stage:'',operation:'',keywords:'',queries:'',source:'',content:'',stability:'稳定',authority:'B',confidence:'高',risk_level:'低',version:'v1.0',status:'启用'})
}
async function edit(doc?:KnowledgeDoc){
  editing.value=doc?.id||0
  if(doc){
    try{
      const full=await api<KnowledgeDoc>('/knowledge/docs/'+doc.id)
      Object.assign(form,{title:full.title,domain_l1:full.domain_l1||'A',domain_l2:full.domain_l2,crop:joinList(full.crop),region:joinList(full.region),stage:joinList(full.stage),operation:joinList(full.operation),keywords:joinList(full.keywords),queries:joinList(full.queries),source:full.source,content:full.content,stability:full.stability||'稳定',authority:full.authority||'B',confidence:full.confidence,risk_level:full.risk_level||'低',version:full.version||'v1.0',status:full.status||'启用'})
    }catch(e){ElMessage.error((e as Error).message);return}
  }else resetForm()
  dialog.value=true
}
async function save(){
  if(!await formRef.value?.validate().catch(()=>false))return
  saving.value=true;error.value=''
  const body={...form,crop:splitList(form.crop),region:splitList(form.region),stage:splitList(form.stage),operation:splitList(form.operation),keywords:splitList(form.keywords),queries:splitList(form.queries)}
  try{
    await api('/knowledge/docs'+(editing.value?'/'+editing.value:''),{method:editing.value?'PUT':'POST',body:JSON.stringify(body)})
    dialog.value=false;ElMessage.success(editing.value?'知识条目已更新':'知识条目已建档');await loadDocs()
  }catch(e){error.value=(e as Error).message;ElMessage.error(error.value)}finally{saving.value=false}
}
async function remove(doc:KnowledgeDoc){
  try{
    await ElMessageBox.confirm(`删除“${doc.title}”？删除后不再参与检索，操作保留审计记录。`,'删除知识条目',{type:'warning'})
    await api('/knowledge/docs/'+doc.id,{method:'DELETE'});ElMessage.success('已删除');await loadDocs()
  }catch(e){if(e instanceof Error)ElMessage.error(e.message)}
}
async function exportCsv(){
  try{await download('/knowledge/export/csv?q='+encodeURIComponent(manageQuery.value),'知识库档案.csv');ElMessage.success('已导出 CSV')}catch(e){ElMessage.error((e as Error).message)}
}
watch(()=>props.user.role,()=>{if(!canManage.value&&tabs.value==='manage')tabs.value='search'},{immediate:true})
watch(tabs,value=>{if(value==='manage')loadDocs()})
</script>
<template>
<div class="page-title"><div><h1>知识库与农技问答</h1><p>惠农服务 · 本地 BM25 检索 · 全局共享档案</p></div><el-tag type="success">{{canManage?'管理员可维护':'只读检索'}}</el-tag></div>
<el-alert title="知识库为全局共享的农技依据，所有账号可检索；新增、修改、删除仅系统管理员可操作。检索结果为字面匹配片段，不构成用药处方，时效性资料需核对最新公告。" type="info" :closable="false" style="margin-bottom:20px"/>
<el-alert v-if="error" :title="error" type="error" :closable="false" style="margin-bottom:16px"/>
<el-tabs v-model="tabs">
  <el-tab-pane label="检索" name="search">
    <section class="panel">
      <div class="toolbar">
        <el-input v-model="query" maxlength="200" clearable placeholder="例如：土壤板结怎么改良 / 番茄叶片发黄" style="width:340px" @keyup.enter="search"/>
        <el-input v-model="crop" maxlength="64" clearable placeholder="作物（可选）" style="width:160px"/>
        <el-input v-model="region" maxlength="64" clearable placeholder="地区（可选）" style="width:160px"/>
        <el-select v-model="domain" clearable placeholder="全部分类" style="width:200px"><el-option v-for="d in domains" :key="d[0]" :label="d[1]" :value="d[0]"/></el-select>
        <el-button type="primary" :loading="loading" @click="search">检索知识库</el-button>
      </div>
      <p class="muted">命中 {{hits.length}} 条。结果按 BM25 相关度排序，点击“查看原文”阅读完整条目。</p>
      <el-empty v-if="!hits.length&&!loading" description="输入问题或关键词，从 96 条农业知识档案中检索依据"/>
      <article v-for="hit in hits" :key="hit.id" class="knowledge-card">
        <div class="flex between">
          <h3><el-tag size="small">{{hit.doc_id}}</el-tag> {{hit.title}}</h3>
          <el-button link type="primary" @click="openDoc(hit.id)">查看原文</el-button>
        </div>
        <div class="tags"><el-tag size="small" type="info">{{domainName(hit.domain_l1)}} / {{hit.domain_l2}}</el-tag><el-tag v-for="item in hit.crop" :key="'c'+item" size="small">{{item}}</el-tag><el-tag v-for="item in hit.region" :key="'r'+item" size="small" type="info">{{item}}</el-tag><el-tag size="small" :type="hit.risk_level==='高'?'danger':hit.risk_level==='中'?'warning':'success'">风险 {{hit.risk_level}}</el-tag><el-tag size="small" type="warning">{{hit.stability}}</el-tag></div>
        <p class="knowledge-snippet">{{hit.snippet}}</p>
        <p class="muted">来源：{{hit.source||'未标注'}} · 相关度 {{hit.score}}</p>
      </article>
    </section>
  </el-tab-pane>
  <el-tab-pane v-if="canManage" label="管理" name="manage">
    <section class="panel">
      <div class="toolbar">
        <el-input v-model="manageQuery" maxlength="64" clearable placeholder="搜索标题 / 编号 / 关键词" style="width:260px" @keyup.enter="page=1;loadDocs()"/>
        <el-button @click="page=1;loadDocs()">查询</el-button>
        <el-button type="primary" @click="edit()">新增知识条目</el-button>
        <el-button @click="exportCsv">导出 CSV</el-button>
        <span class="muted">共 {{total}} 条</span>
      </div>
      <el-table :data="docs" v-loading="loading" empty-text="暂无知识条目">
        <el-table-column prop="doc_id" label="编号" width="110"/>
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip/>
        <el-table-column label="分类" width="190"><template #default="{row}">{{domainName(row.domain_l1)}} / {{row.domain_l2}}</template></el-table-column>
        <el-table-column label="作物" min-width="120"><template #default="{row}">{{row.crop.join('、')||'—'}}</template></el-table-column>
        <el-table-column label="来源" width="100"><template #default="{row}"><el-tag v-if="row.corpus" type="warning" size="small">语料导入</el-tag><span v-else>人工建档</span></template></el-table-column>
        <el-table-column prop="status" label="状态" width="80"/>
        <el-table-column label="操作" width="170" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openDoc(row.id)">详情</el-button><el-button link type="primary" @click="edit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev,pager,next,total" @current-change="loadDocs" style="margin-top:20px"/>
    </section>
  </el-tab-pane>
</el-tabs>
<el-drawer :model-value="!!detail" @close="detail=null" :title="detail?.title" size="620px">
  <template v-if="detail">
    <div class="tags"><el-tag>{{detail.doc_id}}</el-tag><el-tag type="info">{{domainName(detail.domain_l1)}} / {{detail.domain_l2}}</el-tag><el-tag v-for="item in detail.crop" :key="item">{{item}}</el-tag><el-tag :type="detail.risk_level==='高'?'danger':detail.risk_level==='中'?'warning':'success'">风险 {{detail.risk_level}}</el-tag><el-tag type="warning">{{detail.stability}}</el-tag></div>
    <p class="muted" style="margin-top:14px">来源：{{detail.source||'未标注'}} · 权威 {{detail.authority||'—'}} · 置信 {{detail.confidence||'—'}} · 版本 {{detail.version||'—'}}</p>
    <div class="knowledge-full">{{detail.content}}</div>
    <el-alert title="以上为知识库原文，仅作参考依据；具体用药需核对产品登记证、标签和当地禁限用规定。" type="warning" :closable="false" style="margin-top:16px"/>
  </template>
  <el-empty v-else-if="detailBusy" description="正在读取原文…"/>
</el-drawer>
<el-dialog v-model="dialog" :title="editing?'编辑知识条目':'新增知识条目'" width="760px" destroy-on-close :close-on-click-modal="!saving">
  <el-form ref="formRef" :model="form" label-position="top">
    <div class="field-grid">
      <el-form-item label="标题" prop="title" :rules="[{required:true,message:'请填写标题',trigger:'blur'}]"><el-input v-model="form.title" maxlength="200"/></el-form-item>
      <el-form-item label="一级分类"><el-select v-model="form.domain_l1" style="width:100%"><el-option v-for="d in domains" :key="d[0]" :label="d[0]+' '+d[1]" :value="d[0]"/></el-select></el-form-item>
      <el-form-item label="二级分类"><el-input v-model="form.domain_l2" maxlength="64"/></el-form-item>
      <el-form-item label="来源" prop="source" :rules="[{required:true,message:'请填写来源',trigger:'blur'}]"><el-input v-model="form.source" maxlength="500" placeholder="标准号、官方文件或资料名称"/></el-form-item>
      <el-form-item label="作物（顿号或逗号分隔）"><el-input v-model="form.crop" placeholder="例如：番茄、通用"/></el-form-item>
      <el-form-item label="地区（顿号或逗号分隔）"><el-input v-model="form.region" placeholder="例如：全国、长江中下游"/></el-form-item>
      <el-form-item label="生育期"><el-input v-model="form.stage" placeholder="例如：开花结果期"/></el-form-item>
      <el-form-item label="农事环节"><el-input v-model="form.operation" placeholder="例如：土壤诊断、施肥"/></el-form-item>
      <el-form-item label="检索关键词"><el-input v-model="form.keywords" placeholder="例如：土壤板结、通气性"/></el-form-item>
      <el-form-item label="常见问法"><el-input v-model="form.queries" placeholder="例如：土壤板结怎么办"/></el-form-item>
      <el-form-item label="时效"><el-select v-model="form.stability" style="width:100%"><el-option v-for="v in ['稳定','年度更新','时效性']" :key="v" :label="v" :value="v"/></el-select></el-form-item>
      <el-form-item label="风险等级"><el-select v-model="form.risk_level" style="width:100%"><el-option v-for="v in ['高','中','低']" :key="v" :label="v" :value="v"/></el-select></el-form-item>
      <el-form-item label="权威等级"><el-select v-model="form.authority" style="width:100%"><el-option v-for="v in ['A','B','C']" :key="v" :label="v" :value="v"/></el-select></el-form-item>
      <el-form-item label="置信度"><el-input v-model="form.confidence" maxlength="16" placeholder="例如：高"/></el-form-item>
      <el-form-item label="版本"><el-input v-model="form.version" maxlength="16"/></el-form-item>
      <el-form-item label="状态"><el-select v-model="form.status" style="width:100%"><el-option v-for="v in ['启用','停用']" :key="v" :label="v" :value="v"/></el-select></el-form-item>
    </div>
    <el-form-item label="正文" prop="content" :rules="[{required:true,message:'请填写正文',trigger:'blur'}]"><el-input v-model="form.content" type="textarea" :rows="12" maxlength="8000" show-word-limit placeholder="按原文录入，不编造药剂、剂量或未经核验的参数"/></el-form-item>
    <p class="muted">语料导入条目经人工修改后仍保留“语料导入”标记，重启服务不会被覆盖。</p>
  </el-form>
  <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
</el-dialog>
</template>
<style scoped>
.knowledge-card{padding:16px;margin-bottom:14px;background:#f7faf7;border:1px solid #e2ece2;border-radius:12px}
.knowledge-card h3{margin:0 0 10px;font-size:16px;line-height:1.5}
.knowledge-snippet{margin:10px 0;line-height:1.8;white-space:pre-wrap}
.knowledge-full{margin-top:18px;white-space:pre-wrap;line-height:1.9;max-height:60vh;overflow-y:auto;padding-right:8px}
.toolbar{flex-wrap:wrap}
</style>
