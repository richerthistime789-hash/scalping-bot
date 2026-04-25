"""
scalping_main.py — XAUUSD Scalping Bot
Strategy: H1 bias → M15 zone → M5 entry
RR: 1:1.5 | Risk: 0.5% | Zone-based SL
Sessions: Asian 10:00+ | London | London+NY
"""
import os, json, time, logging, threading, requests, html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from anthropic import Anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from strategy import run_strategy
from database import save_trade, update_trade_result, get_all_trades, get_daily_pnl, get_weekly_stats, get_monthly_stats

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("scalping.log", encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

claude          = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
META_TOKEN      = os.getenv("META_API_TOKEN", "").strip()
DEMO_ACCOUNT_ID = os.getenv("DEMO_ACCOUNT_ID", "").strip()
TELEGRAM_TOKEN  = os.getenv("SCALPING_BOT_TOKEN", "").strip()
TELEGRAM_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BKK = ZoneInfo("Asia/Bangkok")

# ── Config ─────────────────────────────────────────────────────────────────
SYMBOL        = "XAUUSD"
NAME          = "Gold"
PIP_SIZE      = 0.1
PIP_VALUE     = 10.0
RISK_PERCENT  = 0.5
MIN_RR        = 1.5
MIN_SL_PIPS   = 30    # scalping SL แคบกว่า
MAX_SL_PIPS   = 150   # ไม่ให้กว้างเกินไป
MAX_LOT       = 0.5
MAX_OPEN      = 2
MAX_TOTAL_LOTS= 1.0
MAX_DRAWDOWN  = 5.0
MAX_DAILY_LOSS= 2.0
MAX_CONSEC    = 3

BASE_HISTORY  = "https://mt-market-data-client-api-v1.new-york.agiliumtrade.ai"
BASE_PRICE    = "https://mt-client-api-v1.london.agiliumtrade.ai"
HEADERS       = {"auth-token": META_TOKEN, "Content-Type": "application/json"}

NEWS_BLOCK_BEFORE = 120  # นาที
NEWS_BLOCK_AFTER  = 30

_monitor_lock = threading.Lock()

# ── Session ─────────────────────────────────────────────────────────────────
def get_session():
    h = datetime.now(BKK).hour
    if 10 <= h < 14:  return "Asian"
    if 14 <= h < 19:  return "London"
    if h >= 19 or h < 2: return "London+NY"
    return "Inactive"

def is_active():
    return get_session() in ["Asian", "London", "London+NY"]

def is_weekend():
    now = datetime.now(BKK)
    if now.weekday() in [5, 6]: return True
    if now.weekday() == 4 and now.hour >= 20: return True
    return False

def is_friday_eod():
    now = datetime.now(BKK)
    return now.weekday() == 4 and now.hour >= 2

# ── News Filter ─────────────────────────────────────────────────────────────
def get_news():
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10)
        if r.status_code != 200: return []
        events = []
        for e in r.json():
            if e.get("impact") != "High": continue
            if e.get("currency") not in ["USD", "XAU"]: continue
            try:
                dt = datetime.strptime(e["date"] + " " + e["time"], "%Y-%m-%dT%H:%M:%S%z")
                events.append(dt.astimezone(BKK))
            except: pass
        return events
    except: return []

def is_news_time():
    now = datetime.now(BKK)
    for e in get_news():
        diff = (now - e).total_seconds() / 60
        if -NEWS_BLOCK_BEFORE <= diff <= NEWS_BLOCK_AFTER:
            return True, e.strftime("%H:%M")
    return False, None

# ── API Helpers ─────────────────────────────────────────────────────────────
def fetch_candles(tf, limit):
    url = f"{BASE_HISTORY}/users/current/accounts/{DEMO_ACCOUNT_ID}/historical-market-data/symbols/{SYMBOL}/timeframes/{tf}/candles"
    try:
        r = requests.get(url, headers=HEADERS, params={"limit": limit}, timeout=30)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception as e:
        log.warning(f"candles {tf}: {e}")
        return []

def fetch_price():
    url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/symbols/{SYMBOL}/current-price"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {"bid": d.get("bid"), "ask": d.get("ask")}
        return {}
    except: return {}

def get_account():
    url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/account-information"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {"balance": d.get("balance", 0), "equity": d.get("equity", 0)}
        return {}
    except: return {}

def get_positions():
    url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/positions"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200: return r.json()
        return []
    except: return []

