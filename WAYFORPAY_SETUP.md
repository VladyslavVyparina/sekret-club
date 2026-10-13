# What WayForPay needs

## 1. Server `.env`

```env
BASE_URL=https://your-domain.com
WAYFORPAY_MERCHANT=your_merchant_login
WAYFORPAY_SECRET=your_wayforpay_secret
WAYFORPAY_DOMAIN=your-domain.com
```

`BASE_URL` is the host where `run_web.py` is reachable. Without it, checkout cannot build the return URL.

For a closed group you can leave `CLUB_GROUP_LINK` empty. After payment the user is told that an admin will add them.

## 2. WayForPay cabinet

- Service URL (callback): `https://YOUR_HOST/webhook/wayforpay`
- Return URL: empty, or `https://t.me/your_bot`

## 3. Processes

Both have to be running:

```bash
python3 run_bot.py
python3 run_web.py
```

## 4. Behavior

- Cancelling a subscription calls WayForPay REMOVE and stops the recurring charge.
- If it is not cancelled, WayForPay charges every month.
- A reminder goes out three days before the subscription ends.
- A failed charge is retried on day 0, 2, 4, 7, 11, and 14.
