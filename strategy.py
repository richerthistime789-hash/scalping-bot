"""
strategy.py — SMC Scalping Strategy
H1 Bias (BOS/CHoCH + S/R) → M15 Zone (Swing H/L) → M5 Entry
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class H1Bias:
    direction: str
    structure: str
    last_bos: Optional[str]
    choch: Optional[str]
    key_support: Optional[float]
    key_resistance: Optional[float]
    confidence: str
    reason: str

@dataclass
class M15Zone:
    in_zone: bool
    zone_type: str
    zone_high: Optional[float]
    zone_low: Optional[float]
    zone_strength: int
    bias: str
    reason: str

@dataclass
class M5Signal:
    signal: str
    pattern: str
    entry: Optional[float]
    sl: Optional[float]
    tp: Optional[float]
    sl_pips: Optional[float]
    rr: Optional[float]
    reason: str

PIP_SIZE    = 0.1
MIN_RR      = 1.5
MIN_SL_PIPS = 30
MAX_SL_PIPS = 150

def _swing_highs_lows(candles, n=5):
    highs, lows = [], []
    for i in range(n, len(candles) - n):
        h = candles[i].get("high", 0)
        l = candles[i].get("low", 0)
        if all(h >= candles[i-j].get("high",0) for j in range(1,n+1)) and \
           all(h >= candles[i+j].get("high",0) for j in range(1,n+1)):
            highs.append({"index": i, "price": h})
        if all(l <= candles[i-j].get("low",0) for j in range(1,n+1)) and \
           all(l <= candles[i+j].get("low",0) for j in range(1,n+1)):
            lows.append({"index": i, "price": l})
    return highs, lows

def _detect_structure(highs, lows):
    if len(highs) < 2 or len(lows) < 2:
        return "Sideways"
    if highs[-1]["price"] > highs[-2]["price"] and lows[-1]["price"] > lows[-2]["price"]:
        return "HH_HL"
    elif highs[-1]["price"] < highs[-2]["price"] and lows[-1]["price"] < lows[-2]["price"]:
        return "LH_LL"
    return "Sideways"

def _detect_bos_choch(highs, lows, closes):
    if len(highs) < 2 or len(lows) < 2:
        return None, None
    bos, choch = None, None
    if highs[-1]["price"] > highs[-2]["price"] and lows[-1]["price"] > lows[-2]["price"]:
        bos = "Bullish_BOS"
    elif lows[-1]["price"] < lows[-2]["price"] and highs[-1]["price"] < highs[-2]["price"]:
        bos = "Bearish_BOS"
    if highs[-1]["price"] < highs[-2]["price"] and lows[-1]["price"] > lows[-2]["price"]:
        choch = "Bullish_CHoCH"
    elif highs[-1]["price"] < highs[-2]["price"] and lows[-1]["price"] < lows[-2]["price"]:
        choch = "Bearish_CHoCH"
    return bos, choch

def calc_h1_bias(candles):
    if len(candles) < 20:
        return H1Bias("Neutral","Sideways",None,None,None,None,"Low","Not enough candles")
    closes = [c.get("close",0) for c in candles]
    highs_list, lows_list = _swing_highs_lows(candles, n=5)
    if not highs_list or not lows_list:
        return H1Bias("Neutral","Sideways",None,None,None,None,"Low","No swing points")
    structure = _detect_structure(highs_list, lows_list)
    bos, choch = _detect_bos_choch(highs_list, lows_list, closes)
    key_resistance = highs_list[-1]["price"]
    key_support    = lows_list[-1]["price"]
    if structure == "HH_HL":
        direction  = "Bullish"
        confidence = "High" if bos == "Bullish_BOS" else "Medium"
        reason     = f"HH+HL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    elif structure == "LH_LL":
        direction  = "Bearish"
        confidence = "High" if bos == "Bearish_BOS" else "Medium"
        reason     = f"LH+LL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    else:
        direction, confidence, reason = "Neutral", "Low", "Sideways — using M15 bias"
    return H1Bias(direction, structure, bos, choch,
                  round(key_support,2), round(key_resistance,2), confidence, reason)

def calc_m15_zone(candles, current_price):
    if len(candles) < 20:
        return M15Zone(False,"None",None,None,0,"Neutral","Not enough candles")
    highs_list, lows_list = _swing_highs_lows(candles, n=5)
    structure = _detect_structure(highs_list, lows_list) if highs_list and lows_list else "Sideways"
    m15_bias = {"HH_HL":"Bullish","LH_LL":"Bearish"}.get(structure,"Neutral")
    if not highs_list or not lows_list:
        return M15Zone(False,"None",None,None,0,m15_bias,"No swing points")
    ZONE_BUFFER = 15 * PIP_SIZE
    ZONE_WIDTH  = 20 * PIP_SIZE
    for sw in reversed(lows_list[-5:]):
        zl, zh = sw["price"] - ZONE_WIDTH, sw["price"] + ZONE_WIDTH
        if zl - ZONE_BUFFER <= current_price <= zh + ZONE_BUFFER:
            touches = sum(1 for s in lows_list if abs(s["price"]-sw["price"]) < ZONE_WIDTH*2)
            return M15Zone(True,"Support",round(zh,2),round(zl,2),touches,m15_bias,
                           f"Near Support {zl:.2f}-{zh:.2f} (x{touches})")
    for sw in reversed(highs_list[-5:]):
        zl, zh = sw["price"] - ZONE_WIDTH, sw["price"] + ZONE_WIDTH
        if zl - ZONE_BUFFER <= current_price <= zh + ZONE_BUFFER:
            touches = sum(1 for s in highs_list if abs(s["price"]-sw["price"]) < ZONE_WIDTH*2)
            return M15Zone(True,"Resistance",round(zh,2),round(zl,2),touches,m15_bias,
                           f"Near Resistance {zl:.2f}-{zh:.2f} (x{touches})")
    return M15Zone(False,"None",None,None,0,m15_bias,"Price not near any zone")

def _is_engulfing(c1, c2, direction):
    o1,c1v = c1.get("open",0), c1.get("close",0)
    o2,c2v = c2.get("open",0), c2.get("close",0)
    if direction == "BUY":
        return (c1v < o1) and (c2v > o2) and (c2v > o1) and (o2 < c1v)
    return (c1v > o1) and (c2v < o2) and (c2v < o1) and (o2 > c1v)

def _is_pin_bar(candle, direction):
    o,c,h,l = candle.get("open",0),candle.get("close",0),candle.get("high",0),candle.get("low",0)
    body = abs(c-o); rng = h-l
    if rng == 0: return False
    if direction == "BUY":
        return (min(o,c)-l) > body*2 and body/rng < 0.4
    return (h-max(o,c)) > body*2 and body/rng < 0.4

def _is_m5_bos(candles, direction):
    if len(candles) < 10: return False
    recent = candles[-10:]
    last_close = candles[-1].get("close",0)
    if direction == "BUY":
        hs, _ = _swing_highs_lows(recent, n=2)
        return bool(hs and last_close > hs[-1]["price"])
    else:
        _, ls = _swing_highs_lows(recent, n=2)
        return bool(ls and last_close < ls[-1]["price"])

def calc_m5_entry(candles, direction, zone):
    if len(candles) < 5:
        return M5Signal("WAIT","None",None,None,None,None,None,"Not enough candles")
    if direction not in ["BUY","SELL"]:
        return M5Signal("WAIT","None",None,None,None,None,None,"No directional bias")
    last, prev = candles[-1], candles[-2]
    current = last.get("close",0)
    pattern = "None"
    if _is_engulfing(prev, last, direction):   pattern = "Engulfing"
    elif _is_pin_bar(last, direction):          pattern = "PinBar"
    elif _is_m5_bos(candles, direction):        pattern = "BOS"
    if pattern == "None":
        return M5Signal("WAIT","None",None,None,None,None,None,"No M5 pattern")
    entry = current
    if direction == "BUY":
        sl = (zone.zone_low - 5*PIP_SIZE) if (zone.in_zone and zone.zone_low) else (last.get("low",0) - 10*PIP_SIZE)
        sl_pips = (entry-sl)/PIP_SIZE
        tp = entry + sl_pips*MIN_RR*PIP_SIZE
    else:
        sl = (zone.zone_high + 5*PIP_SIZE) if (zone.in_zone and zone.zone_high) else (last.get("high",0) + 10*PIP_SIZE)
        sl_pips = (sl-entry)/PIP_SIZE
        tp = entry - sl_pips*MIN_RR*PIP_SIZE
    if sl_pips < MIN_SL_PIPS or sl_pips > MAX_SL_PIPS:
        return M5Signal("WAIT",pattern,None,None,None,round(sl_pips,1),None,
                        f"SL {sl_pips:.0f} pips out of range")
    rr = abs(tp-entry)/abs(entry-sl) if abs(entry-sl) > 0 else 0
    return M5Signal(direction, pattern, round(entry,2), round(sl,2), round(tp,2),
                    round(sl_pips,1), round(rr,2), f"{pattern} | SL {sl_pips:.0f}p | RR 1:{rr:.1f}")

def run_strategy(h1_candles, m15_candles, m5_candles, current_price):
    h1  = calc_h1_bias(h1_candles)
    m15 = calc_m15_zone(m15_candles, current_price)
    bias_direction = h1.direction if h1.direction != "Neutral" else m15.bias
    if bias_direction == "Neutral":
        return {"opportunity":"Skip","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"No bias"),
                "reason":"Both H1 and M15 sideways"}
    if not m15.in_zone:
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Not in zone"),
                "reason":"Price not near M15 zone"}
    if bias_direction == "Bullish" and m15.zone_type != "Support":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bullish but near Resistance — skip"}
    if bias_direction == "Bearish" and m15.zone_type != "Resistance":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bearish but near Support — skip"}
    trade_dir = "BUY" if bias_direction == "Bullish" else "SELL"
    m5 = calc_m5_entry(m5_candles, trade_dir, m15)
    if m5.signal == "WAIT":
        return {"opportunity":"Medium","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":m5,"reason":f"Setup ready, no M5 confirmation — {m5.reason}"}
    opp = "High" if (h1.confidence == "High" and m15.zone_strength >= 2) else "Medium"
    return {"opportunity":opp,"direction":trade_dir,"h1_bias":h1,"m15_zone":m15,
            "m5_signal":m5,"reason":f"H1 {h1.direction} | M15 {m15.zone_type} | M5 {m5.pattern}"}
