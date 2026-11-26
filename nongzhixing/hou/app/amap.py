# =============================================================================
# amap.py —— 高德地图服务接入层
# 职责：向前端签发地图 JS Key，并代理高德 REST 服务请求、在服务端附加安全密钥。
# 设计：安全密钥只存在于后端；代理采用固定路径白名单，避免被当成任意 URL 转发器。
# =============================================================================

# 模块说明：只转发项目实际使用的固定高德服务路径
"""高德 JS API 的安全代理。只转发已使用的固定服务路径。"""

# 导入 httpx：异步 HTTP 客户端，用于把浏览器请求转发给高德服务器
import httpx
# 导入 Redis 异常类型：限流服务不可用时区分处理
import redis.exceptions
# 导入 FastAPI 依赖与异常：实现鉴权和统一错误响应
from fastapi import Depends, HTTPException, Request
# 导入 Response：把高德的原始响应内容（含 JSONP）原样返回浏览器
from fastapi.responses import Response
# 导入全局配置：读取 AMAP_KEY 与 AMAP_SECURITY_CODE
from .core import settings

# 允许代理的高德服务路径白名单：地理编码/逆地理编码、关键字/周边搜索、输入提示、地图样式
ALLOWED={'v3/geocode/geo','v3/geocode/regeo','v3/place/text','v3/place/around','v3/assistant/inputtips','v4/map/styles'}

# 安装函数：main.py 启动时调用，把高德相关路由注册到 FastAPI 实例
def install(app,current_user,cache):
    # 配置接口：登录用户可获得前端加载地图所需的 JS Key 与服务代理前缀
    @app.get('/api/amap/config')
    def config(user=Depends(current_user)):
        # 未配置 Key 或安全密钥时明确返回 503，避免前端加载出半成品地图
        if not settings.amap_key or not settings.amap_security_code:raise HTTPException(503,'高德地图尚未配置 Key 与安全密钥')
        # 只返回 JS Key（可公开）与代理前缀；安全密钥始终留在服务端
        return {'key':settings.amap_key,'service_host':'/_AMapService'}

    # 代理接口：同时挂载 /api 前缀与一级路由，兼容 Vite 代理和部署环境的一级转发
    @app.get('/api/amap/_AMapService/{path:path}')
    @app.get('/_AMapService/{path:path}')
    # 路径参数 path 会截获 _AMapService 之后的全部路径
    async def proxy(path:str,request:Request):
        # 白名单校验：不在列表中的路径一律 404，防止代理被滥用
        if path not in ALLOWED:raise HTTPException(404,'地图服务路径不支持')
        # 再次确认配置完整，避免用空 Key 请求高德
        if not settings.amap_key or not settings.amap_security_code:raise HTTPException(503,'高德地图尚未配置')
        # 复制浏览器的查询参数（含 JSONP callback、platform=JS 等）
        params=dict(request.query_params)
        # 限制查询串长度，防止构造超大请求拖垮代理
        if len(request.url.query)>6000:raise HTTPException(422,'地图请求过长')
        # 校验 JSONP 回调名只含字母数字和 _. $，防止响应注入
        if params.get('callback') and not all(c.isalnum() or c in '_.$' for c in params['callback']):raise HTTPException(422,'回调名称无效')
        # 限流：按客户端 IP 计数，失败时 Redis 异常单独捕获
        try:
            # 限流键：nx:amap:rate:<客户端 IP>
            rate='nx:amap:rate:'+str(request.client.host if request.client else 'local')
            # 自增计数并返回当前分钟内的请求次数
            count=await cache().incr(rate)
            # 第一次请求时设置 60 秒过期，形成分钟级滑动窗口
            if count==1:await cache().expire(rate,60)
            # 单 IP 每分钟超过 120 次直接拒绝，保护上游配额
            if count>120:raise HTTPException(429,'地图请求过于频繁，请稍后重试')
        # 解释器找不到 Redis 时返回 503，而不是放行无保护的请求
        except redis.exceptions.RedisError:raise HTTPException(503,'地图代理限流服务暂不可用')
        # 用服务端配置覆盖客户端传来的 key/jscode，杜绝伪造和密钥泄露
        params.update(key=settings.amap_key,jscode=settings.amap_security_code)
        # 地图样式接口位于 webapi 域名，其余服务位于 restapi 域名
        host='https://webapi.amap.com/' if path=='v4/map/styles' else 'https://restapi.amap.com/'
        # 发起上游请求并处理网络异常
        try:
            # 15 秒超时；不自动跟随重定向，避免被上游带到非预期地址
            async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
                # 把路径与参数转发给高德服务器
                result=await client.get(host+path,params=params)
            # 上游非 200 统一视为服务不可用，避免把错误 HTML 返回前端
            if result.status_code!=200:raise HTTPException(502,'高德地图服务暂不可用')
            # 原样返回内容与 Content-Type，并禁止缓存，保证授权与实时性
            return Response(result.content,media_type=result.headers.get('content-type','application/json'),headers={'Cache-Control':'no-store'})
        # 网络层异常（超时、DNS、连接失败）统一转换为 502
        except httpx.HTTPError:raise HTTPException(502,'无法连接高德地图服务，请检查网络')
