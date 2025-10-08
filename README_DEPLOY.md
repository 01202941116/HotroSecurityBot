## Deployment tips
- For quick deployment, use Render (web service) or Railway. On Render choose "Deploy a Web Service" and set a start command like:
  `python main.py`
- If using webhook, you must implement a Flask/FastAPI wrapper and set webhook to your service URL.
- Make sure to set environment variables (BOT_TOKEN, ADMIN_IDS) in the host service settings.
