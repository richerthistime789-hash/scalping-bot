"""
backtest.py — Backtest SMC Scalping Strategy
ใช้ Twelve Data API | XAUUSD | H1→M15→M5
"""
import os, requests, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from strategy import run_strategy

load_dotenv()

TWELVE_KEY = os.getenv("TWELVE_DATA_API_KEY", "180a281ad6f744ef9f41de0241092787")
BKK        = ZoneInfo("Asia/Bangkok")

SYMBOL    = "XAU/USD"
PIP_SIZE  = 0.01
PIP_VALUE = 10.0
MIN_RR    = 2.0
RISK_PCT  = 0.5
BALANCE   = 10000.0
SPREAD_PIPS    = 3.0   # XAUUSD typical spread (pips)
SLIPPAGE_PIPS  = 1.0   # ยอมรับ slippage 1 pip ต่อ trade

def fetch_twelve(interval, outputsize=5000):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol":     SYMBOL,
        "interval":   interval,
        "outputsize": outputsize,
        "apikey":     TWELVE_KEY,
        "format":     "JSON",
        "order":      "ASC",
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if data.get("status") == "error":
            print(f"❌ Twelve Data error: {data.get('message')}")
            return []
        values = data.get("values", [])
        # แปลงเป็น format เดียวกับ MetaAPI
        candles = []
        for v in values:
            candles.append({
                "time":  v.get("datetime"),
                "open":  float(v.get("open",  0)),
                "high":  float(v.get("high",  0)),
                "low":   float(v.get("low",   0)),
                "close": float(v.get("close", 0)),
            })
        return candles
    except Exception as e:
        print(f"❌ Fetch error {interval}: {e}")
        return []

def get_session(dt):
    h = dt.hour
    if 10 <= h < 14:     return "Asian"
    if 14 <= h < 19:     return "London"
    if h >= 19 or h < 2: return "London+NY"
    return "Inactive"

def is_active_session(dt):
    return get_session(dt) in ["Asian", "London", "London+NY"]

def simulate_trade(direction, entry, sl, tp, future_candles):
    """
    คำนวณผล trade รวม spread + slippage:
    - BUY: actual entry = entry + spread + slippage (แพงขึ้น)
    - SELL: actual entry = entry - spread - slippage (ถูกลง)
    - SL/TP เลื่อนตามจริง
    """
    cost = (SPREAD_PIPS + SLIPPAGE_PIPS) * PIP_SIZE
    if direction == "BUY":
        # entry แพงขึ้น → SL ใกล้ขึ้น (เสี่ยงเพิ่ม), TP ไกลขึ้น (กำไรลด)
        adj_sl = sl + cost   # SL ขยับขึ้นเทียบกับ raw price
        adj_tp = tp + cost
    else:
        adj_sl = sl - cost
        adj_tp = tp - cost

    for c in future_candles:
        high = c.get("high", 0)
        low  = c.get("low",  0)
        if direction == "BUY":
            hit_sl = low  <= adj_sl
            hit_tp = high >= adj_tp
            if hit_sl and not hit_tp: return "LOSS"
            if hit_tp and not hit_sl: return "WIN"
            if hit_sl and hit_tp:
                # ใช้ midpoint heuristic — ถ้า candle เปิดใกล้ SL/TP ฝั่งไหน
                open_  = c.get("open", 0)
                close_ = c.get("close", 0)
                # ถ้า candle เป็น bearish ใหญ่ → น่าจะแตะ SL ก่อน
                if close_ < open_: return "LOSS"
                return "WIN"
        else:
            hit_sl = high >= adj_sl
            hit_tp = low  <= adj_tp
            if hit_sl and not hit_tp: return "LOSS"
            if hit_tp and not hit_sl: return "WIN"
            if hit_sl and hit_tp:
                open_  = c.get("open", 0)
                close_ = c.get("close", 0)
                if close_ > open_: return "LOSS"
                return "WIN"
    return "OPEN"

