# Deploy Render (Free)

**Build Command**

**Start Command**

**Env Vars**
- `BOT_TOKEN` = <token của BotFather>
- `OWNER_ID` = <Telegram user id của bạn> (số)
- (tuỳ chọn) `CONTACT_USERNAME` = <username hỗ trợ>

**Ghi chú**
- Free instance có health check → đã có Flask keepalive bind `PORT` do Render cấp.
- Nếu bị timeout health check, kiểm tra log phải thấy `Running on 0.0.0.0:<PORT>` (không phải 10000 cố định).
