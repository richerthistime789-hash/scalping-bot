from dotenv import load_dotenv
load_dotenv()
import requests, time
from zoneinfo import ZoneInfo
from datetime import datetime
from strategy import calc_h1_bias, calc_m15_zone

TWELVE_KEY = '180a281ad6f744ef9f41de0241092787'
BKK = ZoneInfo("Asia/Bangkok")

def fetch(interval, size):
    r = requests.get('https://api.twelvedata.com/time_series', params={
        'symbol': 'XAU/USD', 'interval': interval,
        'outputsize': size, 'apikey': TWELVE_KEY,
        'format': 'JSON', 'order': 'ASC'
    }, timeout=30)
    return [{'time': v['datetime'], 'open': float(v['open']),
             'high': float(v['high']), 'low': float(v['low']),
             'close': float(v['close'])} for v in r.json().get('values', [])]

h1  = fetch('1h', 200)
time.sleep(1)
m15 = fetch('15min', 500)

skip_reasons = {}
for i in range(50, 300, 2):
    if i >= len(m15) - 20: break
    m15_w  = m15[max(0,i-50):i]
    h1_idx = min(i//4, len(h1)-1)
    h1_w   = h1[max(0,h1_idx-50):h1_idx]
    price  = m15[i]['close']
    if len(h1_w) < 20 or len(m15_w) < 20: continue
    try:
        dt = datetime.fromisoformat(m15[i]['time']).replace(tzinfo=ZoneInfo("UTC")).astimezone(BKK)
        if dt.weekday() in [5,6]: continue
    except:
        continue
    h1b  = calc_h1_bias(h1_w)
    m15z = calc_m15_zone(m15_w, price)
    key  = f"H1={h1b.direction} zone={m15z.in_zone} type={m15z.zone_type}"
    skip_reasons[key] = skip_reasons.get(key, 0) + 1

print("=== Breakdown ===")
for k,v in sorted(skip_reasons.items(), key=lambda x: -x[1])[:8]:
    print(f"  {v:3}x {k}")
