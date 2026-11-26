<script setup lang="ts">
import {ref,onMounted,computed} from 'vue'
import {ElMessage} from 'element-plus'
import {api} from '../api'
const emit=defineEmits<{ask:[crop:string]}>(),groups=ref<{group:string;names:string[]}[]>([]),selected=ref('蔬菜作物'),q=ref(''),crop=ref(''),drawer=ref(false)
onMounted(async()=>{try{groups.value=await api('/crops')}catch(e){ElMessage.error((e as Error).message)}})
const names=computed(()=>groups.value.find(g=>g.group===selected.value)?.names.filter(n=>n.includes(q.value))||[])
function choose(name:string){crop.value=name;drawer.value=true}
const stages=computed(()=>selected.value==='食用菌'?['菌种与基质','接种与发菌','出菇管理','采收','批次复盘']:selected.value==='水果作物'?['苗木与建园','营养生长','开花与结果','果实生长','采收管理']:['播种与苗期','田间建立','营养生长','收获器官生长','成熟采收'])
</script>
<template><div class="page-title"><div><h1>作物资料库与种植方案</h1><p>8 大类、64 种作物目录，种植资料按品种、地区与生产方式审核</p></div></div><section class="panel"><div class="toolbar"><el-select v-model="selected" style="width:180px"><el-option v-for="g in groups" :key="g.group" :value="g.group" :label="g.group"/></el-select><el-input v-model="q" placeholder="搜索作物" clearable style="width:240px"/></div><div class="crop-grid"><button v-for="name in names" :key="name" class="crop-item" @click="choose(name)"><strong>{{name}}</strong><div class="muted" style="margin-top:8px">查看阶段与方案入口 →</div></button></div></section><el-alert title="目录覆盖不等于全部农技资料已审核。具体温湿度、施肥和用药参数需核对适用资料。" type="info" :closable="false"/>
<el-drawer v-model="drawer" :title="crop+' · 生长与管理档案'" size="540px"><el-tag>{{selected}}</el-tag><h3 style="margin-top:25px">阶段管理模板</h3><el-timeline><el-timeline-item v-for="s in stages" :key="s" :timestamp="'需结合地区与品种确认'" color="#246b47">{{s}}</el-timeline-item></el-timeline><div class="danger-note">当前为阶段字段模板，不是具体作物的栽培处方；不提供未经验证的固定周期、剂量或阈值。</div><h3 style="margin-top:25px">方案所需条件</h3><p class="muted">品种、地区、土壤检测、生长阶段、种植方式、近期天气与农事记录。</p><el-button type="primary" @click="emit('ask',crop);drawer=false">用 AI 辅助整理种植方案</el-button></el-drawer></template>
