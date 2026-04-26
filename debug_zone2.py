from dotenv import load_dotenv
load_dotenv()
import requests, time
from strategy import calc_htf_context, _swing_highs_lows, SWING_N

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

h4  = fetch('4h', 1500); time.sleep(1)
h1  = fetch('1h', 5000); time.sleep(1)
m15 = fetch('15min', 5000)

# ตัวอย่างที่ index 800
i = 800
h1_idx = min(i // 4, len(h1)-1)
h1_w = h1[max(0, h1_idx-80):h1_idx]
price = m15[i]['close']

print(f"i={i}, h1_idx={h1_idx}, h1_w len={len(h1_w)}")
print(f"H1 window: {h1_w[0]['time']} -> {h1_w[-1]['time']}")
print(f"Current price (M15): {price}")
print(f"H1 last close: {h1_w[-1]['close']}")
print(f"Time diff: M15[{i}]={m15[i]['time']} vs H1[{h1_idx-1}]={h1[h1_idx-1]['time']}")

highs, lows = _swing_highs_lows(h1_w, n=SWING_N)
print(f"\nSwing lows in this window:")
for l in lows[-10:]:
    print(f"  {l['price']:.2f} (idx {l['index']})")
