from datetime import datetime,timezone
from .domain import TaskStatus
from .service import OperationsService

def run_task_once(service:OperationsService,handler,task_run_id,owner):
    claimed=service.acquire(task_run_id,owner,datetime.now(timezone.utc))
    try:result=dict(handler.execute(claimed))
    except Exception as error:return service.fail(claimed.task_run_id,owner,claimed.fencing_token,type(error).__name__,datetime.now(timezone.utc))
    return service.complete(claimed.task_run_id,owner,claimed.fencing_token,result,datetime.now(timezone.utc))

