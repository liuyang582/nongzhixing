# =============================================================================
# features.py —— 答辩功能扩展层
# 职责：环境阈值预警、生产时间轴、经营核算、采收溯源、通知、密码管理与报表导出。
# 设计：main.py 先完成基础模型和公共依赖，再调用 install(app, ns) 注册本文件的接口，
#       这样既能复用 scope/audit 等函数，又避免两个模块循环 import。
# =============================================================================

# 模块说明：集中实现答辩演示所需的扩展业务
"""答辩功能：配置预警、生产时间轴、经营核算、采收溯源、报表及账号管理。"""
# 导入内存字节流：用于在内存中生成 Excel/PDF，不落临时文件
import io
# 导入 JSON：序列化复杂字段、处理报表单元格
import json
# 导入安全随机数：生成不可预测的溯源码
import secrets
# 导入日期与时间类型：日期校验、时间戳格式化
from datetime import date, datetime
# 导入 Decimal：金额与重量使用十进制计算，避免浮点误差
from decimal import Decimal
# 导入 HTML 转义：生成 PDF 时防止用户内容被当作标签解析
from html import escape
# 导入 FastAPI 依赖、异常、查询参数与请求对象类型
from fastapi import Depends, HTTPException, Query, Request
# 导入 Response：直接返回二进制文件或图片
from fastapi.responses import Response
# 导入 Pydantic 基类、字段约束与跨字段校验器
from pydantic import BaseModel, Field, model_validator
# 导入 SQLAlchemy 查询函数、表结构检查与原生 SQL 执行
from sqlalchemy import select, inspect, text
# 导入 openpyxl 工作簿：生成 Excel 台账
from openpyxl import Workbook
# 导入 reportlab 字体注册模块：注册中文字体
from reportlab.pdfbase import pdfmetrics
# 导入 reportlab 内置中文 CID 字体
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
# 导入 PDF 文档、段落、间距和表格组件
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
# 导入默认样式表：正文、标题等
from reportlab.lib.styles import getSampleStyleSheet
# 导入颜色与对齐方式常量
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
# 导入二维码生成库：为溯源记录生成扫码入口
import qrcode
# 导入数据模型与数据库引擎：用户、记录、库存、订单、AI 任务、溯源
from .core import User, Record, Stock, Order, AIJob, Trace, engine, settings
# 导入业务模块目录与字段工厂：用于新增模块和生成报表表头
from .catalog import MODULES, field
# 导入静态农技资料：通过 /api/crop-guides 返回
from .knowledge import GUIDES

# 注册“其他经营支出”模块：本文件扩展 main.py 的模块目录
MODULES['expenses']={'id':'expenses','title':'其他经营支出','group':'投入与经营','roles':['farmer'],'note':'记录未在农资或农机台账登记的支出，避免同一笔投入重复计入。已关闭记录不计入核算。','fields':[field('plot','地块'),field('date','支出日期','date',True),field('category','费用类别','select',True,['人工','仓储','运输','土地租金','其他']),field('cost','金额（元）','number',True),field('note','凭证与用途','textarea',True)]}

# 增量迁移函数：服务启动时执行，保证旧数据库也能获得新增字段
def migrate():
    # 注释：迁移必须可重复执行，且不删除任何用户数据
    # 单次、可重复执行的增量升级，不删除用户表和记录。
    # 读取 nx_users 表现有列名集合
    columns={c['name'] for c in inspect(engine).get_columns('nx_users')}
    # 如果缺少 token_version 列，说明是旧版本数据库
    if 'token_version' not in columns:
        # 开启事务执行 ALTER TABLE
        with engine.begin() as conn:
            # 新增 token_version 列，默认 0，保证旧账号令牌仍可用
            conn.execute(text('ALTER TABLE nx_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0'))

# 环境阈值规则请求模型：一条规则对应“某地块 × 某作物 × 某生育阶段”的温湿度范围
class RuleInput(BaseModel):
    # 关联地块 ID，必须为正整数
    plot_id:int=Field(gt=0)
    # 适用作物名称
    crop:str=Field(min_length=1,max_length=64)
    # 适用生育阶段，可为“全部阶段”
    stage:str=Field(min_length=1,max_length=64)
    # 空气温度下限（℃）
    temperature_min:float=Field(ge=-50,le=70)
    # 空气温度上限（℃）
    temperature_max:float=Field(ge=-50,le=70)
    # 空气湿度下限（%）
    humidity_min:float=Field(ge=0,le=100)
    # 空气湿度上限（%）
    humidity_max:float=Field(ge=0,le=100)
    # 土壤湿度下限（%）
    soil_min:float=Field(ge=0,le=100)
    # 土壤湿度上限（%）
    soil_max:float=Field(ge=0,le=100)
    # 阈值设置依据，必须填写，便于追溯来源
    basis:str=Field(min_length=2,max_length=1000)
    # 模型级校验：对象构造完成后执行
    @model_validator(mode='after')
    # 校验范围与依据是否合法
    def ranges(self):
        # 依次检查温度、湿度、土壤三项指标
        for metric in ('temperature','humidity','soil'):
            # 下限大于上限时直接报错
            if getattr(self,metric+'_min')>getattr(self,metric+'_max'):
                # 抛出校验异常，FastAPI 会返回 422
                raise ValueError('下限不能大于上限')
        # 依据去除空白后为空时视为未填写
        if not self.basis.strip(): raise ValueError('请填写阈值依据')
        # 返回自身，表示校验通过
        return self

