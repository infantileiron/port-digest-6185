/** @typedef {{id:number,code:string,station:string,planned_at:string,actual_at:string|null,note:string}} Arrival */
/** @typedef {{id:number,station:string,started_at:string,ended_at:string,note:string,created_by:string,created_at:string,updated_at:string}} Outage */
/** @typedef {{id:number,name:string,station:string,daily_at:string,recipient:string,enabled:boolean,next_run_at:string}} Subscription */
/** @typedef {{report_day:string,station:string,checksum:string,locked:boolean,locked_at:string|null,locked_by:string|null}} Basis */
/** @typedef {{code:string,station:string,planned_at:string,actual_at:string|null,pending:boolean,delay_ms:number,delay_seconds:number,attributed_ms:number,attributed_seconds:number,uncovered_ms:number,uncovered_seconds:number,allocations:{outage_id:number,ms:number,seconds:number}[],reconciled:boolean}} Trip */
/** @typedef {{outage_id:number,station:string,started_at:string,ended_at:string,note:string,allocated_ms:number,allocated_seconds:number,trip_count:number}} OutageEvent */
/** @typedef {{id:number,subscription_id:number,report_day:string,state:string,payload:object,review_note:string}} Receipt */
