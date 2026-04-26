from dotenv import load_dotenv
load_dotenv()
import requests, time
from strategy import calc_htf_context, calc_liquidity_zone

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

distances = []
for i in range(800, len(m15)-20, 8):
    h4_idx = min(i // 16, len(h4)-1)
    h4_w = h4[max(0, h4_idx-50):h4_idx]
    h1_idx = min(i // 4, len(h1)-1)
    h1_w = h1[max(0, h1_idx-80):h1_idx]
    if len(h4_w) < 30 or len(h1_w) < 30: continue
    price = m15[i]['close']
    htf = calc_htf_context(h4_w)
    if htf.direction == "Neutral": continue
    liq = calc_liquidity_zone(h1_w, price, htf.direction)
    if liq.detected and liq.distance_pips is not None:
        distances.append(abs(liq.distance_pips))

print(f"Total distances: {len(distances)}")
if distances:
    distances.sort()
    print(f"Min: {distances[0]:.0f}p")
    print(f"Median: {distances[len(distances)//2]:.0f}p")
    print(f"P90: {distances[int(len(distances)*0.9)]:.0f}p")
    print(f"Max: {distances[-1]:.0f}p")
    # นับว่ามีกี่ตัวที่ใกล้
    near_50  = sum(1 for d in distances if d <= 50)
    near_100 = sum(1 for d in distances if d <= 100)
    near_200 = sum(1 for d in distances if d <= 200)
    print(f"\n<=50p:  {near_50}")
    print(f"<=100p: {near_100}")
    print(f"<=200p: {near_200}")