def place_order(direction, lot, sl, tp):
    url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/trade"
    payload = {
        "actionType": "ORDER_TYPE_BUY" if direction == "BUY" else "ORDER_TYPE_SELL",
        "symbol": SYMBOL, "volume": lot,
        "stopLoss": sl, "takeProfit": tp,
        "comment": "Scalping Bot"
    }
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=15)
        if r.status_code in [200, 201]: return r.json()
        log.error(f"Order failed: {r.status_code} {r.text[:100]}")
        return None
    except Exception as e:
        log.error(f"Order exception: {e}")
        return None

def modify_sl(pos_id, new_sl):
    url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/positions/{pos_id}"
    try:
        r = requests.put(url, headers=HEADERS, json={"stopLoss": new_sl}, timeout=15)
        return r.status_code in [200, 201]
    except: return False

# ── Indicators ──────────────────────────────────────────────────────────────
def calc_ema(closes, p):
    if len(closes) < p: return None
    k = 2/(p+1); e = sum(closes[:p])/p
    for c in closes[p:]: e = c*k + e*(1-k)
    return round(e, 3)

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return None
    g=[]; l=[]
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]
        g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[-p:])/p; al=sum(l[-p:])/p
    return round(100-(100/(1+ag/al)),1) if al else 100

def calc_atr(candles, p=14):
    if len(candles) < p+1: return None
    trs=[]
    for i in range(1, len(candles)):
        h=candles[i].get("high",0); l=candles[i].get("low",0); pc=candles[i-1].get("close",0)
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return round(sum(trs[-p:])/p/PIP_SIZE, 1)

# ── Risk ────────────────────────────────────────────────────────────────────
pause_until = None
consec_losses = 0

def calc_lot(equity, entry, sl):
    risk = equity * (RISK_PERCENT/100)
    sl_pips = abs(entry-sl)/PIP_SIZE
    if sl_pips <= 0: return 0.01
    lot = round(risk/(sl_pips*PIP_VALUE), 2)
    return max(0.01, min(lot, MAX_LOT))

def check_risk(new_lot):
    global pause_until
    now = datetime.now(BKK)
    if pause_until and now < pause_until:
        return False, f"Paused until {pause_until.strftime('%H:%M')}"
    info = get_account()
    if not info: return False, "Cannot get account info"
    balance = info.get("balance", 0)
    equity  = info.get("equity", 0)
    daily_pnl = get_daily_pnl()
    if balance > 0:
        if abs(min(daily_pnl,0))/balance*100 >= MAX_DAILY_LOSS:
            return False, f"Daily loss limit reached"
        if (balance-equity)/balance*100 >= MAX_DRAWDOWN:
            return False, f"Max drawdown reached"
    positions = get_positions()
    if len(positions) >= MAX_OPEN:
        return False, f"Max positions ({MAX_OPEN})"
    if sum(p.get("volume",0) for p in positions)+new_lot > MAX_TOTAL_LOTS:
        return False, "Max total lots reached"
    open_syms = [p.get("symbol") for p in positions]
    if SYMBOL in open_syms:
        return False, "Re-entry protection"
    return True, "OK"

def record_loss():
    global consec_losses, pause_until
    consec_losses += 1
    if consec_losses >= MAX_CONSEC:
        pause_until = datetime.now(BKK) + timedelta(hours=24)
        consec_losses = 0
        send_telegram(f"⏸ <b>Paused 24hr</b> — {MAX_CONSEC} consecutive losses\nResume: {pause_until.strftime('%d/%m %H:%M')}")

def record_win():
    global consec_losses
    consec_losses = 0

