from dotenv import load_dotenv
load_dotenv()
import requests, time
from strategy import run_strategy, calc_daily_context, calc_m15_zone

TWELVE_KEY = '180a281ad6f744ef9f41de0241092787'

def fetch(interval, size):
    r = requests.get('https://api.twelvedata.com/time_series', params={
        'symbol': 'XAU/USD', 'interval': interval,
        'outputsize': size, 'apikey': TWELVE_KEY,
        'format': 'JSON', 'order': 'ASC'
    }, timeout=30)
    return [{'time': v['datetime'], 'open': float(v['open']),
             'high': float(v['high']), 'low': float(v['low']),
             'close': float(v['close'])} for v in r.json().get('values', [])]

h1_raw = fetch('1h', 1000); time.sleep(1)
m5     = fetch('5min', 1000)

h2 = []
for i in range(0, len(h1_raw)-1, 2):
    c1, c2 = h1_raw[i], h1_raw[i+1]
    h2.append({'time': c1['time'], 'open': c1['open'],
               'high': max(c1['high'], c2['high']),
               'low':  min(c1['low'],  c2['low']),
               'close': c2['close']})

print(f"H2: {len(h2)} | M5: {len(m5)}")

# ใช้ m5 candle ล่าสุด — h2 idx จะเป็น len(h2)-1
i = len(m5) - 50
h2_idx = min(i // 24, len(h2) - 1)
h2_w = h2[max(0, h2_idx-50):h2_idx]
m5_w = m5[max(0, i-60):i]
price = m5[i]['close']

print(f"\ni={i}, h2_idx={h2_idx}, h2_w={len(h2_w)}, m5_w={len(m5_w)}, price={price}")

ctx = calc_daily_context(h2_w)
print(f"H2 Context: {ctx.direction} | {ctx.reason}")

zone = calc_m15_zone(m5_w, price, ctx.direction)
print(f"M5 Zone: in_zone={zone.in_zone} | type={zone.zone_type} | {zone.reason}")

r = run_strategy(h2_w, m5_w, m5_w, price)
print(f"Result: {r['opportunity']} | {r['reason']}")

# ทดสอบ scan หลายๆจุด
results = {}
for i in range(100, len(m5)-50, 10):
    h2_idx = min(i // 24, len(h2) - 1)
    h2_w = h2[max(0, h2_idx-50):h2_idx]
    m5_w = m5[max(0, i-60):i]
    if len(h2_w) < 30 or len(m5_w) < 60: continue
    price = m5[i]['close']
    try:
        r = run_strategy(h2_w, m5_w, m5_w, price)
        results[r['opportunity']] = results.get(r['opportunity'], 0) + 1
    except: pass

print(f"\nFull scan: {results}")
