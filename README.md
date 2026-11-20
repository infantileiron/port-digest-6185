# 临港 · 港站晨报定时分发

把昨日计划到发、延误分位数与交接班晨报串起来，由真实worker到点生成站内收件箱回执，保留冻结来源。

## 场景与工作流

临港联运运营北站、南站和东港三个港站，每天约150条班次记录。现行工作流是值班员导出 `临港到发_20261114.xlsx`，分析员按日期筛选后手算延误，负责人再把表格转发给下一班。痛点是跨午夜班次归错日、未到发被当准点、重复转发后分不清同一口径。上游为港站计划/实际到发记录；本项目替代日界归档、晨报试算和定时分发；下游为站内值班室交接班。

四个业务实体：Arrival到发记录、Outage停运登记、Subscription晨报订阅、Receipt分发回执；ReportBasis分站依据快照是发报时冻结的中间依据，另有用户和审计。四页：到发台账（含停运登记）、晨报预览、订阅计划、分发回执。回执支持值班复核与下载，原始记录修订不改变已分发晨报。

|角色|权限|典型动作|
|---|---|---|
|admin|全部；独占订阅配置/值班复核/审计|设定08:30晨报并核对回执|
|analyst|到发与停运录入/修订、晨报试算、读取计划回执、导出|补录跨午夜班次、登记停运|
|viewer|业务只读与回执导出|下载冻结晨报；后端拒绝写入/计算|

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18212](http://localhost:18212)，API [localhost:19212/docs](http://localhost:19212/docs)，PostgreSQL映射17712。账号 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。种子为3账号、150条昨日计划到发（末六班排在23:30–23:59并带固定延误）、4条跨午夜停运、3条暂停订阅；不会自动对外发送。自然编号幂等，重复运行不覆盖人工修订；种子日期为首次启动的昨日，后续日需业务录入新记录。

## 一日业务剧本

1. 08:00 viewer 查看到发台账，核对未到发为空；同时查看停运登记（北站道岔检修跨午夜、北站信号复归与之重叠、南站接触网检修、东港泊位断电）。
2. 08:05 analyst 录入 `LG-151`，北站，计划2026-11-14 23:55，实际2026-11-15 00:05，交接说明为跨午夜；如需补登停运，在“登记停运”填港站与起止（跨午夜一条即可）。
3. 08:10 在晨报预览选择2026-11-14和北站：该班次仍归14日、延误10分钟；页面给出延误/停运归因/未覆盖三列秒数，且逐班对账一致。此次开算即锁定北站当日依据。
4. 08:12 继续补录北站班次后重算，北站仍沿用08:10锁定的依据；切换到南站试算，则南站以当前补录首次锁定。
5. 08:15 admin 创建“北站08:30值班晨报”，站内收件箱“北站值班室”，每日08:30，启用。
6. 演示时可把“首次到点”设为未来10秒；不需要任何手动发送按钮。
7. 08:30 worker每秒检查到点订阅；单站订阅沿用该站已锁定依据，全港订阅沿用已锁定各站、其余站随本次发报锁定，然后写入回执。
8. 08:31 刷新分发回执，核对P50/P95、完成/未到发人数、延误/归因/未覆盖秒数与来源checksum；全港回执另列每站依据checksum与锁定状态。
9. 08:35 admin 写入“跨日班次已核对”复核意见；viewer下载 `port-digest-<业务日>-<回执id>.json`。

## 计算与调度口径

**归档**按计划到发时间转Asia/Shanghai后的自然日，而非实际到达日。后端时间输入必须有偏移（如+08:00），统一保存UTC；前端datetime-local明确按上海解释。实际可空，表示未到发。时间差超过3天拒绝，提示核对。

**延误**=max(0,实际−计划)，内部按毫秒、展示按秒，提前到达记0。已到发才进入延误率与分位数分母；未到发单独计数。P50/P95仍以分钟按排序后位置(n−1)p线性插值；没有已到发样本时分位数、均值和延误率为null，页面显示“未定义”。输出带选中来源、口径版本与SHA256 checksum。

**停运归因**只在某班延误区间内做时间切片：与停运相交的每个切片按当时覆盖的事件数均摊（按整毫秒、余数按事件id顺序分配），未被任何停运覆盖的切片单列。于是每班 `延误毫秒 = 停运归因毫秒 + 未覆盖毫秒`，且各事件归因合计等于各班归因合计，页面对账列显示“一致/不平”。停运按港站登记、按绝对时间判断，跨午夜一条即可；只有与该业务日该站班次延误时段真正相交的停运才进入依据快照，不会把整段停运时长直接计成延误。停运起止必须带时区、结束晚于开始、单条不超过7天。

**依据锁定**以“业务日+港站”为键：某站首次开算（单站晨报试算或到点发报）时读入该站当日班次与相交停运，写入ReportBasis快照并计算checksum；此后该站补录、改站、修订停运都不再改变已锁定依据。未开算的站继续纳入补录，待其首次开算时再锁定。班次若在锁定后被改到别的站，同一业务日仍归原站依据，新站依据不再收录该编号（`report_bases` 唯一约束 `(report_day, station)`；PostgreSQL 用按日 advisory lock + `ON CONFLICT DO NOTHING` 串行化并发锁定）。全港晨报/试算沿用各站已锁定依据，未锁定站在全港试算中仅按当前数据临时展示并标记“未锁定”，随正式发报才锁定。因此同一业务日、同一套分站依据可被多个并发回执共用，checksum一致。锁定后才补录、或从已锁定站改到尚未开算站的班次，不再进入任何已锁依据，晨报会把它们单列为“未纳入依据的班次”，不静默丢失也不倒改口径。

**到点调度**由worker每秒扫描UTC next_run_at，Redis锁串行化扫描，数据库用行锁和唯一约束 `(subscription_id, report_day)` 防止同订阅同报告日重复入箱。发报顺序是先按站锁定/读取依据并提交，再入箱回执并提交：计算或进程在入箱前中断，重跑会复用已提交的依据、不会换口径；入箱用 `ON CONFLICT DO NOTHING ... RETURNING` 判定是否真正新建，重试不重复入箱，也不会重复写审计或产物。首次时间可设未来数秒进行真实调度验证；以后按Asia/Shanghai每日HH:MM安排。到点或服务中断恢复时只生成“执行时刻的最新昨日”一份，不补历史天；同日再次到点只推进next_run_at，不新增回执。暂停订阅不执行。修订订阅如果未填写首次时间，会重新安排下一个每日时刻；恢复暂停也按此规则。

晨报“送达”表示已提交站内数据库收件箱，不是SMTP邮件。回执保存冻结payload，DB提交后附加写共享产物卷；附加文件失败不影响DB回执和导出，重试会对已有回执补写缺失产物而不重复入箱。值班复核仅管理员可做，一次复核不可覆盖，且不改变payload。支持单worker；唯一约束与锁防重复，但不声称对外消息的exactly-once。

## 工程、环境变量和开发

Python3.11/FastAPI/SQLAlchemy/PyJWT、原生ES modules/CSS、Nginx、PostgreSQL16、Redis7。恰好frontend/backend/worker/db/redis五服务，各有健康检查；backend等db/redis、worker还等backend、frontend等backend。Redis实际提供调度锁；worker心跳 `/tmp/heartbeat`，DB/Redis/产物分别命名卷。Nginx `/api/` 去前缀代理后端根路由。

`.env.example`列出COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。显式子网10.253.113.0/24规避当前机默认地址池耗尽，可按环境调整。演示凭据应在正式部署替换。清理本项目用 `docker compose down -v --remove-orphans`。

本地开发：启动db/redis，backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，再运行 `uvicorn src.main:app --reload` 和 `python -m src.worker`；前端仍建议用Nginx同源代理。后端目录src按routes/controllers/services/models/schemas/middlewares/config/utils/constants分工；前端src按api/stores/pages/components/hooks/utils/constants/types/router分工。ORM首次建表，migrations保留实际初始DDL（002为停运与依据表），无在线迁移执行器。

枚举：后端 `src/constants/enums.py`、`src/schemas/business.py` 与前端 `src/constants/enums.js` 定义ROLES、STATIONS、RECEIPT_STATES；TIMEZONE固定Asia/Shanghai。共用表格、表单、状态标签、晨报摘要组件；表单hooks、HTML转义和日期工具；请求ID/安全响应头两个中间件，业务审计与全局错误恢复。测试与截图在 `../../test-artifacts/gb-3113/`，不放源码内。

范围：到发与停运均逐条录入/完整修订，无CSV导入、删除或分页；只有三个固定港站与上海时区。停运按站登记，不建“部分影响”比例；归因是时间覆盖均摊，不推断因果关系。站内收件箱按名称记录，当前所有登录角色可读业务回执，无多租户邮箱隔离；不连接邮件、短信或外部IM。Google Fonts离线时字体回退。许可证MIT，见LICENSE。
