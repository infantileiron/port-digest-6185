import random
from datetime import datetime,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,Arrival,Outage,Subscription,Receipt
from src.utils.security import hash_password
from src.utils.time import now_utc,SH,next_due

# 末六班刻意排在 23:30–23:59 并用固定延误，跨午夜到达，用来演练归档与重叠停运归因。
LATE=[((0,23,30),35),((0,23,36),30),((0,23,42),40),((0,23,48),25),((0,23,54),45),((0,23,59),20)]
# (港站, 起(天,时,分), 止(天,时,分), 说明)；第 2 天 00:xx 用 day+1 表示，跨午夜不拆单。
OUTAGES=[('北站',(0,23,40),(1,0,0),'夜班道岔检修'),
         ('北站',(0,23,55),(1,0,15),'北站信号复归，与道岔检修重叠'),
         ('南站',(0,23,50),(1,0,20),'南站接触网检修'),
         ('东港',(1,0,10),(1,0,30),'东港泊位断电')]

def seed():
 Base.metadata.create_all(engine);rng=random.Random(3113);now=now_utc();day=now.astimezone(SH).date()-timedelta(days=1)
 midnight=datetime.combine(day,datetime.min.time(),tzinfo=SH)
 def at(spec):
  d,h,m=spec
  return (midnight+timedelta(days=d,hours=h,minutes=m)).astimezone(now.tzinfo).isoformat()
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for i in range(150):
   code=f'LG-{i+1:03}'
   tail=i-(150-len(LATE))
   if tail>=0:
    planned_spec,delay=LATE[tail]
    planned=midnight+timedelta(days=planned_spec[0],hours=planned_spec[1],minutes=planned_spec[2])
   else:
    planned=midnight+timedelta(minutes=i*8)
    delay=rng.choice([-5,0,0,3,5,8,12,18,25,40])
   actual=planned+timedelta(minutes=delay)
   if not s.query(Arrival).filter_by(code=code).first():s.add(Arrival(code=code,station=('北站','南站','东港')[i%3],planned_at=planned.astimezone(now.tzinfo).isoformat(),actual_at=None if i%29==0 and tail<0 else actual.astimezone(now.tzinfo).isoformat(),note='临港联运昨日交接班导出'))
  if not s.query(Outage).count():
   for station,start,end,note in OUTAGES:
    s.add(Outage(station=station,started_at=at(start),ended_at=at(end),note=note,created_by='seed',created_at=now.isoformat(),updated_at=now.isoformat()))
  for station in ('北站','南站','东港'):
   name=station+'值班晨报'
   if not s.query(Subscription).filter_by(name=name).first():s.add(Subscription(name=name,station=station,daily_at='08:30',recipient=station+'值班室',enabled=False,next_run_at=next_due('08:30',now).isoformat()))
  s.commit();print({'users':s.query(User).count(),'arrivals':s.query(Arrival).count(),'outages':s.query(Outage).count(),'subscriptions':s.query(Subscription).count(),'receipts':s.query(Receipt).count()})
if __name__=='__main__':seed()
