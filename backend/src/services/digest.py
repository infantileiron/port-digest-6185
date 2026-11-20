import hashlib,json
from datetime import datetime,timezone
from src.utils.time import aware
VERSION='planned-day-overlap-even-v2'
EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)
METHOD=('按计划到发时间的上海自然日归档；延误=max(0,实际−计划)，提前记0；'
        '延误区间与停运相交的时段按当时覆盖事件数均摊，未被停运覆盖的时段单列；'
        '按整毫秒分摊，每班延误秒数=停运归因秒数+未覆盖秒数，可与事件合计对账。'
        'P50/P95为已到发样本的(n−1)p线性插值(分钟)；无已到发样本为null，不伪造0。')

def epoch_ms(value):
 d=aware(value)-EPOCH
 return d.days*86400000+d.seconds*1000+d.microseconds//1000
def seconds(ms):return round(ms/1000,3)
def quantile(values,p):
 if not values:return None
 values=sorted(values);position=(len(values)-1)*p;lower=int(position);upper=min(lower+1,len(values)-1)
 return values[lower]+(values[upper]-values[lower])*(position-lower)
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def basis_checksum(rows,outages):
 return hashlib.sha256(canonical({'rows':rows,'outages':outages}).encode()).hexdigest()

def relevant_outages(rows,outages):
 """只冻结与某班延误时段真正相交的停运；跨午夜按绝对时间判断。"""
 windows=[(epoch_ms(r['planned_at']),epoch_ms(r['actual_at'])) for r in rows if r['actual_at'] and epoch_ms(r['actual_at'])>epoch_ms(r['planned_at'])]
 return [o for o in outages if any(epoch_ms(o['started_at'])<end and epoch_ms(o['ended_at'])>start for start,end in windows)]

def attribute_trip(row,outages):
 planned=epoch_ms(row['planned_at'])
 actual=epoch_ms(row['actual_at']) if row['actual_at'] else None
 delay_ms=max(0,actual-planned) if actual is not None else 0
 allocations={}
 uncovered=0
 if delay_ms:
  relevant=[o for o in outages if epoch_ms(o['started_at'])<actual and epoch_ms(o['ended_at'])>planned]
  cuts={planned,actual}
  for o in relevant:
   cuts.add(min(actual,max(planned,epoch_ms(o['started_at']))))
   cuts.add(min(actual,max(planned,epoch_ms(o['ended_at']))))
  edges=sorted(cuts)
  for left,right in zip(edges,edges[1:]):
   length=right-left
   if length<=0:continue
   covering=sorted((o for o in relevant if epoch_ms(o['started_at'])<=left and epoch_ms(o['ended_at'])>=right),key=lambda o:o['id'])
   if not covering:uncovered+=length;continue
   share,remainder=divmod(length,len(covering))
   for i,o in enumerate(covering):allocations[o['id']]=allocations.get(o['id'],0)+share+(1 if i<remainder else 0)
 attributed=sum(allocations.values())
 return {'code':row['code'],'station':row['station'],'planned_at':row['planned_at'],'actual_at':row['actual_at'],'pending':row['actual_at'] is None,'delay_ms':delay_ms,'delay_seconds':seconds(delay_ms),'attributed_ms':attributed,'attributed_seconds':seconds(attributed),'uncovered_ms':uncovered,'uncovered_seconds':seconds(uncovered),'allocations':[{'outage_id':k,'ms':v,'seconds':seconds(v)} for k,v in sorted(allocations.items())],'reconciled':delay_ms==attributed+uncovered}

def _events(trips,by_id):
 totals={}
 for t in trips:
  for a in t['allocations']:
   item=totals.setdefault(a['outage_id'],{'allocated_ms':0,'trip_count':0})
   item['allocated_ms']+=a['ms'];item['trip_count']+=1
 events=[]
 for oid,item in totals.items():
  o=by_id[oid]
  events.append({'outage_id':oid,'station':o['station'],'started_at':o['started_at'],'ended_at':o['ended_at'],'note':o.get('note',''),'allocated_ms':item['allocated_ms'],'allocated_seconds':seconds(item['allocated_ms']),'trip_count':item['trip_count']})
 events.sort(key=lambda e:(e['started_at'],e['outage_id']))
 return events

