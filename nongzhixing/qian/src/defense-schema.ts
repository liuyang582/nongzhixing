import type {FormRules} from 'element-plus'
export const required=(label:string)=>[{required:true,message:`请填写${label}`,trigger:'change'}]
export const harvestRules:FormRules={growth_id:required('生长批次'),batch:required('采收批号'),date:required('采收日期'),quantity:required('重量')}
export const passwordRules:FormRules={old_password:required('原密码'),new_password:[...required('新密码'),{min:8,max:128,message:'密码需为 8–128 个字符',trigger:'blur'}]}
