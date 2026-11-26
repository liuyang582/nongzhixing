"""仅供浏览器写入验收：独立 SQLite、内存缓存、明确标注的外部服务测试桩。

运行：hou/.venv/Scripts/python.exe hou/scripts/browser_acceptance_server.py
不修改本地 .env，不连接 MySQL / Redis / 大模型，不修改生产附件。
"""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from datetime import datetime

BACKEND = Path(__file__).resolve().parents[1]
CASE = Path(tempfile.mkdtemp(prefix="nx-browser-acceptance-"))
sys.path.insert(0, str(BACKEND))
password = os.environ.get("BROWSER_ACCEPTANCE_PASSWORD") or secrets.token_urlsafe(24)
if len(password) < 8:
    raise RuntimeError("浏览器验收口令至少需要 8 个字符")
map_mode = os.environ.get('BROWSER_ACCEPTANCE_MAP') == 'true'
os.environ.update(DATABASE_URL="sqlite:///" + str(CASE / "acceptance.db"),
                  JWT_SECRET=secrets.token_urlsafe(48), DEMO_PASSWORD=password,
                  SEED_DEMO="true", QWEN_API_KEY="")
if not map_mode:
    os.environ.update(AMAP_KEY="", AMAP_SECURITY_CODE="")
from app import core
map_config = (core.settings.amap_key, core.settings.amap_security_code)
# Settings 使用的环境文件只在隔离进程禁用，生产配置文件保持原样。
core.settings = core.Settings(_env_file=None)
if map_mode:
    core.settings.amap_key, core.settings.amap_security_code = map_config
core.runtime = CASE
from app import main
assert core.engine.dialect.name == "sqlite"
main.settings.qwen_api_key = "local-test-stub"
main.settings.qwen_model = "浏览器验收测试桩（非真实模型）"


class MemoryCache:
    def __init__(self): self.values = {}
    async def ping(self): return True
    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, **kwargs): self.values[key] = value; return True
    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]
    async def expire(self, key, seconds): return True
    async def xadd(self, *args, **kwargs): return "1-0"
    async def aclose(self): pass


async def test_weather(**kwargs):
    return {"source": "浏览器验收天气测试桩（非真实天气）", "cached": False,
            "source_url": "", "fetched_at": datetime.now().isoformat(), "latitude": kwargs.get("latitude"),
            "longitude": kwargs.get("longitude"),
            "current": {"temperature_2m": 25, "relative_humidity_2m": 65,
                        "precipitation": 0, "wind_speed_10m": 3,
                        "time": datetime.now().isoformat()}, "daily": {
                            "time": [datetime.now().date().isoformat()],
                            "temperature_2m_max": [28], "temperature_2m_min": [20],
                            "precipitation_probability_max": [0]}}


async def test_model(state):
    return {"answer": "【浏览器验收测试桩】本回答仅验证页面、资料关联及人工确认流程，"
                      "不是外部模型识别结果。请在隔离测试中记录巡检反馈。",
            "review": "待人工确认", "steps": ["读取隔离测试资料", "本地测试桩回答", "待人工确认"]}


main.cache = MemoryCache()
main.weather = test_weather
# FastAPI keeps the registered callable even after a module attribute is replaced.
for route in main.app.routes:
    if getattr(route, "path", None) == "/api/weather":
        route.dependant.call = test_weather
main.workflow.ainvoke = test_model
(CASE / "login.txt").write_text(password, encoding="utf-8")
manifest = BACKEND.parent / "outputs" / "browser-acceptance-session.json"
manifest.write_text(json.dumps({"case": str(CASE), "credential_file": str(CASE / "login.txt"),
                                "database": "SQLite", "backend_port": 8001}, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    import uvicorn
    print("浏览器验收隔离服务：http://127.0.0.1:8001；全部数据及外部回答均为测试用途。", flush=True)
    try:
        uvicorn.run(main.app, host="127.0.0.1", port=8001, log_level="warning")
    finally:
        (CASE / "login.txt").unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
