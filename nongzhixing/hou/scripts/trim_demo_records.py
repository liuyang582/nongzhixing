"""将现有库的演示台账保留三条，先备份；不删除用户录入或 AI 历史。"""
import argparse
from datetime import datetime
from pathlib import Path
import json
import sys
from sqlalchemy import select, func

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import SessionLocal, Record, Stock, Trace, Order, AIJob, Audit, User

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
keep_ids = {32, 33, 35}


def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


with SessionLocal() as db:
    demos = list(db.scalars(select(Record).where(Record.demo.is_(True))))
    if {r.id for r in demos} == keep_ids:
        print('已保留三条演示台账，无需重复清理。')
        sys.exit(0)
    assert keep_ids <= {r.id for r in demos}, '目标三条演示记录缺失，停止清理'
    deleted = [r for r in demos if r.id not in keep_ids]
    remove_ids = {r.id for r in deleted}
    user_rows = list(db.scalars(select(Record).where(Record.demo.is_(False))))
    before = {r.id: serialize(r) for r in user_rows}
    for row in user_rows:
        assert not ({row.data.get('plot_id'), row.data.get('growth_id')} & remove_ids), '用户记录引用待删演示记录，停止清理'
    for job in db.scalars(select(AIJob)):
        assert not ({job.result.get('plot_id'), job.result.get('growth_id'), job.task_id} & remove_ids), 'AI 历史引用待删主记录，停止清理'
    traces = list(db.scalars(select(Trace).where(Trace.harvest_id.in_(remove_ids))))
    assert all(t.snapshot.get('demo') is True and not t.published for t in traces), '关联溯源不是未公开演示数据，停止清理'
    stocks = list(db.scalars(select(Stock).where(Stock.demo.is_(True))))
    stock_ids = {s.id for s in stocks}
    assert not db.scalar(select(Order.id).where(Order.stock_id.in_(stock_ids))), '演示库存已有关联订单，停止清理'
    assert all(t in traces or t.stock_id not in stock_ids for t in db.scalars(select(Trace))), '保留溯源引用演示库存，停止清理'
    summary = {'kept_record_ids': sorted(keep_ids), 'removed_demo_records': len(deleted),
               'removed_demo_stocks': len(stocks), 'removed_demo_traces': len(traces),
               'preserved_user_records': len(before)}
    if not args.apply:
        print(json.dumps(summary, ensure_ascii=False))
        sys.exit(0)
    backup = Path(__file__).resolve().parents[2] / 'outputs/demo-backups'
    backup.mkdir(exist_ok=True)
    target = backup / ('demo-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    target.write_text(json.dumps({'summary': summary, 'nx_records': [serialize(r) for r in deleted],
                                  'nx_stocks': [serialize(s) for s in stocks],
                                  'nx_traces': [serialize(t) for t in traces]},
                                 ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    for row in traces:
        db.delete(row)
    db.flush()
    for row in stocks:
        db.delete(row)
    for row in deleted:
        db.delete(row)
    db.flush()
    assert db.scalar(select(func.count(Record.id)).where(Record.demo.is_(True))) == 3
    after = {r.id: serialize(r) for r in db.scalars(select(Record).where(Record.demo.is_(False)))}
    assert before == after, '用户记录发生变化，回滚'
    admin = db.scalar(select(User).where(User.username == 'admin'))
    db.add(Audit(actor_id=admin.id, org=admin.org, action='清理演示数据', detail=summary))
    db.commit()
    print(json.dumps({**summary, 'backup': str(target)}, ensure_ascii=False))
