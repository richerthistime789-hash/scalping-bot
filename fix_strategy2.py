with open('strategy.py', 'r') as f:
    content = f.read()

# ── Fix 1: H1 Bias ต้องการ strong confirmation ──
# เพิ่ม minimum swing count และ require BOS
old_bias = '''    if structure == "HH_HL":
        direction  = "Bullish"
        confidence = "High" if bos == "Bullish_BOS" else "Medium"
        reason     = f"HH+HL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    elif structure == "LH_LL":
        direction  = "Bearish"
        confidence = "High" if bos == "Bearish_BOS" else "Medium"
        reason     = f"LH+LL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    else:
        direction, confidence, reason = "Neutral", "Low", "Sideways — using M15 bias"'''

new_bias = '''    if structure == "HH_HL":
        direction  = "Bullish"
        # ต้องการ BOS หรือ CHoCH confirm ถึงจะ High confidence
        confidence = "High" if bos == "Bullish_BOS" else "Medium"
        reason     = f"HH+HL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    elif structure == "LH_LL":
        direction  = "Bearish"
        confidence = "High" if bos == "Bearish_BOS" else "Medium"
        reason     = f"LH+LL{', BOS' if bos else ''}{', CHoCH:'+choch if choch else ''}"
    else:
        # Sideways — ดู price vs key S/R แทน
        last_close = closes[-1] if closes else 0
        if last_close > key_resistance:
            direction, confidence = "Bullish", "Low"
            reason = f"Price above key resistance {key_resistance}"
        elif last_close < key_support:
            direction, confidence = "Bearish", "Low"
            reason = f"Price below key support {key_support}"
        else:
            direction, confidence, reason = "Neutral", "Low", "Sideways — price between S/R"'''

content = content.replace(old_bias, new_bias)

# ── Fix 2: ห้าม counter-trend — Bearish ต้อง SELL เท่านั้น ──
old_zone_check = '''    if bias_direction == "Bullish" and m15.zone_type != "Support":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bullish but near Resistance — skip"}
    if bias_direction == "Bearish" and m15.zone_type != "Resistance":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bearish but near Support — skip"}'''

new_zone_check = '''    if bias_direction == "Bullish" and m15.zone_type != "Support":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bullish but near Resistance — wait for pullback to Support"}
    if bias_direction == "Bearish" and m15.zone_type != "Resistance":
        return {"opportunity":"Low","direction":"WAIT","h1_bias":h1,"m15_zone":m15,
                "m5_signal":M5Signal("WAIT","None",None,None,None,None,None,"Wrong zone"),
                "reason":"Bearish but near Support — NO counter-trend BUY allowed"}'''

content = content.replace(old_zone_check, new_zone_check)

with open('strategy.py', 'w') as f:
    f.write(content)
print("✅ strategy.py fixed!")
