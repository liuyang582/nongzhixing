"""一次真实模型图像联通检查，仅发送人工示意图，不写业务库或配置。"""
import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.ai import workflow


async def run():
    picture = ROOT / 'tests/fixtures/leaf-demo.png'
    image = 'data:image/png;base64,' + base64.b64encode(picture.read_bytes()).decode()
    try:
        result = await workflow.ainvoke({
            'kind': 'diagnosis', 'crop': '番茄', 'image': image,
            'question': '这是一张人工绘制的叶片示意图，用于本科项目功能验收，不是真实作物照片。请明确说明不能据此诊断真实病害，简短描述可见颜色与图形，并列出需要补充的真实资料。',
            'context': [{'demo': True, 'note': '仅人工示意图，无真实传感器或生产数据'}]})
        evidence = {'success': bool(result.get('answer', '').strip()),
                    'image_source': '人工叶片示意图，非真实作物照片',
                    'review': result.get('review'), 'steps': result.get('steps'),
                    'answer': result.get('answer'), 'business_database_written': False}
    except Exception as error:
        # 不打印 SDK 异常内容，避免其中包含请求配置。
        evidence = {'success': False, 'error_type': type(error).__name__,
                    'business_database_written': False}
    output = ROOT.parent / 'outputs/final-real-model.json'
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'success': evidence['success'], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(run())
