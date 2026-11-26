import type {FormRules} from 'element-plus'
const required=(label:string)=>({required:true,message:`请填写${label}`,trigger:'blur'})
export const landRules:FormRules={title:[required('地块名称')],crop:[required('作物')],latitude:[required('纬度')],longitude:[required('经度')]}
export const growthRules:FormRules={title:[required('批次名称')],crop:[required('作物')],sow_date:[required('播种或定植日期')],stage:[required('实际生长阶段')]}
export const environmentRules:FormRules={temperature:[required('空气温度')],humidity:[required('空气湿度')],soil:[required('土壤湿度')],source:[required('数据来源')]}
export const analysisRules:FormRules={question:[required('异常描述'),{min:2,message:'描述至少两个字',trigger:'blur'}],growth_id:[required('生长记录')],image:[required('田间照片')]}
export const confirmRules:FormRules={title:[required('任务名称')],assignee:[required('执行人')],date:[required('计划日期')],note:[required('人工确认意见')]}
export const feedbackRules:FormRules={note:[required('实际执行结果')]}
