from sqlalchemy import select,text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Arrival,Subscription,Receipt,Outage,ReportBasis
from src.constants.enums import STATIONS
from src.services.business import dump
from src.services.digest import basis_checksum,relevant_outages
from src.utils.time import now_utc,next_due,aware,SH

def arrival_rows(s):return [dump(r) for r in s.query(Arrival).order_by(Arrival.planned_at,Arrival.id).all()]
def outage_rows(s):return [dump(r) for r in s.query(Outage).order_by(Outage.started_at,Outage.id).all()]

def save_arrival(s,data,i=None):
 r=s.get(Arrival,i) if i else Arrival()
 if not r:raise HTTPException(404,'到发记录不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'班次编号重复')
 return r

def save_outage(s,data,actor,i=None):
 r=s.get(Outage,i) if i else Outage()
 if not r:raise HTTPException(404,'停运登记不存在')
 now=now_utc().isoformat()
 if i is None:r.created_by=actor;r.created_at=now
 for k,v in data.model_dump().items():setattr(r,k,v)
 r.updated_at=now
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'停运登记重复或冲突')
 return r

def save_subscription(s,data,i=None):
 r=s.get(Subscription,i) if i else Subscription()
 if not r:raise HTTPException(404,'订阅不存在')
 values=data.model_dump();first=values.pop('first_due_at')
 for k,v in values.items():setattr(r,k,v)
 # Explicit edit schedules the next future run; an initial override is for a first/catch-up delivery.
 r.next_run_at=first or next_due(r.daily_at,now_utc()).isoformat()
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'订阅名称重复')
 return r

def get_receipt(s,i):
 r=s.get(Receipt,i)
 if not r:raise HTTPException(404,'回执不存在')
 return r

def day_rows(rows,day):
 return [r for r in rows if aware(r['planned_at']).astimezone(SH).date().isoformat()==day]

def claimed_codes(s,report_day,exclude_station=None):
 """已被其他港站锁定依据收录的班次编号；同日改站不再重复归于新站。"""
 codes=set()
 for record in s.scalars(select(ReportBasis).where(ReportBasis.report_day==report_day)).all():
  if record.station==exclude_station:continue
  codes.update(r['code'] for r in record.payload['rows'])
 return codes

def unassigned_rows(s,report_day,bases):
 """当日班次中不在任何已锁定依据内的部分：锁定后新补录或改到未开算站后又被排除的班次。"""
 recorded=set()
 for b in bases:
  recorded.update(r['code'] for r in b['rows'])
 return [r for r in day_rows(arrival_rows(s),report_day) if r['code'] not in recorded]

def build_basis(s,report_day,station):
 if station not in STATIONS:raise HTTPException(400,'依据只能按固定港站锁定')
 claim=claimed_codes(s,report_day,exclude_station=station)
 rows=[r for r in day_rows(arrival_rows(s),report_day) if r['station']==station and r['code'] not in claim]
 rows.sort(key=lambda r:(r['planned_at'],r['code']))
 outages=[o for o in relevant_outages(rows,outage_rows(s)) if o['station']==station]
 outages.sort(key=lambda o:(o['started_at'],o['id']))
 snapshot={'rows':rows,'outages':outages}
 snapshot['checksum']=basis_checksum(rows,outages)
 return snapshot

def _advisory(s,key):
 if s.get_bind().dialect.name=='postgresql':s.execute(text('SELECT pg_advisory_xact_lock(hashtext(:k))'),{'k':key})

def station_basis(s,report_day,station):
 return s.scalars(select(ReportBasis).where(ReportBasis.report_day==report_day,ReportBasis.station==station)).first()

def basis_dict(record):
 return {'report_day':record.report_day,'station':record.station,'created_at':record.created_at,'created_by':record.created_by,'checksum':record.checksum,'rows':record.payload['rows'],'outages':record.payload['outages'],'locked':True}

def ephemeral_basis(s,report_day,station):
 snapshot=build_basis(s,report_day,station)
 return {'report_day':report_day,'station':station,'created_at':None,'created_by':None,'checksum':snapshot['checksum'],'rows':snapshot['rows'],'outages':snapshot['outages'],'locked':False}

def preview_bases(s,report_day):
 """全港试算沿用已锁定各站依据；未开算站按当次补录临时试算，不锁定，随本次发报再锁定。"""
 result=[]
 for station in STATIONS:
  record=station_basis(s,report_day,station)
  result.append(basis_dict(record) if record else ephemeral_basis(s,report_day,station))
 return result

def lock_basis(s,report_day,station,actor):
 """同一业务日同一站只在首次开算时冻结；已存在则原样返回，不因补录或改站而换依据。"""
 if station not in STATIONS:raise HTTPException(400,'依据只能按固定港站锁定')
 _advisory(s,'report-basis:'+report_day)
 existing=station_basis(s,report_day,station)
 if existing:return existing,False
 snapshot=build_basis(s,report_day,station)
 values=dict(report_day=report_day,station=station,created_at=now_utc().isoformat(),created_by=actor,checksum=snapshot['checksum'],payload=snapshot)
 if s.get_bind().dialect.name=='postgresql':
  stmt=pg_insert(ReportBasis).values(**values).on_conflict_do_nothing(index_elements=['report_day','station']).returning(ReportBasis.id)
  new_id=s.execute(stmt).scalar()
  record=station_basis(s,report_day,station)
  return record,new_id is not None
 record=ReportBasis(**values);s.add(record);s.flush();return record,True

def locked_bases(s,report_day,stations=STATIONS):
 records={r.station:r for r in s.scalars(select(ReportBasis).where(ReportBasis.report_day==report_day)).all()}
 return [basis_dict(records[station]) for station in stations if station in records]

def enqueue_receipt(s,sub,day,payload,now):
 values=dict(subscription_id=sub.id,report_day=day,recipient=sub.recipient,created_at=now.isoformat(),state='delivered',payload=payload)
 if s.get_bind().dialect.name=='postgresql':
  stmt=pg_insert(Receipt).values(**values).on_conflict_do_nothing(index_elements=['subscription_id','report_day']).returning(Receipt.id)
  new_id=s.execute(stmt).scalar()
  if new_id is not None:return new_id,True
  existing=s.query(Receipt).filter_by(subscription_id=sub.id,report_day=day).one()
  return existing.id,False
 existing=s.query(Receipt).filter_by(subscription_id=sub.id,report_day=day).first()
 if existing:return existing.id,False
 record=Receipt(**values);s.add(record);s.flush();return record.id,True
