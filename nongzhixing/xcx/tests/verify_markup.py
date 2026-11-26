import json
import pathlib
import re
import xml.etree.ElementTree as ET
root=pathlib.Path(__file__).resolve().parents[1]/'miniprogram'
for path in root.rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
app=json.loads((root/'app.json').read_text(encoding='utf-8'))
allowed={'chooseAddress','chooseLocation','choosePoi','getFuzzyLocation','getLocation','onLocationChange','startLocationUpdate','startLocationUpdateBackground'}
assert set(app.get('requiredPrivateInfos',[])) <= allowed, 'requiredPrivateInfos 存在不支持的接口声明'
for name in ['login','index','land','home','manage','me','records','editor','ai','service']:
    text=(root/'pages'/name/'index.wxml').read_text(encoding='utf-8')
    expressions=re.findall(r'\{\{(.*?)\}\}',text,re.S)
    assert all('&amp;' not in e and '&lt;' not in e for e in expressions), 'WXML 表达式不得使用 HTML 转义操作符'
    structural=re.sub(r'\{\{.*?\}\}', 'expression', text, flags=re.S)
    structural=re.sub(r'\b(selectable|auto-height)(?=\s|/|>)', r'\1="true"', structural)
    try:
        ET.fromstring('<root xmlns:wx="urn:wx">'+structural+'</root>')
    except ET.ParseError as e:
        raise RuntimeError(name+': '+structural[max(0,e.position[1]-50):e.position[1]+50]) from e
print('PASS JSON 与新页面 WXML 结构')