# 采收登记请求模型：关联生长批次、批号、日期、重量与等级
class HarvestInput(BaseModel):
    # 关联生长记录 ID
    growth_id:int=Field(gt=0)
    # 产品批号：用于入库和溯源对应
    batch:str=Field(min_length=1,max_length=64)
    # 实际采收日期，长度固定 10 位（YYYY-MM-DD）
    date: str=Field(min_length=10,max_length=10)
    # 实收重量（kg），Decimal 保证精度
    quantity:Decimal=Field(gt=0,le=100000000,max_digits=12,decimal_places=3)
    # 等级只允许 A / B / 未分级
    grade:str=Field(default='A',pattern='^(A|B|未分级)$')
    # 模型级校验：日期格式与未来日期
    @model_validator(mode='after')
    # 校验采收日期不能晚于今天
    def harvest_date(self):
        # 先解析 ISO 日期，格式错误会抛出 ValueError
        date.fromisoformat(self.date)
        # 实际采收日期不可能在未来
        if date.fromisoformat(self.date)>date.today():raise ValueError('实际采收日期不能在未来')
        # 校验通过返回自身
        return self

# 修改密码请求模型：需要提供旧密码与新密码
class PasswordChange(BaseModel):
    # 旧密码：用于验证操作人身份
    old_password:str=Field(min_length=1,max_length=128)
    # 新密码：至少 8 位
    new_password:str=Field(min_length=8,max_length=128)
# 管理员重置密码请求模型：只需新密码
class PasswordReset(BaseModel):
    # 重置后的新密码：至少 8 位
    new_password:str=Field(min_length=8,max_length=128)

