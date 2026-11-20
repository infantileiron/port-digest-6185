import json,logging,os
from pathlib import Path
from sqlalchemy import select
from src.constants.enums import STATIONS
from src.models.entities import Subscription,Receipt,Audit,ReportBasis
from src.services.repository import lock_basis,basis_dict,enqueue_receipt,_advisory,unassigned_rows
from src.services.digest import metrics,aggregate
from src.utils.time import aware,next_due,yesterday

def ensure_bases(s,report_day,stations,actor):
 """先把本次发报要用的分站依据逐站锁定并提交；中断重跑沿用同一份，不因补录改口径。
 每站的锁定在 lock_basis 内持有按日 advisory 锁并单事务提交，因此并发发报读到的相互声明也是串行的。"""
 locked=[]
 for station in stations:
  record,created=lock_basis(s,report_day,station,actor)
  s.commit()
  if created:locked.append(station)
 return locked

def collect_bases(s,report_day,stations):
 records={r.station:r for r in s.scalars(select(ReportBasis).where(ReportBasis.report_day==report_day)).all()}
 return [basis_dict(records[station]) for station in stations if station in records]

def build_payload(s,sub,day,actor):
 stations=list(STATIONS) if sub.station=='全部' else [sub.station]
 locked=ensure_bases(s,day,stations,actor)
 bases=collect_bases(s,day,stations)
 loose=unassigned_rows(s,day,bases)
 if sub.station=='全部':payload=aggregate(day,bases,loose)
 else:payload=metrics(day,sub.station,bases[0],[r for r in loose if r['station']==sub.station])
 return payload,locked

def run_due(s,now,actor='scheduler'):
 sent=[]
 artifacts=[]
 subscriptions=s.scalars(select(Subscription).where(Subscription.enabled.is_(True),Subscription.next_run_at<=now.isoformat()).with_for_update(skip_locked=True)).all()
 for sub in subscriptions:
  if aware(sub.next_run_at)>now:continue
  day=yesterday(now)
  payload,locked=build_payload(s,sub,day,actor)
  _advisory(s,'receipt:'+str(sub.id)+':'+day)
  receipt_id,created=enqueue_receipt(s,sub,day,payload,now)
  artifacts.append(receipt_id)
  if created:
   sent.append(receipt_id)
   s.add(Audit(actor=actor,action='到点分发订阅 '+str(sub.id)+' / '+day+' / 锁定依据 '+','.join(locked),created=now.isoformat()))
  sub.last_run_at=now.isoformat();sub.next_run_at=next_due(sub.daily_at,now).isoformat()
  s.commit()
 # 入箱已提交；产物写失败只记日志。重试时对已有回执补写缺失产物，不重复入箱。
 for i in artifacts:
  try:
   receipt=s.get(Receipt,i);target=Path(os.environ.get('ARTIFACT_DIR','/artifacts'))
   target_file=target/(str(i)+'.json')
   if receipt and not target_file.exists():
    target.mkdir(parents=True,exist_ok=True);target_file.write_text(json.dumps(receipt.payload,ensure_ascii=False,indent=2))
  except Exception:logging.exception('DB inbox delivered; optional artifact write failed')
 return sent
