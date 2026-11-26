<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref,watch} from 'vue'
import * as echarts from 'echarts'
const props=defineProps<{option:echarts.EChartsOption}>()
const el=ref<HTMLElement>();let chart:echarts.ECharts|undefined,observer:ResizeObserver|undefined
onMounted(()=>{if(el.value){chart=echarts.init(el.value);chart.setOption(props.option);observer=new ResizeObserver(()=>chart?.resize());observer.observe(el.value)}})
watch(()=>props.option,v=>chart?.setOption(v,true),{deep:true})
onBeforeUnmount(()=>{observer?.disconnect();chart?.dispose()})
</script>
<template><div ref="el" class="chart" role="img" aria-label="农业数据统计图"></div></template>
