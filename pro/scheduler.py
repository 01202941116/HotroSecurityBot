
from apscheduler.schedulers.asyncio import AsyncIOScheduler

def attach_scheduler(application):
    sched = AsyncIOScheduler(timezone="UTC")
    sched.start()
