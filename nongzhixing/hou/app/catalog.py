# =============================================================================
# catalog.py —— 业务模块与字段目录（元数据层）
# 职责：集中声明每个业务模块的标题、分组、字段、可访问角色和业务说明。
# 作用：前端的表格/表单、后端的数据校验、CSV/Excel/PDF 导出都读取这份目录，
#       新增一个业务流程通常只需要在本文件登记模块，而不需要新建数据表。
# =============================================================================

# 模块文件说明：专业农业参数由人工审核资料提供，本文件只描述字段结构，不内置药剂处方。
"""业务模块、字段与权限目录。专业农业参数由审核资料提供。"""

# 字段工厂函数：统一生成前端可渲染、后端可校验的字段描述字典
def field(key, label, kind="text", required=False, options=None):
    # key=存储键名；label=中文显示名；kind=控件类型；required=是否必填；options=下拉选项
    return {"key": key, "label": label, "type": kind, "required": required, "options": options or []}

# 通用字段组：所有未单独声明字段的模块默认使用这 4 个字段
COMMON = [field("crop", "作物"), field("plot", "地块 / 温室"), field("date", "记录日期", "date"), field("note", "说明 / 依据", "textarea")]
# 模块注册表：键为模块 ID，值为模块描述字典；features.py 还会追加 expenses 模块
MODULES = {}

# 模块注册函数：把模块信息写入 MODULES，并统一补全默认字段与默认角色
def module(key, title, group, fields=None, roles=None, note=""):
    # 写入模块元数据：id 用于接口路径，title 用于菜单和导出，group 用于侧栏分组
    MODULES[key] = {"id": key, "title": title, "group": group,
                    # 未传 fields 时使用通用字段；未传 roles 时默认仅经营主体可访问
                    "fields": fields or COMMON, "roles": roles or ["farmer"], "note": note}

