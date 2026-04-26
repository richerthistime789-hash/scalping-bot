from dotenv import load_dotenv
load_dotenv()
import requests, time
from strategy import (calc_htf_context, calc_liquidity_zone, run_strategy,
                      _find_inducement, _is_imbalance_candle)

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

stats = {'total':0, 'near':0, 'inducement':0, 'imbalance':0, 'signal':0, 'reasons':{}}

for i in range(800, len(m15)-20, 4):
    h4_idx = min(i // 16, len(h4)-1)
    h4_w = h4[max(0, h4_idx-50):h4_idx]
    h1_idx = min(i // 4, len(h1)-1)
    h1_w = h1[max(0, h1_idx-80):h1_idx]
    m15_w = m15[max(0, i-50):i]
    if len(h4_w) < 30 or len(h1_w) < 30: continue
    price = m15[i]['close']
    htf = calc_htf_context(h4_w)
    if htf.direction == "Neutral": continue
    liq = calc_liquidity_zone(h1_w, price, htf.direction)
    if not liq.detected or not liq.near_zone: continue
    stats['near'] += 1
    direction = "BUY" if htf.direction == "Bullish" else "SELL"
    induce_idx, induce_low, induce_high = _find_inducement(m15_w, liq.level, direction)
    if induce_idx is None: continue
    stats['inducement'] += 1
    if not _is_imbalance_candle(m15_w[-2], m15_w[-1], direction): continue
    stats['imbalance'] += 1
    r = run_strategy(h4_w, h1_w, m15_w, price)
    reason = r['reason']
    stats['reasons'][reason] = stats['reasons'].get(reason, 0) + 1
    if r['opportunity'] in ['High','Medium'] and r['m5_signal'].signal != 'WAIT':
        stats['signal'] += 1

print(f"Near zone: {stats['near']}")
print(f"  → Inducement: {stats['inducement']}")
print(f"  → Imbalance: {stats['imbalance']}")
print(f"  → Final Signal: {stats['signal']}")
print(f"\nReasons (top 5):")
for k,v in sorted(stats['reasons'].items(), key=lambda x:-x[1])[:5]:
    print(f"  {v}x {k}")