# 安装函数：把本文件的全部扩展路由注册到 FastAPI 应用
def install(app, ns):
    # 从 main.py 的全局命名空间取出公共依赖，避免重复实现和循环导入
    current=ns['current_user']; get_db=ns['get_db']; scope=ns['scope']; info=ns['record_info']; audit=ns['audit']; farmer=ns['farmer_only']; get_plot=ns['get_plot']; get_growth=ns['get_growth']; store=ns['password_store']

    # 通用查询助手：按角色数据范围查询指定模块的记录，并按创建时间升序排列
    def rows(db,user,modules):
        # scope 负责追加 org / district 条件，实现经营主体与辖区的数据隔离
        return db.scalars(scope(select(Record).where(Record.module.in_(modules)).order_by(Record.created_at,Record.id),Record,user)).all()

    # 环境预警评估：新增或修改环境记录后自动比对已启用阈值规则
    def evaluate(env,user,db):
        # 没有关联地块的环境记录无法匹配规则，直接返回
        if not env.data.get('plot_id'):return
        # 取出关联地块，同时校验访问权限
        land=get_plot(env.data['plot_id'],user,db)
        # 找出该地块的全部生长记录
        growth=[r for r in rows(db,user,['growth']) if r.data.get('plot_id')==land.id]
        # 没有生长记录就没有作物与生育阶段，无法评估
        if not growth:return
        # 取最近一条生长记录作为当前批次
        active=growth[-1]
        # 查询本组织所有“启用”状态的阈值规则，并加行锁防止并发重复生成告警
        rules=db.scalars(select(Record).where(Record.module=='env-rules',Record.org==user.org,Record.status=='启用').with_for_update()).all()
        # 预先读取已有告警，用于去重判断
        alerts=rows(db,user,['alerts'])
        # 逐条规则进行比对
        for rule in rules:
            # 取出规则中的业务字段
            d=rule.data
            # 地块、作物、阶段任一不匹配则跳过
            if d['plot_id']!=land.id or d['crop']!=active.data.get('crop') or d['stage'] not in ('全部阶段',active.data.get('stage')):continue
            # 依次检查温度、湿度、土壤三项指标
            for key,label in [('temperature','空气温度'),('humidity','空气湿度'),('soil','土壤湿度')]:
                # 读取本次环境记录中的指标值
                value=env.data.get(key)
                # 指标缺失或在范围内则不告警
                if value is None or d[key+'_min']<=value<=d[key+'_max']:continue
                # 同一规则、同一指标已有未关闭告警时不重复生成，避免告警风暴
                if any(a.data.get('rule_id')==rule.id and a.data.get('metric')==key and a.status!='已关闭' for a in alerts):continue
                # 构造告警记录：带上地块、生长批次、规则、指标、环境记录来源与阈值依据
                alert=Record(module='alerts',title=f'{land.title}{label}超出配置范围',org=user.org,district=user.district,creator_id=user.id,demo=env.demo or env.data.get('source')=='模拟器',data={'plot_id':land.id,'plot':land.title,'growth_id':active.id,'rule_id':rule.id,'metric':key,'environment_id':env.id,'type':'环境异常','level':'关注','note':f'测量 {value}；用户配置范围 {d[key+"_min"]}–{d[key+"_max"]}。来源：{env.data.get("source")}；依据：{d["basis"]}。请人工核查现场。'})
                # 加入会话并同步到内存列表，保证同一请求内去重有效
                db.add(alert);alerts.append(alert)
        # 记录一次规则评估审计并提交事务
        audit(db,user,'环境规则评估',{'environment_id':env.id});db.commit()
    # 把评估函数暴露给 main.py，创建/修改环境记录时调用
    ns['feature_environment_event']=evaluate

    # 查询环境阈值规则列表
    @app.get('/api/environment-rules')
    # 路由函数：仅经营主体可查看
    def rules(user=Depends(current),db=Depends(get_db)):
        # 校验角色
        farmer(user)
        # 返回本组织全部阈值规则
        return [info(r) for r in rows(db,user,['env-rules'])]

    # 新增环境阈值规则
    @app.post('/api/environment-rules')
    # 路由函数：入参由 RuleInput 校验
    def add_rule(body:RuleInput,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可配置阈值；同时校验地块权限
        farmer(user);land=get_plot(body.plot_id,user,db)
        # 创建规则记录：标题自动拼接地块/作物/阶段，演示标记继承地块
        r=Record(module='env-rules',title=f'{land.title} / {body.crop} / {body.stage}',demo=land.demo,status='启用',data=body.model_dump(),org=user.org,district=user.district,creator_id=user.id)
        # 写库、记审计并提交
        db.add(r);db.flush();audit(db,user,'新增环境阈值',{'id':r.id});db.commit();return info(r)

    # 启用 / 停用阈值规则
    @app.post('/api/environment-rules/{rule_id}/toggle')
    # 路由函数：按规则 ID 切换状态
    def toggle(rule_id:int,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可用；加行锁防止并发切换
        farmer(user);r=db.scalar(select(Record).where(Record.id==rule_id,Record.module=='env-rules',Record.org==user.org).with_for_update())
        # 规则不存在时返回 404
        if not r:raise HTTPException(404,'规则不存在')
        # 在启用与停用之间切换，并记录审计
        r.status='停用' if r.status=='启用' else '启用';audit(db,user,'切换环境阈值',{'id':r.id,'status':r.status});db.commit();return info(r)

    # 生产时间轴：把地块相关的生长、环境、任务、采收、告警和 AI 分析合并成事件流
    @app.get('/api/plots/{plot_id}/timeline')
    # 路由函数：可选 growth_id 用于只看某个生长批次
    def timeline(plot_id:int,growth_id:int|None=None,user=Depends(current),db=Depends(get_db)):
        # 校验地块访问权限
        land=get_plot(plot_id,user,db)
        # 指定生长批次时先校验它属于该地块
        if growth_id:get_growth(growth_id,land,user,db)
        # 事件结果列表
        events=[]
        # 遍历五类业务记录
        for r in rows(db,user,['growth','environment','tasks','harvest','alerts']):
            # 只保留属于当前地块的记录
            if r.data.get('plot_id')!=plot_id:continue
            # 指定批次时：环境记录属于地块即可；其他记录必须匹配批次
            if growth_id and r.module!='environment' and (r.id if r.module=='growth' else r.data.get('growth_id'))!=growth_id:continue
            # 追加记录创建事件：时间、类型、标题、状态、演示标记和详情
            events.append({'key':f'record-{r.id}','time':r.created_at.isoformat(),'kind':r.module,'title':r.title,'status':r.status,'demo':r.demo,'detail':r.data})
            # 任务被更新过时，额外追加一条“执行反馈”事件
            if r.module=='tasks' and r.updated_at!=r.created_at:
                # 反馈事件使用更新时间，标题带上任务状态
                events.append({'key':f'feedback-{r.id}','time':r.updated_at.isoformat(),'kind':'feedback','title':r.title+' · '+r.status,'status':r.status,'demo':r.demo,'detail':{'note':r.data.get('note')}})
        # 把 AI 分析任务也纳入时间轴
        for j in db.scalars(scope(select(AIJob),AIJob,user)).all():
            # 只保留属于当前地块（及指定批次）的分析
            if j.result.get('plot_id')==plot_id and (not growth_id or j.result.get('growth_id')==growth_id):
                # 追加 AI 事件：问题、状态、关联任务 ID 和回答
                events.append({'key':f'ai-{j.id}','time':j.created_at.isoformat(),'kind':'ai','title':j.question,'status':j.status,'demo':land.demo,'detail':{'answer':j.result.get('answer'),'task_id':j.task_id}})
        # 按时间和事件键排序后返回
        return sorted(events,key=lambda x:(x['time'],x['key']))

    # 经营核算核心函数：汇总成本、销售、月度数据与地块每亩差额
    def finance_data(year,user,db,include_demo):
        # 仅经营主体可核算；取出农资、农机、其他支出和地块记录
        farmer(user);items=rows(db,user,['inputs','machines','expenses','lands']);lands={r.id:r for r in items if r.module=='lands'}
        # 成本明细、销售明细与 12 个月汇总容器
        costs=[];sales=[];monthly=[{'month':f'{year}-{m:02d}','cost':Decimal(0),'sales':Decimal(0)} for m in range(1,13)]
        # 逐条处理成本类记录
        for r in items:
            # 跳过地块记录、已关闭记录，以及不包含演示数据时的演示记录
            if r.module=='lands' or r.status=='已关闭' or (r.demo and not include_demo):continue
            # 取业务日期；没有日期时退化为创建日期
            day=str(r.data.get('date') or r.created_at.date().isoformat())
            # 只统计指定年份
            if not day.startswith(str(year)+'-'):continue
            # 读取金额并保留两位小数
            amount=Decimal(str(r.data.get('cost') or 0)).quantize(Decimal('.01'))
            # 追加成本明细
            costs.append({'id':r.id,'source':r.module,'title':r.title,'date':day,'amount':float(amount),'plot_id':r.data.get('plot_id'),'demo':r.demo})
            # 累加到对应月份的成本列
            monthly[date.fromisoformat(day).month-1]['cost']+=amount
        # 建立库存批次索引，便于从订单反查作物与来源
        stocks={s.id:s for s in db.scalars(scope(select(Stock),Stock,user)).all()}
        # 建立采收记录索引，便于把库存来源映射回地块
        harvests={r.id:r for r in rows(db,user,['harvest'])}
        # 遍历订单，只统计“已出库”的销售
        for o in db.scalars(scope(select(Order),Order,user)).all():
            # 取订单对应库存
            stock=stocks.get(o.stock_id)
            # 库存缺失、未出库、或为演示数据且本次不包含演示时跳过
            if not stock or o.status!='已出库' or (stock.demo and not include_demo):continue
            # 按订单创建日期归入年度
            day=o.created_at.date()
            # 非指定年份跳过
            if day.year!=year:continue
            # 计算订单金额并保留两位小数
            amount=(o.quantity*o.price).quantize(Decimal('.01'));plot_id=None
            # 库存来源形如 harvest:12 时，反查采收记录得到地块
            if stock.source.startswith('harvest:') and stock.source.split(':',1)[1].isdigit():
                # 根据采收 ID 找到地块 ID
                h=harvests.get(int(stock.source.split(':')[1]));plot_id=h.data.get('plot_id') if h else None
            # 追加销售明细
            sales.append({'id':o.id,'crop':stock.crop,'date':day.isoformat(),'amount':float(amount),'plot_id':plot_id,'demo':stock.demo})
            # 累加到对应月份的销售列
            monthly[day.month-1]['sales']+=amount
        # 地块维度汇总结果
        plot_rows=[]
        # 逐个地块计算成本、销售、差额和每亩差额
        for lid,l in lands.items():
            # 不包含演示数据时跳过演示地块
            if l.demo and not include_demo:continue
            # 汇总该地块的成本与销售
            cost=sum((Decimal(str(x['amount'])) for x in costs if x['plot_id']==lid),Decimal(0));income=sum((Decimal(str(x['amount'])) for x in sales if x['plot_id']==lid),Decimal(0));area=Decimal(str(l.data.get('area') or l.data.get('measured_area') or 0))
            # 每亩差额 = 差额 / 面积；面积为 0 时返回 None
            plot_rows.append({'plot_id':lid,'title':l.title,'area':float(area),'cost':float(cost),'sales':float(income),'profit':float(income-cost),'profit_per_mu':float((income-cost)/area) if area>0 else None})
        # 计算总成本与总销售
        total_cost=sum((Decimal(str(x['amount'])) for x in costs),Decimal(0));income=sum((Decimal(str(x['amount'])) for x in sales),Decimal(0))
        # 返回完整核算结果，并附带口径说明与未关联地块金额
        return {'year':year,'include_demo':include_demo,'cost':float(total_cost),'sales':float(income),'profit':float(income-total_cost),'monthly':[{**m,'cost':float(m['cost']),'sales':float(m['sales'])} for m in monthly],'plots':plot_rows,'costs':costs,'orders':sales,'unallocated_cost':sum(x['amount'] for x in costs if not x['plot_id']),'unallocated_sales':sum(x['amount'] for x in sales if not x['plot_id']),'note':'登记口径：农资、农机及其他支出合计；已出库销售按订单创建年度统计，不代表回款、会计净利润或未来收益。未关联地块的金额单独列示。'}

    # 查询年度经营核算
    @app.get('/api/finance')
    # 路由函数：year 默认当年；include_demo 控制是否包含演示数据
    def finance(year:int=Query(default=date.today().year,ge=2000,le=2100),include_demo:bool=False,user=Depends(current),db=Depends(get_db)):
        # 直接复用核心核算函数
        return finance_data(year,user,db,include_demo)

    # 导出年度经营核算为 Excel 或 PDF
    @app.get('/api/finance/export/{format}')
    # 路由函数：format 只支持 xlsx / pdf
    def finance_export(format:str,year:int=Query(default=date.today().year,ge=2000,le=2100),include_demo:bool=False,user=Depends(current),db=Depends(get_db)):
        # 先计算核算数据
        data=finance_data(year,user,db,include_demo)
        # 非法格式返回 422
        if format not in ('xlsx','pdf'):raise HTTPException(422,'支持 xlsx 或 pdf')
        # 内存缓冲区：承载生成的文件
        buf=io.BytesIO();header=['地块','面积（亩）','登记成本','出库销售','登记差额','每亩差额']
        # 把地块汇总转换成表格行
        table=[[p['title'],p['area'],p['cost'],p['sales'],p['profit'],p['profit_per_mu']] for p in data['plots']]
        # 生成 Excel 版本
        if format=='xlsx':
            # 创建工作簿与“经营汇总”工作表
            wb=Workbook();ws=wb.active;ws.title='经营汇总';ws.append(['年度',year,'含演示数据',include_demo]);ws.append(['成本',data['cost'],'销售',data['sales'],'差额',data['profit']]);ws.append([data['note']]);ws.append(['未关联成本',data['unallocated_cost'],'未关联销售',data['unallocated_sales']]);ws.append(header)
            # 写入表格行，并对以公式符号开头的文本加单引号，防止 Excel 公式注入
            for row in table:ws.append(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
            # 新增“月度统计”工作表
            monthly=wb.create_sheet('月度统计');monthly.append(['月份','成本（元）','销售（元）'])
            # 写入 12 个月数据
            for m in data['monthly']:monthly.append([m['month'],m['cost'],m['sales']])
            # 统一列宽，便于打印和查看
            for sheet in wb:
                for col in sheet.columns:sheet.column_dimensions[col[0].column_letter].width=24
            # 保存到内存，并设置 Excel MIME 类型
            wb.save(buf);mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        # 生成 PDF 版本
        else:
            # 注册内置中文宋体，设置自动换行与行距
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));style=getSampleStyleSheet()['Normal'];style.fontName='STSong-Light';style.wordWrap='CJK';style.leading=17
            # 组装汇总文字
            lines=[f'农知行 {year} 年经营汇总 · 含演示数据：{include_demo}',f'成本 {data["cost"]:.2f} 元；出库销售 {data["sales"]:.2f} 元；登记差额 {data["profit"]:.2f} 元',data['note'],f'未关联成本 {data["unallocated_cost"]:.2f}；未关联销售 {data["unallocated_sales"]:.2f}']
            # 追加每个地块的汇总行
            lines += ['；'.join(f'{label}：{value if value is not None else "缺少面积"}' for label,value in zip(header,row)) for row in table]
            # 生成 PDF 并设置 MIME 类型
            SimpleDocTemplate(buf).build([Paragraph(escape(line),style) for line in lines]);mime='application/pdf'
        # 记录导出审计并返回附件
        audit(db,user,'导出经营核算',{'year':year,'format':format,'include_demo':include_demo});db.commit()
        # 以附件形式返回文件流
        return Response(buf.getvalue(),media_type=mime,headers={'Content-Disposition':f'attachment; filename="finance-{year}.{format}"'})

    # 登记采收：必须关联生长批次，日期不能早于播种日期
    @app.post('/api/harvests')
    # 路由函数：入参由 HarvestInput 校验
    def add_harvest(body:HarvestInput,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可登记；按 ID 和本组织范围查生长记录
        farmer(user);g=db.scalar(select(Record).where(Record.id==body.growth_id,Record.module=='growth',Record.org==user.org))
        # 生长记录不存在或未关联地块时拒绝
        if not g or not g.data.get('plot_id'):raise HTTPException(422,'选择已关联地块的生长记录')
        # 校验地块访问权限
        land=get_plot(g.data['plot_id'],user,db)
        # 采收日期不能早于播种日期
        if body.date<g.data['sow_date']:raise HTTPException(422,'采收日期不能早于播种日期')
        # 创建采收记录：继承生长与地块的演示标记
        r=Record(module='harvest',title=f'{g.data["crop"]}采收 {body.batch}',demo=g.demo or land.demo,org=user.org,district=user.district,creator_id=user.id,data={'plot_id':land.id,'plot':land.title,'growth_id':g.id,'crop':g.data['crop'],'batch':body.batch,'date':body.date,'quantity':float(body.quantity),'grade':body.grade})
        # 写库、记审计并提交
        db.add(r);db.flush();audit(db,user,'登记关联采收',{'id':r.id});db.commit();return info(r)

    # 采收入库并生成溯源记录
    @app.post('/api/harvests/{harvest_id}/stock')
    # 路由函数：把采收记录转换为库存批次与溯源码
    def harvest_stock(harvest_id:int,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可用；按本组织范围查找采收记录并加行锁
        farmer(user);h=db.scalar(select(Record).where(Record.id==harvest_id,Record.module=='harvest',Record.org==user.org).with_for_update())
        # 采收记录不存在或未关联地块时拒绝
        if not h or not h.data.get('plot_id'):raise HTTPException(404,'关联采收记录不存在')
        # 已存在溯源记录说明已入库，禁止重复入库
        if db.scalar(select(Trace).where(Trace.harvest_id==h.id)):raise HTTPException(409,'已入库，不能重复入库')
        # 入库必须具备生长批次、产品批号和正数重量
        if not h.data.get('growth_id') or not h.data.get('batch') or Decimal(str(h.data.get('quantity') or 0))<=0:raise HTTPException(422,'采收须关联生长批次，填写产品批号和正数重量')
        # 校验地块与生长记录归属
        land=get_plot(h.data['plot_id'],user,db);g=get_growth(h.data['growth_id'],land,user,db)
        # 取出该生长批次关联的农事任务，写入溯源快照
        tasks=[r for r in rows(db,user,['tasks']) if r.data.get('growth_id')==g.id]
        # 创建库存批次，source 记录 harvest:<id> 以支持后续反查
        stock=Stock(crop=h.data['crop'],batch=h.data['batch'],grade=h.data['grade'],quantity=Decimal(str(h.data['quantity'])),org=user.org,district=user.district,source=f'harvest:{h.id}',demo=h.demo)
        # 先写库存以获得自增 ID
        db.add(stock);db.flush()
        # 组装公开溯源快照：只包含生产摘要，不含隐私与合同信息
        snapshot={'crop':stock.crop,'batch':stock.batch,'grade':stock.grade,'quantity':float(stock.quantity),'harvest_date':h.data['date'],'plot':land.title,'producer':user.org,'variety':g.data.get('variety'),'sow_date':g.data['sow_date'],'stage':g.data['stage'],'tasks':[{'type':t.data.get('type'),'date':t.data.get('date'),'status':t.status} for t in tasks],'demo':h.demo or land.demo,'notice':'生产记录追溯参考，不是产品检测报告或官方合格证。'}
        # 生成 48 位随机溯源码；默认不公开
        trace=Trace(token=secrets.token_hex(24),org=user.org,district=user.district,harvest_id=h.id,stock_id=stock.id,snapshot=snapshot)
        # 保存溯源记录，把采收状态改为“已入库”，记审计并提交
        db.add(trace);h.status='已入库';audit(db,user,'采收入库并生成溯源码',{'harvest_id':h.id,'stock_id':stock.id});db.commit();return {'stock_id':stock.id,'trace_id':trace.id}

    # 查询本组织的溯源记录列表
    @app.get('/api/traces')
    # 路由函数：仅经营主体可查看自己的溯源
    def traces(user=Depends(current),db=Depends(get_db)):
        # 返回 ID、溯源码、公开状态、库存 ID 与快照
        farmer(user);return [{'id':t.id,'token':t.token,'published':t.published,'stock_id':t.stock_id,'snapshot':t.snapshot} for t in db.scalars(select(Trace).where(Trace.org==user.org)).all()]

    # 切换溯源的公开 / 未公开状态
    @app.post('/api/traces/{trace_id}/publish')
    # 路由函数：默认未公开，确认后才允许扫码查看
    def publish(trace_id:int,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可用；按本组织范围查找并加锁
        farmer(user);t=db.scalar(select(Trace).where(Trace.id==trace_id,Trace.org==user.org).with_for_update())
        # 不存在时返回 404
        if not t:raise HTTPException(404,'溯源码不存在')
        # 切换公开状态并记录审计
        t.published=not t.published;audit(db,user,'切换溯源公开状态',{'id':t.id,'published':t.published});db.commit();return {'published':t.published}

    # 公开溯源查询：无需登录，只返回已公开的快照
    @app.get('/api/public/trace/{token}')
    # 路由函数：消费者扫码访问
    def public_trace(token:str,db=Depends(get_db)):
        # 同时匹配随机码和 published=True，未公开的返回 404
        t=db.scalar(select(Trace).where(Trace.token==token,Trace.published==True))
        # 不存在或未公开时统一提示
        if not t:raise HTTPException(404,'溯源信息不存在或未公开')
        # 返回冻结的生产摘要快照
        return t.snapshot

    # 生成溯源二维码 PNG
    @app.get('/api/traces/{trace_id}/qr')
    # 路由函数：二维码指向前端公开溯源页
    def qr(trace_id:int,request:Request,user=Depends(current),db=Depends(get_db)):
        # 仅经营主体可用；只能生成本组织的溯源码
        farmer(user);t=db.scalar(select(Trace).where(Trace.id==trace_id,Trace.org==user.org))
        # 不存在时返回 404
        if not t:raise HTTPException(404,'溯源码不存在')
        # 二维码地址：优先 PUBLIC_BASE_URL，留空时按当前访问地址生成，本机和局域网都能扫码
        base=(settings.public_base_url or str(request.base_url)).rstrip('/')
        # 在内存中生成 PNG 二维码
        buf=io.BytesIO();qrcode.make(base+'/trace/'+t.token).save(buf,format='PNG')
        # 以附件形式返回
        return Response(buf.getvalue(),media_type='image/png',headers={'Content-Disposition':f'attachment; filename="trace-{t.id}.png"'})

    # 消息与待办：聚合任务、告警、审核与待确认的 AI 建议
    @app.get('/api/notifications')
    # 路由函数：按角色返回不同的待办来源
    def notifications(user=Depends(current),db=Depends(get_db)):
        # 经营主体看任务与告警；管理员看农药资料与基础资料审核
        modules=['tasks','alerts'] if user.role!='admin' else ['pesticides','dictionary']
        # 筛选待处理 / 进行中 / 待审核的记录
        pending=[{'key':f'{r.module}-{r.id}','title':r.title,'module':r.module,'status':r.status,'time':r.updated_at.isoformat()} for r in rows(db,user,modules) if r.status in ('待处理','进行中','待审核')]
        # 经营主体额外把“待人工确认”的 AI 建议加入待办
        if user.role=='farmer':
            # AI 建议以问题作为标题，module 指向种植流程页
            pending += [{'key':f'ai-{j.id}','title':j.question,'module':'planting-flow','status':'待人工确认','time':j.created_at.isoformat()} for j in db.scalars(select(AIJob).where(AIJob.org==user.org,AIJob.status=='待确认')).all()]
        # 按时间倒序返回
        return sorted(pending,key=lambda x:x['time'],reverse=True)

    # 修改当前账号密码
    @app.post('/api/auth/password')
    # 路由函数：校验旧密码后写入新密码并使旧令牌失效
    def change_password(body:PasswordChange,user=Depends(current),db=Depends(get_db)):
        # 加行锁读取当前用户，避免并发修改
        locked=db.scalar(select(User).where(User.id==user.id).with_for_update())
        # 旧密码不正确时拒绝
        if not store.verify(body.old_password,locked.password):raise HTTPException(400,'原密码不正确')
        # 新密码不能与旧密码相同
        if store.verify(body.new_password,locked.password):raise HTTPException(422,'新密码不能与原密码相同')
        # 保存新密码，令牌版本加 1 使旧 JWT 全部失效，记录审计
        locked.password=store.encode(body.new_password);locked.token_version+=1;audit(db,user,'修改密码');db.commit();return {'ok':True,'note':'请重新登录'}

    # 管理员重置指定账号密码
    @app.post('/api/admin/users/{uid}/password')
    # 路由函数：仅管理员可用
    def reset_password(uid:int,body:PasswordReset,user=Depends(current),db=Depends(get_db)):
        # 非管理员拒绝
        if user.role!='admin':raise HTTPException(403,'仅管理员可重置密码')
        # 不允许通过该接口修改自己的密码，避免绕过旧密码校验
        if uid==user.id:raise HTTPException(422,'自己的密码请通过修改密码功能处理')
        # 加锁读取目标账号
        target=db.scalar(select(User).where(User.id==uid).with_for_update())
        # 账号不存在时返回 404
        if not target:raise HTTPException(404,'账号不存在')
        # 写入新密码并使目标账号旧令牌失效，记录审计
        target.password=store.encode(body.new_password);target.token_version+=1;audit(db,user,'管理员重置密码',{'user_id':uid});db.commit();return {'ok':True}

    # 返回静态农技资料
    @app.get('/api/crop-guides')
    # 路由函数：登录用户均可查看
    def guides(user=Depends(current)):
        # 直接返回 knowledge.py 中的人工整理资料
        return GUIDES

    # 通用正式报表导出：任意业务模块导出为 Excel 或 PDF
    @app.get('/api/reports/{module}/{format}')
    # 路由函数：先做模块权限校验，再导出当前用户可见数据
    def reports(module:str,format:str,user=Depends(current),db=Depends(get_db)):
        # 校验模块存在性与角色权限
        spec=ns['authorize'](module,user)
        # 只支持 xlsx / pdf
        if format not in ('xlsx','pdf'):raise HTTPException(422,'支持 xlsx 或 pdf')
        # 查询记录；表头由模块字段目录动态生成
        records=rows(db,user,[module]);headers=['标题','状态','来源','更新时间']+[f['label'] for f in spec['fields']]
        # 单元格清洗：字典/列表转 JSON，公式开头加单引号防注入
        def cell(v):
            # 空值转空字符串，复杂类型转 JSON，其余转字符串
            value='' if v is None else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)
            # 防止 Excel 把单元格当作公式执行
            return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
        # 组装数据行
        data=[[cell(r.title),r.status,'演示' if r.demo else '用户录入',r.updated_at.isoformat()]+[cell(r.data.get(f['key'])) for f in spec['fields']] for r in records]
        # 内存缓冲区
        buf=io.BytesIO()
        # 生成 Excel
        if format=='xlsx':
            # 创建工作表并写入表头
            wb=Workbook();ws=wb.active;ws.title='业务台账';ws.append(headers)
            # 写入数据行
            for row in data:ws.append(row)
            # 冻结表头、启用自动筛选、统一列宽
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            # 设置列宽
            for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=24
            # 保存并设置 MIME
            wb.save(buf);mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        # 生成 PDF
        else:
            # 注册中文字体并设置正文样式
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));styles=getSampleStyleSheet();style=styles['Normal'];style.fontName='STSong-Light';style.fontSize=10;style.leading=15;style.wordWrap='CJK';style.alignment=TA_LEFT
            # PDF 开头：模块标题、导出时间、数据范围与条数
            story=[Paragraph(escape('农知行 · '+spec['title']),style),Paragraph(escape(f'导出时间：{datetime.now().isoformat(timespec="seconds")}；数据范围：{user.org}；共 {len(data)} 条。'),style),Spacer(1,12)]
            # 每条记录作为一个段落块：标题 + 各字段
            for row in data:
                # 记录标题
                story.append(Paragraph(escape(row[0]),style))
                # 逐字段输出“标签：值”，换行转为 <br/>
                for label,value in zip(headers[1:],row[1:]):story.append(Paragraph(escape(label+'：'+str(value)).replace('\n','<br/>'),style))
                # 记录之间留出间距
                story.append(Spacer(1,12))
            # 页脚回调：打印页码
            def footer(canvas,doc):
                # 设置 9 号字并绘制页脚
                canvas.setFont('STSong-Light',9);canvas.drawString(40,25,'农知行业务记录 · 第 '+str(doc.page)+' 页')
            # 生成 PDF，首页和后续页共用页脚
            SimpleDocTemplate(buf,rightMargin=40,leftMargin=40,topMargin=35,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer);mime='application/pdf'
        # 记录导出审计
        audit(db,user,'导出正式报表',{'module':module,'format':format,'count':len(data)});db.commit()
        # 以附件形式返回
        return Response(buf.getvalue(),media_type=mime,headers={'Content-Disposition':f'attachment; filename="{module}.{format}"'})
