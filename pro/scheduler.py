# pro/scheduler.py
from datetime import datetime, timedelta
from telegram.ext import Application, JobQueue

def attach_scheduler(app: Application):
    """
    Gắn các job định kỳ vào PTB JobQueue.
    Yêu cầu đã cài python-telegram-bot[job-queue] (đã thêm trong requirements.txt).
    """
    jq: JobQueue = app.job_queue

    # ví dụ: job dọn rác / gia hạn pro hết hạn
    async def _tick_expire_pro(context):
        # TODO: đặt logic kiểm tra hạn dùng PRO/Trial ở đây
        # print("tick expire pro", datetime.utcnow())
        pass

    # mỗi 5 phút chạy 1 lần
    jq.run_repeating(_tick_expire_pro, interval=300, first=10)

    # có thể thêm các job khác tương tự…
