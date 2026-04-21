"""
database.py — Trade log + Performance stats
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

BKK     = ZoneInfo("Asia/Bangkok")
DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")
engine  = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Base    = declarative_base()
Session = sessionmaker(bind=engine)


class Trade(Base):
    __tablename__ = "trades"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    time         = Column(DateTime, default=datetime.now)
    symbol       = Column(String)
    name         = Column(String)
    direction    = Column(String)
    lot          = Column(Float)
    entry        = Column(Float)
    sl           = Column(Float)
    tp           = Column(Float)
    risk_usd     = Column(Float)
    equity       = Column(Float)
    opportunity  = Column(String)
    order_id     = Column(String)
    session      = Column(String,  nullable=True)   # London / NY / Asian
    htf_analysis = Column(String,  nullable=True)   # analysis reason
    closed       = Column(Boolean, default=False)
    close_price  = Column(Float,   nullable=True)
    profit       = Column(Float,   nullable=True)
    result       = Column(String,  nullable=True)   # WIN / LOSS / BE


Base.metadata.create_all(engine)


# ── Write ──────────────────────────────────────────────────────────────────
def save_trade(trade_dict: dict) -> Trade:
    session = Session()
    try:
        t = Trade(
            time         = datetime.strptime(trade_dict["time"], "%Y-%m-%d %H:%M"),
            symbol       = trade_dict["symbol"],
            name         = trade_dict["name"],
            direction    = trade_dict["direction"],
            lot          = trade_dict["lot"],
            entry        = trade_dict.get("entry", 0),
            sl           = trade_dict["sl"],
            tp           = trade_dict["tp"],
            risk_usd     = trade_dict.get("risk_usd", 0),
            equity       = trade_dict.get("equity", 0),
            opportunity  = trade_dict.get("opportunity", ""),
            order_id     = trade_dict.get("order_id", "N/A"),
            session      = trade_dict.get("session", ""),
            htf_analysis = trade_dict.get("htf_analysis", ""),
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        return t
    finally:
        session.close()


def update_trade_result(trade_id: int, close_price: float, profit: float, result: str):
    session = Session()
    try:
        t = session.query(Trade).filter(Trade.id == trade_id).first()
        if t:
            t.closed      = True
            t.close_price = close_price
            t.profit      = profit
            t.result      = result
            session.commit()
    finally:
        session.close()


# ── Read ───────────────────────────────────────────────────────────────────
def get_all_trades():
    session = Session()
    try:
        return session.query(Trade).order_by(Trade.time.desc()).all()
    finally:
        session.close()


def get_daily_pnl() -> float:
    """P/L วันนี้ (Bangkok time) — trades ที่ปิดแล้ว"""
    session = Session()
    try:
        now_bkk   = datetime.now(BKK)
        start_bkk = now_bkk.replace(hour=0, minute=0, second=0, microsecond=0)
        since     = start_bkk.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        trades    = session.query(Trade).filter(
            Trade.time >= since,
            Trade.closed == True
        ).all()
        return round(sum(t.profit or 0 for t in trades), 2)
    finally:
        session.close()


def get_daily_trade_count() -> int:
    """จำนวน trade ที่เปิดวันนี้ (Bangkok time)"""
    session = Session()
    try:
        now_bkk   = datetime.now(BKK)
        start_bkk = now_bkk.replace(hour=0, minute=0, second=0, microsecond=0)
        since     = start_bkk.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        return session.query(Trade).filter(Trade.time >= since).count()
    finally:
        session.close()


def get_recent_losses(n: int) -> int:
    """นับ consecutive losses จาก n trade ล่าสุดที่ปิดแล้ว"""
    session = Session()
    try:
        trades = (session.query(Trade)
                  .filter(Trade.closed == True)
                  .order_by(Trade.time.desc())
                  .limit(n).all())
        count = 0
        for t in trades:
            if t.result == "LOSS":
                count += 1
            else:
                break
        return count
    finally:
        session.close()


def get_performance_by_session() -> dict:
    """Win rate และ P/L แยกตาม session"""
    session = Session()
    try:
        trades = session.query(Trade).filter(Trade.closed == True).all()
        result = {}
        for t in trades:
            s = t.session or "Unknown"
            if s not in result:
                result[s] = {"total": 0, "wins": 0, "pnl": 0.0}
            result[s]["total"] += 1
            result[s]["pnl"]   += t.profit or 0
            if t.result == "WIN":
                result[s]["wins"] += 1
        for s in result:
            total = result[s]["total"]
            result[s]["win_rate"] = round(result[s]["wins"] / total * 100, 1) if total > 0 else 0
            result[s]["pnl"]      = round(result[s]["pnl"], 2)
        return result
    finally:
        session.close()


def get_performance_by_direction() -> dict:
    """Win rate และ P/L แยกตาม BUY/SELL"""
    session = Session()
    try:
        trades = session.query(Trade).filter(Trade.closed == True).all()
        result = {"BUY": {"total":0,"wins":0,"pnl":0.0}, "SELL": {"total":0,"wins":0,"pnl":0.0}}
        for t in trades:
            d = t.direction or "BUY"
            if d not in result:
                result[d] = {"total":0,"wins":0,"pnl":0.0}
            result[d]["total"] += 1
            result[d]["pnl"]   += t.profit or 0
            if t.result == "WIN":
                result[d]["wins"] += 1
        for d in result:
            total = result[d]["total"]
            result[d]["win_rate"] = round(result[d]["wins"] / total * 100, 1) if total > 0 else 0
            result[d]["pnl"]      = round(result[d]["pnl"], 2)
        return result
    finally:
        session.close()


def get_performance_by_opportunity() -> dict:
    """Win rate และ P/L แยกตาม High/Medium/Low"""
    session = Session()
    try:
        trades = session.query(Trade).filter(Trade.closed == True).all()
        result = {}
        for t in trades:
            o = t.opportunity or "Unknown"
            if o not in result:
                result[o] = {"total":0,"wins":0,"pnl":0.0}
            result[o]["total"] += 1
            result[o]["pnl"]   += t.profit or 0
            if t.result == "WIN":
                result[o]["wins"] += 1
        for o in result:
            total = result[o]["total"]
            result[o]["win_rate"] = round(result[o]["wins"] / total * 100, 1) if total > 0 else 0
            result[o]["pnl"]      = round(result[o]["pnl"], 2)
        return result
    finally:
        session.close()


def get_weekly_stats() -> dict:
    session = Session()
    try:
        since  = datetime.now() - timedelta(days=7)
        trades = session.query(Trade).filter(Trade.time >= since).all()
        total  = len(trades)
        closed = [t for t in trades if t.closed]
        wins   = [t for t in closed if t.result == "WIN"]
        losses = [t for t in closed if t.result == "LOSS"]
        win_rate      = (len(wins) / len(closed) * 100) if closed else 0
        total_pnl     = sum(t.profit or 0 for t in closed)
        avg_win       = (sum(t.profit or 0 for t in wins)   / len(wins))   if wins   else 0
        avg_loss      = (sum(t.profit or 0 for t in losses) / len(losses)) if losses else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        return {
            "total": total, "closed": len(closed), "open": total - len(closed),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
        }
    finally:
        session.close()


def get_monthly_stats() -> dict:
    session = Session()
    try:
        since  = datetime.now() - timedelta(days=30)
        trades = session.query(Trade).filter(Trade.time >= since).all()
        closed = [t for t in trades if t.closed]
        wins   = [t for t in closed if t.result == "WIN"]
        losses = [t for t in closed if t.result == "LOSS"]
        win_rate  = (len(wins) / len(closed) * 100) if closed else 0
        total_pnl = sum(t.profit or 0 for t in closed)
        return {
            "total": len(trades), "closed": len(closed),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
        }
    finally:
        session.close()