# ── Analysis (Scalping) ─────────────────────────────────────────────────────
def analyze(h1_candles, m15_candles, m5_candles, price):
    def summarize(candles, label, n=10):
        if not candles: return f"{label}: no data"
        last = candles[-n:]
        closes = [c.get("close",0) for c in last if c.get("close")]
        highs  = [c.get("high",0)  for c in last if c.get("high")]
        lows   = [c.get("low",0)   for c in last if c.get("low")]
        if not closes: return f"{label}: no data"
        trend = "Bullish" if closes[-1] > closes[0] else "Bearish"
        e20 = calc_ema(closes, min(20, len(closes)))
        rsi = calc_rsi(closes)
        return (f"{label}: High={max(highs):.2f} Low={min(lows):.2f} Close={closes[-1]:.2f} "
                f"[{trend}] EMA20={e20:.2f if e20 else 'N/A'} RSI={rsi if rsi else 'N/A'}")

    h1_closes  = [c.get("close",0) for c in h1_candles  if c.get("close")]
    m15_closes = [c.get("close",0) for c in m15_candles if c.get("close")]
    atr = calc_atr(m15_candles)

    prompt = f"""คุณเป็น scalping trader เชี่ยวชาญ XAUUSD ใช้ Price Action และ S/R Zone

สัญลักษณ์: {NAME} ({SYMBOL})
ราคาปัจจุบัน: Bid={price.get("bid")} Ask={price.get("ask")}
ATR (M15): {atr} pips

=== HTF Bias (H1) ===
{summarize(h1_candles, "H1", 20)}

=== Setup Zone (M15) ===
{summarize(m15_candles, "M15", 15)}

=== Entry Signal (M5) ===
{summarize(m5_candles, "M5", 10)}

Strategy Rules:
1. H1 กำหนด Bias (Bullish/Bearish/Neutral)
2. M15 หา S/R Zone ที่ราคากำลังอยู่ใกล้
3. M5 หา Entry signal (Engulfing, Pin Bar, Break+Retest)
4. SL วางใต้/เหนือ zone M15 ห่าง {MIN_SL_PIPS}-{MAX_SL_PIPS} pips
5. TP = RR 1:{MIN_RR}
6. ถ้า H1 Neutral หรือ M15 ไม่มี zone ชัด → Skip
7. Counter-trend กับ H1 → Skip เด็ดขาด

ตอบ JSON เท่านั้น:
{{
  "opportunity": "High/Medium/Low/Skip",
  "bias": "Bullish/Bearish/Neutral",
  "h1_analysis": "วิเคราะห์ H1 สั้นๆ",
  "m15_zone": "zone ที่สำคัญ",
  "m5_signal": "สัญญาณ M5 ที่เห็น",
  "best_entry": {{
    "direction": "BUY/SELL/WAIT",
    "entry": "ราคา",
    "sl": "ราคา",
    "tp": "ราคา",
    "rr": "1:1.5",
    "confirmation": "รอสัญญาณอะไรเพิ่ม"
  }},
  "summary": "สรุป 1-2 ประโยค"
}}"""

    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip().replace("```json","").replace("```","").strip()
    start = text.find("{"); end = text.rfind("}")+1
    if start >= 0 and end > start: text = text[start:end]
    return json.loads(text)

# ── Telegram ─────────────────────────────────────────────────────────────────
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

def format_msg(analysis, price):
    opp_emoji = {"High":"🔥","Medium":"⚡","Low":"💤","Skip":"⏭️"}.get(analysis.get("opportunity",""),"❓")
    e = analysis.get("best_entry", {})
    now = datetime.now(BKK).strftime("%d/%m %H:%M")
    return (
        f"{opp_emoji} <b>Scalping — {NAME} ({SYMBOL})</b> — {now}\n"
        f"💹 {price.get('bid')} / {price.get('ask')}\n"
        f"📊 Bias: <b>{html.escape(str(analysis.get('bias','')))}</b> | โอกาส: <b>{analysis.get('opportunity','')}</b>\n\n"
        f"📋 H1: <i>{html.escape(str(analysis.get('h1_analysis',''))[:200])}</i>\n"
        f"📍 M15 Zone: {html.escape(str(analysis.get('m15_zone','')))}\n"
        f"🕯 M5 Signal: {html.escape(str(analysis.get('m5_signal','')))}\n\n"
        f"{'📈' if e.get('direction')=='BUY' else '📉'} <b>{e.get('direction','WAIT')}</b>\n"
        f"  Entry: {e.get('entry','-')} | SL: {e.get('sl','-')} | TP: {e.get('tp','-')}\n"
        f"  R/R: {e.get('rr','-')}\n"
        f"  ⏳ {e.get('confirmation','-')}\n\n"
        f"💬 <i>{html.escape(str(analysis.get('summary',''))[:200])}</i>"
    )