# 地块资源模块：GIS 边界、登记面积、土壤与承包信息；状态和经纬度等字段用于地图定位
module("lands", "GIS 地块资源", "资源与种植", [field("area", "登记面积（亩）", "number"), field("crop", "当前作物"), field("ph", "土壤 pH", "number"), field("organic", "有机质（g/kg）", "number"), field("soil_grade", "地力等级"), field("irrigation", "灌溉 / 排水类型"), field("elevation", "海拔（m）", "number"), field("previous_crop", "前茬作物"), field("contract", "承包 / 流转信息", "textarea"), field("note", "档案说明", "textarea")], note="地图绘制和 GeoJSON/SHP 导入可用；面积测算与合同登记面积分开。未接入卫星自动识别和 NDVI。")
# 播种方案模块：记录品种、用种量、计划日期和来源，不自动生成未经核验的种植处方
module("sowing", "播种方案与台账", "资源与种植", [field("crop", "作物", required=True), field("plot", "地块", required=True), field("variety", "品种"), field("region", "地区"), field("date", "计划播种日期", "date"), field("seed_batch", "种子批次"), field("amount", "用种量（kg）", "number"), field("plan", "方案与整地说明", "textarea"), field("source", "农技资料来源")], note="播种参数必须有适用农技资料；不自动生成未经验证的株行距与底肥处方。")
# 生长周期模块：作物、品种、播种日期、生长阶段、预计采收日期和株高
module("growth", "生长周期", "资源与种植", [field("crop", "作物", required=True), field("plot", "地块 / 温室", required=True), field("variety", "品种"), field("sow_date", "播种 / 定植日期", "date", True), field("stage", "实际生长阶段", "select", True, ["育苗期", "营养生长期", "开花结果期", "收获期", "其他"]), field("harvest_date", "预计采收日期", "date"), field("height", "株高（cm）", "number"), field("note", "观察记录", "textarea")])
# 农事任务模块：任务类型、执行人、计划日期、实际投入与执行结果
module("tasks", "农事任务", "田间管护", [field("crop", "作物"), field("plot", "地块 / 温室"), field("type", "任务类型", "select", True, ["巡检", "灌溉检查", "施肥", "植保", "除草", "采收", "其他"]), field("assignee", "执行人"), field("date", "计划日期", "date"), field("amount", "实际投入量", "number"), field("unit", "投入单位"), field("note", "执行结果 / 依据", "textarea")])
# 环境监测模块：温度、湿度、土壤湿度与数据来源；新增记录会触发阈值预警引擎
module("environment", "环境监测", "田间管护", [field("plot", "地块 / 温室", required=True), field("temperature", "空气温度（℃）", "number", True), field("humidity", "空气湿度（%）", "number", True), field("soil", "土壤湿度（%）", "number", True), field("source", "数据来源", "select", True, ["模拟器", "传感器", "人工记录"]), field("note", "设备说明", "textarea")])
# 告警中心模块：记录环境异常、设备离线、库存提醒等事件及人工处理结果
module("alerts", "告警中心", "田间管护", [field("plot", "对象"), field("type", "告警类型", "select", True, ["环境异常", "设备离线", "库存提醒", "人工上报"]), field("level", "等级", "select", True, ["提示", "关注", "紧急"]), field("note", "事件及处理记录", "textarea", True)])
# 温室与设备模块：登记温室面积、种植作物、设备编号和采集周期
module("houses", "温室与设备", "田间管护", [field("area", "面积（m²）", "number"), field("crop", "作物"), field("device", "设备编号"), field("frequency", "采集周期（分钟）", "number"), field("note", "区域与设备说明", "textarea")])
# 农资供应链模块：种子、肥料、农药的批次、供应商、数量、金额和登记凭证
module("inputs", "农资供应链", "投入与经营", [field("type", "农资类别", "select", True, ["种子", "肥料", "农药", "其他"]), field("batch", "批次", required=True), field("supplier", "供应商"), field("quantity", "数量", "number", True), field("unit", "单位", required=True), field("cost", "采购金额（元）", "number"), field("registration", "登记 / 来源凭证"), field("note", "合同与验收说明", "textarea")])
# 采收记录模块：记录实收量、等级、含水率和杂质率；入库动作在库存/溯源接口中完成
module("harvest", "采收记录", "投入与经营", [field("crop", "作物", required=True), field("plot", "地块", required=True), field("batch", "种植批次", required=True), field("date", "采收日期", "date", True), field("quantity", "实收量（kg）", "number", True), field("grade", "等级", "select", True, ["A", "B", "未分级"]), field("moisture", "含水率（%）", "number"), field("impurity", "杂质率（%）", "number"), field("note", "采收说明", "textarea")], note="库存入库通过库存模块完成，不会因修改采收记录重复入库。")
# 农机作业模块：整地、播种、收割等作业的服务方、日期和费用
module("machines", "农机作业", "投入与经营", [field("plot", "地块"), field("type", "作业类别", "select", True, ["整地", "播种", "收割", "脱粒", "烘干"]), field("provider", "服务方"), field("date", "作业日期", "date"), field("cost", "费用（元）", "number"), field("note", "进度与评价", "textarea")])
# 仓储与质量模块：关联库存批次、仓库、温湿度、合格证与质量控制依据
module("storage", "仓储与质量", "投入与经营", [field("batch", "关联库存批次"), field("warehouse", "仓库"), field("temperature", "仓储温度（℃）", "number"), field("humidity", "仓储湿度（%）", "number"), field("certificate", "合格证编号"), field("basis", "质量控制 / 检测依据", "textarea"), field("note", "开具主体确认记录", "textarea")], note="台账不等于检测结果；合格证必须由开具主体依据实际质量控制资料确认。")
# 客户与回款模块：记录客户联系信息、关联订单、回款金额和日期
module("customers", "客户与回款", "投入与经营", [field("contact", "联系人"), field("phone", "联系电话"), field("region", "地区"), field("order", "关联订单"), field("amount", "回款金额（元）", "number"), field("date", "日期", "date"), field("note", "询价 / 回款说明", "textarea")])
# 市场行情模块：品类、市场、等级、价格、报价口径和原始来源
module("market", "市场行情", "惠农服务", [field("crop", "品类", required=True), field("market", "市场 / 来源", required=True), field("region", "地区"), field("grade", "等级 / 规格"), field("price", "价格（元/kg）", "number", True), field("type", "报价口径", "select", True, ["收购价", "批发价", "零售价"]), field("date", "报价日期", "date", True), field("source", "原始来源链接"), field("note", "行情说明", "textarea")], note="手工导入行情有来源标注，不提供未经验证的未来价格预测。")
# 惠农政策模块：适用地区、发布单位、申报截止日期、官方原文和适用条件
module("policies", "惠农政策", "惠农服务", [field("region", "适用地区", required=True), field("issuer", "发布单位"), field("deadline", "申报截止日期", "date"), field("source", "官方原文链接", required=True), field("conditions", "适用条件", "textarea", True), field("note", "材料清单", "textarea")], note="政策匹配仅为辅助，需核对有效原文，不代替审批。")
# 农技问诊模块：经营主体提问题，专家或农技人员填写人工回复；监管员也可查看
module("services", "农技问诊", "惠农服务", [field("crop", "作物", required=True), field("plot", "地块"), field("expert", "专家 / 分派人"), field("question", "问题描述", "textarea", True), field("reply", "人工回复", "textarea"), field("date", "预约日期", "date")], roles=["farmer", "regulator"])
# 内部知识库模块：仅用于生成“惠农服务”侧栏与小程序入口；数据走 /api/knowledge 专用接口
module("knowledge", "知识库与农技问答", "惠农服务", [field("domain_l2", "分类"), field("crop", "作物"), field("region", "地区"), field("keywords", "关键词"), field("source", "来源"), field("stability", "时效"), field("risk_level", "风险")], roles=["farmer", "regulator", "admin"], note="全局共享知识档案；所有账号可检索，仅系统管理员可新增、修改或删除。检索结果不构成用药处方。")
# 灾情与保险模块：受灾地块、灾种、自报面积、发生日期和保单编号
module("disasters", "灾情与保险", "惠农服务", [field("plot", "受灾地块", required=True), field("type", "灾种", "select", True, ["干旱", "洪涝", "冰雹", "霜冻", "高温", "大风", "其他"]), field("area", "自报受灾面积（亩）", "number"), field("date", "发生日期", "date"), field("policy", "保单编号"), field("note", "灾情与处置说明", "textarea")], roles=["farmer", "regulator"], note="自报、核查、保险定损分开，不自动承诺赔付。")
# 绿色农业模块：农药包装、农膜、秸秆等农业废弃物的数量和交接去向
module("eco", "绿色农业", "惠农服务", [field("type", "资源类别", "select", True, ["农药包装", "农膜", "秸秆"]), field("quantity", "数量", "number"), field("unit", "单位"), field("destination", "交接去向"), field("date", "日期", "date"), field("note", "处置与交接记录", "textarea")], note="未提供经认证的碳汇核算。")
# 经营主体与资质模块：合作社、家庭农场的登记证号与有效期，仅监管员可访问
module("subjects", "经营主体与资质", "辖区监管", [field("type", "主体类型", "select", True, ["合作社", "家庭农场", "种植大户"]), field("region", "行政区域"), field("certificate", "认证 / 登记证号"), field("expiry", "有效期", "date"), field("note", "核查记录", "textarea")], roles=["regulator"])
# 耕地与面积核验模块：登记面积与测算面积差异、抛荒线索等，仅监管员可访问
module("verification", "耕地与面积核验", "辖区监管", [field("plot", "地块", required=True), field("area", "登记面积（亩）", "number"), field("measured", "测算面积（亩）", "number"), field("type", "线索", "select", True, ["面积差异", "抛荒疑似", "非粮化疑似", "资料缺失"]), field("note", "人工核验记录", "textarea")], roles=["regulator"], note="仅辅助核验与线索登记，不审批补贴、不自动作行政认定。")
# 辖区病虫害模块：记录疑似防治对象、确认方式与统防统治情况，仅监管员可访问
module("regional-pests", "辖区病虫害", "辖区监管", [field("crop", "作物"), field("plot", "地块"), field("disease", "疑似防治对象"), field("confirmed", "确认方式", "select", True, ["AI 疑似", "人工巡查", "专家确认"]), field("level", "等级"), field("note", "统防统治记录", "textarea")], roles=["regulator"])
# 农药资料审核模块：完整登记证信息与官方标签来源，仅管理员可录入和维护
module("pesticides", "农药资料审核", "系统管理", [field("registration", "登记证号", required=True), field("ingredient", "有效成分及含量", required=True), field("formulation", "剂型", required=True), field("holder", "登记持有人", required=True), field("crop", "标签适用作物", required=True), field("target", "防治对象", required=True), field("dose", "标签剂量及单位", required=True), field("method", "方法 / 时期", required=True), field("interval", "安全间隔期说明", required=True), field("max_uses", "最多使用次数", required=True), field("risk", "防护 / 环境风险", "textarea", True), field("first_aid", "急救说明", "textarea", True), field("storage", "储运 / 包装处置", "textarea", True), field("restrictions", "禁限用 / 混配 / 药害", "textarea", True), field("source", "官方标签来源", required=True), field("expiry", "登记有效期", "date", True)], roles=["admin"], note="人工审核后才进入候选资料；仅保存完整资料不代表登记信息已核验。")
# 基础资料与标准模块：种植规程、病虫害、行政区划等公共资料，仅管理员可维护
module("dictionary", "基础资料与标准", "系统管理", [field("type", "资料类别", "select", True, ["种植规程", "病虫害", "肥料", "行政区划", "单位", "灾害", "消息模板"]), field("crop", "作物"), field("region", "适用地区"), field("source", "资料来源", required=True), field("content", "正文", "textarea", True), field("expiry", "有效期", "date")], roles=["admin"])
# 设备接入档案模块：预留传感器、虫情灯、摄像头等硬件接入信息，仅管理员可维护
module("devices", "设备接入档案", "系统管理", [field("device", "设备编号", required=True), field("type", "设备类型", "select", True, ["温湿度传感器", "土壤传感器", "虫情灯", "摄像头"]), field("plot", "绑定地块"), field("frequency", "采集周期（秒）", "number"), field("note", "接入资料", "textarea")], roles=["admin"])
# 系统配置台账模块：只记录配置方案，不提供修改系统密钥或执行代码的能力
module("settings", "系统配置台账", "系统管理", [field("key", "配置项", required=True), field("value", "配置值", required=True), field("note", "生效说明", "textarea")], roles=["admin"], note="用于记录配置方案；不会通过台账直接更改系统密钥或执行代码。")

# 作物分组字典：用于前端“作物与种植方案”页面的分组选择
CROP_GROUPS = {"粮食作物":"水稻 小麦 玉米 高粱 谷子 大麦 燕麦 荞麦", "蔬菜作物":"番茄 黄瓜 辣椒 茄子 白菜 甘蓝 菠菜 生菜 西兰花 萝卜 胡萝卜 芹菜 韭菜 葱 大蒜 南瓜 冬瓜 丝瓜 豇豆", "水果作物":"苹果 梨 桃 葡萄 柑橘 草莓 蓝莓 猕猴桃 香蕉 芒果 西瓜 甜瓜", "油料与豆类":"大豆 花生 油菜 芝麻 向日葵 绿豆 蚕豆", "薯类作物":"马铃薯 甘薯 山药 芋头 木薯", "经济作物":"棉花 甘蔗 甜菜 茶树 咖啡", "药用作物":"黄芪 金银花 菊花 枸杞", "食用菌":"香菇 平菇 双孢菇 木耳"}

# 为地块模块追加天气定位经纬度字段：供地图定位与 Open-Meteo 天气查询使用
MODULES["lands"]["fields"] += [field("latitude", "纬度（天气定位）", "number"), field("longitude", "经度（天气定位）", "number")]
