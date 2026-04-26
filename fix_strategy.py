# รันไฟล์นี้เพื่อ patch strategy.py
import re

with open('strategy.py', 'r') as f:
    content = f.read()

# แก้ _is_engulfing — ลด threshold ให้ง่ายขึ้น
old_engulfing = '''def _is_engulfing(c1, c2, direction):
    o1,c1v = c1.get("open",0), c1.get("close",0)
    o2,c2v = c2.get("open",0), c2.get("close",0)
    if direction == "BUY":
        return (c1v < o1) and (c2v > o2) and (c2v > o1) and (o2 < c1v)
    return (c1v > o1) and (c2v < o2) and (c2v < o1) and (o2 > c1v)'''

new_engulfing = '''def _is_engulfing(c1, c2, direction):
    o1,c1v = c1.get("open",0), c1.get("close",0)
    o2,c2v = c2.get("open",0), c2.get("close",0)
    body1 = abs(c1v - o1)
    body2 = abs(c2v - o2)
    if body1 < 0.05 or body2 < 0.05: return False  # candle เล็กเกิน
    if direction == "BUY":
        # c1 bearish, c2 bullish และ body ใหญ่กว่า c1
        return (c1v < o1) and (c2v > o2) and (body2 >= body1 * 0.8)
    else:
        # c1 bullish, c2 bearish และ body ใหญ่กว่า c1
        return (c1v > o1) and (c2v < o2) and (body2 >= body1 * 0.8)'''

# แก้ _is_pin_bar — ลด ratio threshold
old_pinbar = '''def _is_pin_bar(candle, direction):
    o,c,h,l = candle.get("open",0),candle.get("close",0),candle.get("high",0),candle.get("low",0)
    body = abs(c-o); rng = h-l
    if rng == 0: return False
    if direction == "BUY":
        return (min(o,c)-l) > body*2 and body/rng < 0.4
    return (h-max(o,c)) > body*2 and body/rng < 0.4'''

new_pinbar = '''def _is_pin_bar(candle, direction):
    o,c,h,l = candle.get("open",0),candle.get("close",0),candle.get("high",0),candle.get("low",0)
    body = abs(c-o); rng = h-l
    if rng < 0.05: return False  # candle เล็กเกิน
    if body == 0: body = rng * 0.1
    if direction == "BUY":
        lower_wick = min(o,c) - l
        return lower_wick > body * 1.5 and body/rng < 0.5
    else:
        upper_wick = h - max(o,c)
        return upper_wick > body * 1.5 and body/rng < 0.5'''

# แก้ _is_m5_bos — ใช้ n=1 แทน n=2 เพราะ candle เล็ก
old_bos = '''def _is_m5_bos(candles, direction):
    if len(candles) < 10: return False
    recent = candles[-10:]
    last_close = candles[-1].get("close",0)
    if direction == "BUY":
        hs, _ = _swing_highs_lows(recent, n=2)
        return bool(hs and last_close > hs[-1]["price"])
    else:
        _, ls = _swing_highs_lows(recent, n=2)
        return bool(ls and last_close < ls[-1]["price"])'''

new_bos = '''def _is_m5_bos(candles, direction):
    if len(candles) < 6: return False
    recent = candles[-10:]
    last_close = candles[-1].get("close",0)
    if direction == "BUY":
        # ราคาปิดสูงกว่า high ของ 3 candles ก่อนหน้า
        prev_highs = [c.get("high",0) for c in candles[-4:-1]]
        return bool(prev_highs and last_close > max(prev_highs))
    else:
        # ราคาปิดต่ำกว่า low ของ 3 candles ก่อนหน้า
        prev_lows = [c.get("low",0) for c in candles[-4:-1]]
        return bool(prev_lows and last_close < min(prev_lows))'''

content = content.replace(old_engulfing, new_engulfing)
content = content.replace(old_pinbar, new_pinbar)
content = content.replace(old_bos, new_bos)

with open('strategy.py', 'w') as f:
    f.write(content)

print("✅ strategy.py patched!")