# ── Execute ──────────────────────────────────────────────────────────────────
def execute(analysis, price):
    e = analysis.get("best_entry", {})
    direction = e.get("direction")
    if direction not in ["BUY","SELL"]: return

    try:
        entry = float(str(e.get("entry","")).replace(",",""))
        sl    = float(str(e.get("sl","")).replace(",",""))
        tp    = float(str(e.get("tp","")).replace(",",""))
    except: return

    sl_pips = abs(entry-sl)/PIP_SIZE
    if sl_pips < MIN_SL_PIPS or sl_pips > MAX_SL_PIPS:
        log.info(f"SL pips {sl_pips:.0f} out of range {MIN_SL_PIPS}-{MAX_SL_PIPS}")
        return

    rr = abs(tp-entry)/abs(entry-sl)
    if rr < MIN_RR:
        log.info(f"RR {rr:.2f} < {MIN_RR}")
        return

    info   = get_account()
    equity = info.get("equity", 10000)
    lot    = calc_lot(equity, entry, sl)

    can, reason = check_risk(lot)
    if not can:
        log.info(f"Risk check failed: {reason}")
        send_telegram(f"⛔ <b>Skip</b> — {reason}")
        return

    result = place_order(direction, lot, sl, tp)
    if result:
        risk_usd = equity * (RISK_PERCENT/100)
        save_trade({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol": SYMBOL, "name": NAME,
            "direction": direction, "lot": lot,
            "entry": entry, "sl": sl, "tp": tp,
            "risk_usd": round(risk_usd, 2), "equity": equity,
            "opportunity": analysis.get("opportunity"),
            "order_id": result.get("orderId", "N/A"),
            "session": get_session(),
        })
        send_telegram(
            f"🤖 <b>Scalping Trade Executed</b>\n"
            f"{'📈' if direction=='BUY' else '📉'} {direction} | Lot: {lot}\n"
            f"Entry: {entry} | SL: {sl} | TP: {tp}\n"
            f"R/R: 1:{MIN_RR} | Risk: ${risk_usd:.0f}\n"
            f"Order: {result.get('orderId','N/A')}"
        )

# ── Scan ─────────────────────────────────────────────────────────────────────
def scan():
    if is_weekend() or is_friday_eod():
        return
    if not is_active():
        return

    news_block, news_time = is_news_time()
    if news_block:
        log.info(f"News block: {news_time}")
        return

    log.info(f"Scalping scan — {get_session()} {datetime.now(BKK).strftime('%H:%M')}")

    h1_candles  = fetch_candles("1h",  50)
    m15_candles = fetch_candles("15m", 50)
    m5_candles  = fetch_candles("5m",  30)
    price       = fetch_price()

    if not price.get("bid"):
        log.warning("No price")
        return

    try:
        analysis = analyze(h1_candles, m15_candles, m5_candles, price)
    except Exception as e:
        log.error(f"analyze error: {e}")
        return

    opp = analysis.get("opportunity","Skip")
    log.info(f"Scan result: {opp} — {analysis.get('best_entry',{}).get('direction','')}")

    if opp != "Skip":
        send_telegram(format_msg(analysis, price))

    if opp in ["High","Medium"]:
        execute(analysis, price)

# ── Monitor ──────────────────────────────────────────────────────────────────
def monitor():
    while True:
        try:
            with _monitor_lock:
                positions = get_positions()
                open_ids  = {str(p.get("id")) for p in positions}

                for p in positions:
                    pos_id  = str(p.get("id"))
                    entry   = p.get("openPrice", 0)
                    current = p.get("currentPrice", 0)
                    sl      = p.get("stopLoss", 0)
                    tp      = p.get("takeProfit", 0)
                    profit  = p.get("profit", 0)
                    ptype   = p.get("type","")
                    if not entry or not sl: continue
                    risk_pts = abs(entry-sl)
                    is_buy   = "BUY" in ptype.upper()
                    price_diff = (current-entry) if is_buy else (entry-current)
                    # Move to BE เมื่อ profit >= RR 1:1
                    if price_diff >= risk_pts:
                        sl_at_be = abs(sl-entry) < 0.01*entry if entry else False
                        if not sl_at_be:
                            ok = modify_sl(pos_id, entry)
                            if ok:
                                send_telegram(f"🔒 <b>BE triggered</b> — {p.get('symbol')}\nSL → {entry} | Profit: ${profit:.2f}")

                # Update closed trades
                all_trades = get_all_trades()
                for t in all_trades:
                    if t.closed: continue
                    if str(t.order_id) not in open_ids and t.order_id != "N/A":
                        price_now = fetch_price()
                        close_px  = price_now.get("bid", 0)
                        pnl = 0
                        if t.entry and close_px:
                            diff = (close_px-t.entry) if t.direction=="BUY" else (t.entry-close_px)
                            pnl  = round((diff/PIP_SIZE)*PIP_VALUE*t.lot, 2)
                        result = "WIN" if pnl>0 else ("BE" if pnl==0 else "LOSS")
                        update_trade_result(t.id, close_px, pnl, result)
                        if result == "WIN": record_win()
                        else: record_loss()
                        send_telegram(
                            f"{'✅' if result=='WIN' else '❌'} <b>Trade Closed — {NAME}</b>\n"
                            f"{'📈' if t.direction=='BUY' else '📉'} {t.direction} | {result}\n"
                            f"P/L: <b>${pnl:+.2f}</b>"
                        )
        except Exception as e:
            log.error(f"monitor error: {e}")
        time.sleep(120)

