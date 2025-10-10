
# Render Deploy Notes (Python 3.12)

- `runtime.txt` pins Python runtime to 3.12.5 on Render (avoids PTB + Python 3.13 issue).
- Recommended Build Command:
```
pip uninstall -y telegram || true
pip install --no-cache-dir -r requirements.txt
```
- Start Command:
```
python main.py
```
