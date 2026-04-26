from dotenv import load_dotenv
load_dotenv()
import requests
from strategy import _swing_highs_lows

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

h1 = fetch('1h', 200)
print(f"H1 range: {h1[0]['time']} -> {h1[-1]['time']}")

window = h1[-80:]
print(f"\nLast 80 H1: {window[0]['time']} -> {window[-1]['time']}")
print(f"Price range: ${min(c['low'] for c in window):.2f} - ${max(c['high'] for c in window):.2f}")

highs, lows = _swing_highs_lows(window, n=3)
current = h1[-1]['close']
print(f"\nCurrent price: ${current:.2f}")
print(f"Swing lows  ({len(lows)}): {[round(l['price'],2) for l in lows[-5:]]}")

# กรอง swing lows ที่ต่ำกว่าราคา
candidates = [l for l in lows if l["price"] < current]
print(f"\nSwing lows < current: {len(candidates)}")
if candidates:
    nearest = max(candidates, key=lambda l: l["price"])
    print(f"Nearest swing low: ${nearest['price']:.2f} (dist: ${current-nearest['price']:.2f})")