def _summary(rows,trips,events,outages):
 completed=[t for t in trips if not t['pending']]
 delays=[t['delay_ms']/60000 for t in completed]
 late=sum(d>0 for d in delays)
 delay_ms=sum(t['delay_ms'] for t in trips)
 attributed_ms=sum(t['attributed_ms'] for t in trips)
 uncovered_ms=sum(t['uncovered_ms'] for t in trips)
 event_ms=sum(e['allocated_ms'] for e in events)
 return {'scheduled':len(rows),'completed':len(completed),'pending':len(rows)-len(completed),'late':late,'late_rate':late/len(completed) if completed else None,'p50':quantile(delays,.5),'p95':quantile(delays,.95),'mean_delay':sum(delays)/len(delays) if delays else None,'max_delay':max(delays) if delays else None,'delay_ms':delay_ms,'delay_seconds':seconds(delay_ms),'attributed_ms':attributed_ms,'attributed_seconds':seconds(attributed_ms),'uncovered_ms':uncovered_ms,'uncovered_seconds':seconds(uncovered_ms),'event_ms':event_ms,'event_seconds':seconds(event_ms),'reconciled':delay_ms==attributed_ms+uncovered_ms and attributed_ms==event_ms,'outage_count':len(outages)}

def metrics(report_day,station,basis,unassigned=None):
 rows,outages=basis['rows'],basis['outages']
 trips=[attribute_trip(r,outages) for r in rows]
 events=_events(trips,{o['id']:o for o in outages})
 summary=_summary(rows,trips,events,outages)
 return dict(report_day=report_day,timezone='Asia/Shanghai',station=station,**summary,unassigned=unassigned or [],trips=trips,events=events,rows=rows,outages=outages,checksum=basis['checksum'],version=VERSION,method=METHOD,basis={'kind':'station','station':station,'checksum':basis['checksum'],'rows':len(rows),'outages':len(outages),'locked':basis.get('locked',True),'locked_at':basis.get('created_at'),'locked_by':basis.get('created_by')})

def aggregate(report_day,bases,unassigned=None):
 station_metrics=[metrics(report_day,b['station'],b) for b in bases]
 trips=[t for m in station_metrics for t in m['trips']]
 rows=[r for m in station_metrics for r in m['rows']]
 unique={}
 for b in bases:
  for o in b['outages']:unique[o['id']]=o
 outages=[unique[k] for k in sorted(unique)]
 events=_events(trips,{o['id']:o for o in outages})
 summary=_summary(rows,trips,events,outages)
 checksum=hashlib.sha256(canonical([{'station':b['station'],'checksum':b['checksum']} for b in bases]).encode()).hexdigest()
 stations=[{'station':m['station'],'checksum':m['checksum'],'scheduled':m['scheduled'],'completed':m['completed'],'pending':m['pending'],'p50':m['p50'],'p95':m['p95'],'delay_seconds':m['delay_seconds'],'attributed_seconds':m['attributed_seconds'],'uncovered_seconds':m['uncovered_seconds'],'reconciled':m['reconciled'],'basis':m['basis']} for m in station_metrics]
 return dict(report_day=report_day,timezone='Asia/Shanghai',station='全部',**summary,unassigned=unassigned or [],trips=trips,events=events,rows=rows,outages=outages,checksum=checksum,version=VERSION,method=METHOD,stations=stations,basis={'kind':'all-stations','checksum':checksum,'stations':[{'station':b['station'],'checksum':b['checksum'],'locked':b.get('locked',True),'locked_at':b.get('created_at'),'locked_by':b.get('created_by')} for b in bases]})
