from dotenv import load_dotenv
load_dotenv()
import requests, time
from strategy import calc_htf_context, calc_liquidity_zone, run_strategy

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

print(f"H4: {len(h4)} | H1: {len(h1)} | M15: {len(m15)}")

results = {}
near_zone_count = 0
non_skip = 0

# เริ่ม i ที่ 800 ขึ้นไปเพื่อให้ h4 window พอ
for i in range(800, len(m15)-20, 8):
    h4_idx = min(i // 16, len(h4)-1)
    h4_w = h4[max(0, h4_idx-50):h4_idx]
    h1_idx = min(i // 4, len(h1)-1)
    h1_w = h1[max(0, h1_idx-80):h1_idx]
    m15_w = m15[max(0, i-50):i]
    if len(h4_w) < 30 or len(h1_w) < 30: continue
    price = m15[i]['close']
    htf = calc_htf_context(h4_w)
    liq = calc_liquidity_zone(h1_w, price, htf.direction)
    key = f"H4={htf.direction} liq_det={liq.detected} near={liq.near_zone}"
    results[key] = results.get(key, 0) + 1
    if liq.near_zone:
        near_zone_count += 1
        r = run_strategy(h4_w, h1_w, m15_w, price)
        if r['opportunity'] != "Skip":
            non_skip += 1
            if non_skip <= 3:
                print(f"  Non-skip: {r['opportunity']} | {r['reason']}")

print("\n=== Breakdown ===")
for k, v in sorted(results.items(), key=lambda x: -x[1])[:10]:
    print(f"  {v:3}x {k}")
print(f"\nNear zone: {near_zone_count}")
print(f"Non-skip: {non_skip}")