# ── Friday EOD ───────────────────────────────────────────────────────────────
def friday_eod():
    while True:
        try:
            now = datetime.now(BKK)
            if now.weekday() == 4 and now.hour == 1 and now.minute >= 45:
                positions = get_positions()
                if positions:
                    send_telegram("⚠️ <b>Friday EOD</b> — ปิด positions ทั้งหมด")
                    for p in positions:
                        pos_id = str(p.get("id"))
                        url = f"{BASE_PRICE}/users/current/accounts/{DEMO_ACCOUNT_ID}/positions/{pos_id}/close"
                        requests.post(url, headers=HEADERS, timeout=15)
        except Exception as e:
            log.warning(f"friday_eod error: {e}")
        time.sleep(300)

# ── Scheduler ─────────────────────────────────────────────────────────────────
def scheduler():
    """Scan ทุก 30 นาที — scalping ต้องถี่กว่า"""
    while True:
        time.sleep(1800)
        scan()

# ── Telegram Commands ─────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>XAUUSD Scalping Bot</b>\n\n"
        "Strategy: H1 bias → M15 zone → M5 entry\n"
        "RR: 1:1.5 | Risk: 0.5%\n\n"
        "/scan — scan ทันที\n"
        "/status — สถานะ bot\n"
        "/positions — open positions\n"
        "/trades — trade log\n"
        "/weekly — weekly stats\n"
        "/pause — หยุด bot\n"
        "/resume — เปิด bot",
        parse_mode="HTML"
    )

