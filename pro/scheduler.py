
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .license_manager import check_and_downgrade_expired

def attach_scheduler(application):
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(check_and_downgrade_expired, "interval", hours=1, id="license_expire_check")
    sched.start()