def run_backtest():
    print("=" * 60)
    print("  BACKTEST — XAUUSD SMC Scalping Strategy")
    print(f"  Source: Twelve Data | RR: 1:{MIN_RR} | Risk: {RISK_PCT}%")
    print("=" * 60)
    print("กำลังดึงข้อมูลจาก Twelve Data...")

    h4_all  = fetch_twelve("4h", 1500)
    time.sleep(1)
    h1_all  = fetch_twelve("1h", 5000)
    time.sleep(1)
    m15_all = fetch_twelve("15min", 5000)
    time.sleep(1)
    m5_all  = fetch_twelve("5min", 5000)

    if not h1_all or not m15_all or not m5_all:
        print("❌ ดึงข้อมูลไม่ได้ เช็ค API key")
        return

    print(f"✅ H4: {len(h4_all)} | H1: {len(h1_all)} | M15: {len(m15_all)} | M5: {len(m5_all)} candles")
    if h1_all:
        print(f"   ช่วงเวลา: {h1_all[0]['time']} → {h1_all[-1]['time']}")
    print()

    trades      = []
    balance     = BALANCE
    max_equity  = BALANCE
    max_dd      = 0
    scan_count  = 0
    signal_count= 0
    last_trade_time = None
    COOLDOWN_HOURS  = 2

    WINDOW_H1  = 50  # H2 candles
    WINDOW_M15 = 100
    WINDOW_M5  = 30
    STEP       = 2

    for i in range(WINDOW_M15, len(m5_all) - 20, STEP):  # iterate over M5
        # ใช้ M5 เป็น scanning TF
        m15_window     = m5_all[max(0, i-WINDOW_M15):i]   # rename for compat (เป็น m5 จริง)
        current_candle = m5_all[i]

        try:
            candle_dt = datetime.fromisoformat(current_candle["time"]).replace(tzinfo=ZoneInfo("UTC")).astimezone(BKK)
        except Exception as e:
            print(f"ERR: {e}")
            continue

        if not is_active_session(candle_dt): continue
        if candle_dt.weekday() in [5, 6]:    continue

        # Map by datetime (ไม่ใช่ index ratio) เพื่อให้ trustable
        try:
            cur_dt = datetime.fromisoformat(current_candle["time"])
        except:
            continue

        # H4: ใช้ candles ที่ time < cur_dt และเอา 50 ตัวล่าสุด
        h4_window = [c for c in h4_all if c["time"] < current_candle["time"]][-50:]
        # H1: ใช้ candles ที่ time < cur_dt และเอา 80 ตัวล่าสุด
        h1_window = [c for c in h1_all if c["time"] < current_candle["time"]][-80:]
        m5_idx = i  # M5 is the scanning TF
        m5_window = m5_all[max(0, m5_idx - WINDOW_M5):m5_idx]

        if len(h4_window) < 30 or len(h1_window) < 30 or len(m15_window) < 20:
            continue

        current_price = current_candle.get("close", 0)
        if not current_price: continue

        scan_count += 1

        try:
            result = run_strategy(h4_window, h1_window, m15_window, current_price)
        except Exception as e:
            print(f"ERR: {e}")
            continue

        opp = result.get("opportunity", "Skip")
        m5  = result.get("m5_signal")

        if opp not in ["High", "Medium"]: continue
        if not m5 or m5.signal == "WAIT": continue
        if not m5.entry or not m5.sl or not m5.tp: continue

        # Cooldown check — ห้าม re-entry ภายใน 4 ชั่วโมง
        if last_trade_time:
            hours_since = (candle_dt - last_trade_time).total_seconds() / 3600
            if hours_since < COOLDOWN_HOURS:
                continue

        signal_count += 1

        future_m5 = m5_all[m5_idx:m5_idx + 100]  # 100 M5 = ~8 ชม
        outcome   = simulate_trade(m5.signal, m5.entry, m5.sl, m5.tp, future_m5)
        if outcome == "OPEN":
            outcome = "LOSS"



        risk_usd = balance * (RISK_PCT / 100)
        # cost ของ spread+slippage หักจากกำไรเสมอ
        cost_pct = (SPREAD_PIPS + SLIPPAGE_PIPS) / max(m5.sl_pips or 50, 30)
        cost_usd = risk_usd * cost_pct
        if outcome == "WIN":
            pnl = round(risk_usd * MIN_RR - cost_usd, 2)
        else:
            pnl = round(-risk_usd - cost_usd, 2)
        balance += pnl
        max_equity = max(max_equity, balance)
        dd = (max_equity - balance) / max_equity * 100
        max_dd = max(max_dd, dd)

        last_trade_time = candle_dt
        trades.append({
            "time":      candle_dt.strftime("%Y-%m-%d %H:%M"),
            "session":   get_session(candle_dt),
            "direction": m5.signal,
            "pattern":   m5.pattern,
            "sl_pips":   m5.sl_pips or 0,
            "outcome":   outcome,
            "pnl":       pnl,
            "balance":   round(balance, 2),
            "h1_bias":   result["h1_bias"].direction,
            "opp":       opp,
        })

    if not trades:
        print(f"⚠️  Scanned {scan_count} bars | Signals: {signal_count} | No completed trades")
        return

    wins   = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    net_pnl   = sum(t["pnl"] for t in trades)
    win_rate  = len(wins) / len(trades) * 100
    gross_win = sum(t["pnl"] for t in wins)
    gross_los = abs(sum(t["pnl"] for t in losses))
    pf        = round(gross_win / gross_los, 2) if gross_los else 999

    print("=" * 60)
    print("  📊 BACKTEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Bars scanned   : {scan_count}")
    print(f"  Signals found  : {signal_count}")
    print(f"  Trades taken   : {len(trades)}")
    print(f"  Wins / Losses  : {len(wins)} / {len(losses)}")
    print(f"  Win Rate       : {win_rate:.1f}%")
    print(f"  Profit Factor  : {pf}")
    print(f"  Net P/L        : ${net_pnl:+.2f}")
    print(f"  Max Drawdown   : {max_dd:.2f}%")
    print(f"  Final Balance  : ${balance:,.2f}  (start: ${BALANCE:,.2f})")
    print()

    print("  📅 BY SESSION")
    print("  " + "-" * 45)
    for sess in ["Asian", "London", "London+NY"]:
        st = [t for t in trades if t["session"] == sess]
        if not st: continue
        sw = [t for t in st if t["outcome"] == "WIN"]
        wr = len(sw)/len(st)*100
        pl = sum(t["pnl"] for t in st)
        print(f"  {sess:<12} | {len(st):>3} trades | WR: {wr:.0f}% | P/L: ${pl:+.2f}")

    print()
    print("  🕯 BY PATTERN")
    print("  " + "-" * 45)
    for pat in ["Engulfing", "PinBar", "BOS"]:
        pt = [t for t in trades if t["pattern"] == pat]
        if not pt: continue
        pw = [t for t in pt if t["outcome"] == "WIN"]
        wr = len(pw)/len(pt)*100
        pl = sum(t["pnl"] for t in pt)
        print(f"  {pat:<12} | {len(pt):>3} trades | WR: {wr:.0f}% | P/L: ${pl:+.2f}")

    print()
    print("  📋 TRADE LOG (ล่าสุด 20 รายการ)")
    print("  " + "-" * 72)
    print(f"  {'Time':<17} {'Sess':<10} {'Dir':<5} {'Pat':<10} {'SL':>5} {'Result':<6} {'P/L':>8} {'Balance':>10}")
    print("  " + "-" * 72)
    for t in trades[-20:]:
        e = "✅" if t["outcome"] == "WIN" else "❌"
        print(f"  {t['time']:<17} {t['session']:<10} {t['direction']:<5} {t['pattern']:<10} "
              f"{t['sl_pips']:>5.0f} {e}{t['outcome']:<5} {t['pnl']:>+8.2f} {t['balance']:>10.2f}")

    print("=" * 60)
    print(f"  ✅ Done — {len(trades)} trades | Start: ${BALANCE:,.2f} → End: ${balance:,.2f}")
    print("=" * 60)

if __name__ == "__main__":
    run_backtest()