BOT_ENABLED = True

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = False
    await update.message.reply_text("⏸ <b>Bot หยุดทำงาน</b>", parse_mode="HTML")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ENABLED
    BOT_ENABLED = True
    await update.message.reply_text("▶️ <b>Bot กลับมาทำงาน</b>", parse_mode="HTML")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info      = get_account()
    positions = get_positions()
    balance   = info.get("balance", 0)
    equity    = info.get("equity", 0)
    daily_pnl = get_daily_pnl()
    now       = datetime.now(BKK).strftime("%d/%m/%Y %H:%M")
    dd = (balance-equity)/balance*100 if balance else 0
    news_block, news_time = is_news_time()
    await update.message.reply_text(
        f"🤖 <b>Scalping Bot Status</b>\n"
        f"⏰ {now} [{get_session()}]\n"
        f"{'▶️ Active' if BOT_ENABLED else '⏸ Paused'}\n\n"
        f"💰 Balance: ${balance:,.2f}\n"
        f"📉 DD: {dd:.2f}%\n"
        f"📆 Daily P/L: ${daily_pnl:+.2f}\n"
        f"📦 Positions: {len(positions)}/{MAX_OPEN}\n"
        + (f"📰 News Block: {news_time}\n" if news_block else ""),
        parse_mode="HTML"
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ENABLED:
        await update.message.reply_text("⏸ Bot หยุดอยู่ครับ")
        return
    await update.message.reply_text("🔍 กำลัง scan... รอ 40 วินาทีครับ")
    threading.Thread(target=scan, daemon=True).start()

async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    positions = get_positions()
    if not positions:
        await update.message.reply_text("📋 ไม่มี open positions")
        return
    msg = f"📊 <b>Open Positions ({len(positions)})</b>\n\n"
    for p in positions:
        emoji  = "📈" if "BUY" in p.get("type","").upper() else "📉"
        profit = p.get("profit", 0)
        msg += f"{emoji} {p.get('symbol')} | Lot: {p.get('volume')} | P/L: ${profit:.2f}\n"
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_all_trades()
    if not trades:
        await update.message.reply_text("📋 ยังไม่มี trade log")
        return
    msg = "📊 <b>Trade Log ล่าสุด 5 รายการ</b>\n\n"
    for t in trades[:5]:
        emoji = "✅" if t.result == "WIN" else ("❌" if t.result == "LOSS" else "🔄")
        pnl   = f"${t.profit:+.2f}" if t.profit is not None else "open"
        msg  += f"{emoji} {t.direction} | {t.result or 'open'} | {pnl}\n"
        msg  += f"   {t.time.strftime('%d/%m %H:%M')} | Lot: {t.lot}\n\n"
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_weekly_stats()
    await update.message.reply_text(
        f"📊 <b>Weekly Stats (7 วัน)</b>\n\n"
        f"Trades: {stats['total']} | Win: {stats['wins']} | Loss: {stats['losses']}\n"
        f"Win Rate: <b>{stats['win_rate']}%</b>\n"
        f"P/L: <b>${stats['total_pnl']}</b>\n"
        f"Profit Factor: {stats['profit_factor']}",
        parse_mode="HTML"
    )

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("🚀 Scalping Bot starting...")
    send_telegram(
        "🚀 <b>Scalping Bot เริ่มทำงาน</b>\n"
        "Strategy: H1 → M15 → M5\n"
        f"RR: 1:{MIN_RR} | Risk: {RISK_PERCENT}% | Max DD: {MAX_DRAWDOWN}%"
    )

    threading.Thread(target=scan,        daemon=True).start()
    threading.Thread(target=scheduler,   daemon=True).start()
    threading.Thread(target=monitor,     daemon=True).start()
    threading.Thread(target=friday_eod,  daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("pause",     cmd_pause))
    app.add_handler(CommandHandler("resume",    cmd_resume))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("scan",      cmd_scan))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("trades",    cmd_trades))
    app.add_handler(CommandHandler("weekly",    cmd_weekly))

    log.info("✅ Ready!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

# ── OVERRIDE analyze() with SMC strategy ─────────────────────────────────────
def analyze(h1_candles, m15_candles, m5_candles, price):
    bid = price.get("bid", 0)
    if not bid:
        return {"opportunity":"Skip","bias":"Neutral","h1_analysis":"No price",
                "m15_zone":"N/A","m5_signal":"N/A",
                "best_entry":{"direction":"WAIT","entry":"-","sl":"-","tp":"-","rr":"-","confirmation":"No price"},
                "summary":"Cannot analyze without price"}
    result = run_strategy(h1_candles, m15_candles, m5_candles, bid)
    h1, m15, m5 = result["h1_bias"], result["m15_zone"], result["m5_signal"]
    opp = result["opportunity"]
    best_entry = {
        "direction":    m5.signal if m5.signal != "WAIT" else result["direction"],
        "entry":        str(m5.entry) if m5.entry else "-",
        "sl":           str(m5.sl)    if m5.sl    else "-",
        "tp":           str(m5.tp)    if m5.tp    else "-",
        "rr":           f"1:{m5.rr}"  if m5.rr    else f"1:{MIN_RR}",
        "confirmation": m5.reason,
    }
    summary = result["reason"]
    if opp in ["High","Medium"] and m5.signal != "WAIT":
        try:
            resp = claude.messages.create(
                model="claude-sonnet-4-20250514", max_tokens=200,
                messages=[{"role":"user","content":
                    f"สรุปสัญญาณ trading นี้ 1-2 ประโยคภาษาไทย:\n"
                    f"H1: {h1.direction} ({h1.reason})\n"
                    f"M15: {m15.zone_type} zone {m15.zone_low}-{m15.zone_high}\n"
                    f"M5: {m5.pattern} | Entry {m5.entry} SL {m5.sl} TP {m5.tp}"}]
            )
            summary = resp.content[0].text.strip()
        except: pass
    return {
        "opportunity": opp,
        "bias":        h1.direction,
        "h1_analysis": f"{h1.structure} | {h1.reason}",
        "m15_zone":    f"{m15.zone_type} {m15.zone_low}-{m15.zone_high} (x{m15.zone_strength})" if m15.in_zone else m15.reason,
        "m5_signal":   f"{m5.pattern} | {m5.reason}",
        "best_entry":  best_entry,
        "summary":     summary,
    }
