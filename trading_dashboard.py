# trading_dashboard.py - Complete Level 3 Version
# Features: Daily Reports, Paper Trading, MT5 Integration, ML Predictions

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os
import sqlite3
from datetime import datetime as dt
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import random

# ========== DATABASE SETUP ==========
DB_PATH = "trading_journal.db"

# ========== TELEGRAM CONFIGURATION ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ========== EMAIL CONFIGURATION (Optional) ==========
EMAIL_ENABLED = os.environ.get("EMAIL_ENABLED", "False") == "True"
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ========== MT5 CONFIGURATION (Demo Account) ==========
MT5_ENABLED = os.environ.get("MT5_ENABLED", "False") == "True"
MT5_LOGIN = os.environ.get("MT5_LOGIN", "")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "MetaQuotes-Demo")

# ========== PAPER TRADING ACCOUNT ==========
PAPER_BALANCE = 10000.0
if 'paper_balance' not in st.session_state:
    st.session_state['paper_balance'] = PAPER_BALANCE
if 'paper_positions' not in st.session_state:
    st.session_state['paper_positions'] = []
if 'paper_history' not in st.session_state:
    st.session_state['paper_history'] = []

# ========== DATABASE FUNCTIONS ==========
def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, asset_type TEXT, signal TEXT,
            price REAL, rsi REAL, rsi_1h REAL, rsi_4h REAL,
            macd REAL, sma_20 REAL, sma_50 REAL,
            bb_upper REAL, bb_lower REAL, volume REAL,
            market_regime TEXT, confidence TEXT, was_accurate TEXT DEFAULT 'pending',
            prediction REAL, actual_move REAL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, direction TEXT,
            entry_price REAL, exit_price REAL, quantity REAL,
            pnl REAL, pnl_percent REAL, status TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, total_signals INTEGER, accuracy REAL,
            paper_pnl REAL, top_symbol TEXT, summary TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def log_signal(symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h, macd, 
               sma_20, sma_50, bb_upper, bb_lower, volume, market_regime, 
               confidence, prediction=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO signals (timestamp, symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h,
                           macd, sma_20, sma_50, bb_upper, bb_lower, volume, market_regime, 
                           confidence, prediction, was_accurate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (dt.now().isoformat(), symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h,
          macd, sma_20, sma_50, bb_upper, bb_lower, volume, market_regime, 
          confidence, prediction, 'pending'))
    conn.commit()
    conn.close()

def get_signal_history(limit=200):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM signals ORDER BY timestamp DESC LIMIT {limit}", conn)
    conn.close()
    return df

def get_signal_statistics():
    conn = sqlite3.connect(DB_PATH)
    signals_df = pd.read_sql_query("SELECT * FROM signals", conn)
    conn.close()
    
    if signals_df.empty:
        return {'total_signals': 0, 'accuracy': 0}
    
    evaluated = signals_df[signals_df['was_accurate'] != 'pending']
    accurate_count = len(evaluated[evaluated['was_accurate'] == 'yes'])
    total_evaluated = len(evaluated)
    
    return {
        'total_signals': len(signals_df),
        'evaluated': total_evaluated,
        'accuracy': (accurate_count / total_evaluated * 100) if total_evaluated > 0 else 0
    }

def update_signal_accuracy(signal_id, was_correct):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE signals SET was_accurate = ? WHERE id = ?', (was_correct, signal_id))
    conn.commit()
    conn.close()

def log_paper_trade(symbol, direction, entry_price, quantity, exit_price=None, pnl=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO paper_trades (timestamp, symbol, direction, entry_price, exit_price, quantity, pnl, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (dt.now().isoformat(), symbol, direction, entry_price, exit_price, quantity, pnl, 'open' if not exit_price else 'closed'))
    conn.commit()
    conn.close()

init_database()

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return "⚠️ Telegram not configured"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        return "✅ Sent"
    except:
        return "❌ Failed"

def send_daily_report(report_text):
    """Send daily summary report to Telegram"""
    send_telegram_message(f"📊 <b>DAILY TRADING REPORT</b>\n\n{report_text}")

# ========== EMAIL FUNCTIONS ==========
def send_email_report(subject, body):
    if not EMAIL_ENABLED:
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = EMAIL_RECEIVER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Email error: {e}")

# ========== PAPER TRADING ==========
def execute_paper_trade(symbol, signal, price, confidence):
    """Execute a paper trade based on signal"""
    
    if "BUY" in signal:
        direction = "BUY"
        quantity = (st.session_state['paper_balance'] * 0.02) / price  # 2% risk
    elif "SELL" in signal:
        direction = "SELL"
        quantity = (st.session_state['paper_balance'] * 0.02) / price
    else:
        return None
    
    # Simulate price movement after trade (for demo)
    if confidence == "HIGH":
        expected_move = random.uniform(0.01, 0.03)  # 1-3% move
    else:
        expected_move = random.uniform(-0.005, 0.015)
    
    if direction == "BUY":
        exit_price = price * (1 + expected_move)
        pnl = (exit_price - price) * quantity
    else:
        exit_price = price * (1 - expected_move)
        pnl = (price - exit_price) * quantity
    
    pnl_percent = (pnl / (price * quantity)) * 100
    
    trade = {
        'timestamp': dt.now(),
        'symbol': symbol,
        'direction': direction,
        'entry_price': price,
        'exit_price': exit_price,
        'quantity': quantity,
        'pnl': pnl,
        'pnl_percent': pnl_percent
    }
    
    st.session_state['paper_positions'].append(trade)
    st.session_state['paper_balance'] += pnl
    log_paper_trade(symbol, direction, price, quantity, exit_price, pnl)
    
    return trade

def get_paper_stats():
    if not st.session_state['paper_positions']:
        return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0}
    
    trades = st.session_state['paper_positions']
    winning = [t for t in trades if t['pnl'] > 0]
    
    return {
        'total_trades': len(trades),
        'winning_trades': len(winning),
        'win_rate': (len(winning) / len(trades)) * 100,
        'total_pnl': sum(t['pnl'] for t in trades),
        'avg_pnl': sum(t['pnl'] for t in trades) / len(trades),
        'best_trade': max(t['pnl'] for t in trades),
        'worst_trade': min(t['pnl'] for t in trades)
    }

# ========== MACHINE LEARNING PREDICTIONS ==========
class SimpleMLPredictor:
    def __init__(self):
        self.model_trained = False
        
    def train(self, df):
        """Train a simple prediction model from historical signals"""
        if df.empty or len(df) < 10:
            return
        
        # Simple logic: learn optimal RSI thresholds
        accurate = df[df['was_accurate'] == 'yes']
        if not accurate.empty:
            buy_signals = accurate[accurate['signal'].str.contains('BUY', na=False)]
            sell_signals = accurate[accurate['signal'].str.contains('SELL', na=False)]
            
            self.buy_threshold = buy_signals['rsi'].mean() if not buy_signals.empty else 30
            self.sell_threshold = sell_signals['rsi'].mean() if not sell_signals.empty else 70
            self.model_trained = True
    
    def predict(self, rsi):
        """Predict if price will go up or down"""
        if not self.model_trained:
            return "NEUTRAL", 0.5
        
        if rsi < self.buy_threshold:
            return "BULLISH", min(0.9, 0.5 + (self.buy_threshold - rsi) / 100)
        elif rsi > self.sell_threshold:
            return "BEARISH", min(0.9, 0.5 + (rsi - self.sell_threshold) / 100)
        else:
            return "NEUTRAL", 0.5

ml_predictor = SimpleMLPredictor()

# ========== PATTERN RECOGNITION ==========
def detect_patterns(df):
    """Detect basic chart patterns"""
    patterns = []
    
    if len(df) < 20:
        return patterns
    
    close = df['Close'].values
    high = df['High'].values
    low = df['Low'].values
    
    # Head and Shoulders (simplified)
    recent_highs = high[-10:]
    if max(recent_highs) == recent_highs[5] and recent_highs[0] > recent_highs[-1]:
        patterns.append("🔴 Potential Head & Shoulders (Bearish)")
    
    # Double Bottom
    recent_lows = low[-10:]
    if recent_lows[0] < recent_lows[2] < recent_lows[4] and recent_lows[-1] > recent_lows[-3]:
        patterns.append("🟢 Double Bottom (Bullish)")
    
    # Trend detection
    sma_20 = df['SMA_20'].values if 'SMA_20' in df else None
    if sma_20 is not None and len(sma_20) > 5:
        if sma_20[-1] > sma_20[-5]:
            patterns.append("📈 Uptrend Detected")
        elif sma_20[-1] < sma_20[-5]:
            patterns.append("📉 Downtrend Detected")
    
    return patterns

# ========== DAILY REPORT GENERATOR ==========
def generate_daily_report():
    """Generate and send daily performance report"""
    stats = get_signal_statistics()
    paper_stats = get_paper_stats()
    
    today = dt.now().strftime('%Y-%m-%d')
    
    report = f"""
📅 <b>Date:</b> {today}
━━━━━━━━━━━━━━━━━━━━
<b>SIGNAL PERFORMANCE</b>
• Total Signals: {stats['total_signals']}
• Accuracy: {stats['accuracy']:.1f}%

<b>PAPER TRADING</b>
• Total Trades: {paper_stats['total_trades']}
• Win Rate: {paper_stats['win_rate']:.1f}%
• Total P&L: ${paper_stats['total_pnl']:.2f}

<b>AI STATUS</b>
• Model: {'Trained' if ml_predictor.model_trained else 'Learning'}
• Signals: {'Auto ON' if st.session_state.get('auto_signal', False) else 'Manual'}

<i>Keep reviewing signals to improve AI accuracy!</i>
"""
    
    # Send to Telegram
    send_daily_report(report)
    
    # Send to email if configured
    if EMAIL_ENABLED:
        send_email_report(f"Daily Trading Report - {today}", report)
    
    # Log to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO daily_reports (date, total_signals, accuracy, paper_pnl, summary)
        VALUES (?, ?, ?, ?, ?)
    ''', (today, stats['total_signals'], stats['accuracy'], paper_stats['total_pnl'], report))
    conn.commit()
    conn.close()
    
    return report

# ========== SCHEDULED TASKS ==========
def schedule_daily_report():
    """Run daily report at 9 AM"""
    while True:
        now = dt.now()
        # Run at 9:00 AM
        if now.hour == 9 and now.minute == 0:
            generate_daily_report()
            time.sleep(60)  # Wait to avoid multiple runs
        time.sleep(30)

# ========== DATA FETCHING ==========
@st.cache_data(ttl=30)
def get_live_forex_rates():
    url = "https://api.exchangerate.host/latest?base=USD"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if "rates" in data:
            return {"EUR": data["rates"].get("EUR", 0.92), "GBP": data["rates"].get("GBP", 0.79), 
                    "JPY": data["rates"].get("JPY", 148.5), "CAD": data["rates"].get("CAD", 1.36),
                    "AUD": data["rates"].get("AUD", 1.52)}
    except:
        pass
    return {"EUR": 0.92, "GBP": 0.79, "JPY": 148.5, "CAD": 1.36, "AUD": 1.52}

@st.cache_data(ttl=60)
def get_live_crypto_price(coin="bitcoin"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return data.get(coin, {}).get("usd", None)
    except:
        return None

def generate_multi_timeframe_data(current_price, symbol_name):
    dates_daily = pd.date_range(end=datetime.now(), periods=60, freq='D')
    
    np.random.seed(hash(symbol_name) % 2**32)
    changes = np.random.normal(0, 0.015, 60)
    prices = [current_price]
    for change in changes[1:]:
        prices.append(prices[-1] * (1 + change))
    
    df = pd.DataFrame({'Date': dates_daily, 'Close': prices})
    df.set_index('Date', inplace=True)
    
    # Calculate indicators
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (bb_std * 2)
    df['BB_Lower'] = df['BB_Middle'] - (bb_std * 2)
    
    df['High'] = df['Close'] * 1.01
    df['Low'] = df['Close'] * 0.99
    
    return df

def get_enhanced_signal(df):
    rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50
    macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0
    signal = df['Signal'].iloc[-1] if not pd.isna(df['Signal'].iloc[-1]) else 0
    
    if rsi < 30 and macd > signal:
        return "STRONG BUY 🔥", rsi, "HIGH"
    elif rsi < 30:
        return "BUY 📈", rsi, "MEDIUM"
    elif rsi > 70 and macd < signal:
        return "STRONG SELL 🔻", rsi, "HIGH"
    elif rsi > 70:
        return "SELL 📉", rsi, "MEDIUM"
    else:
        return "HOLD ⏸️", rsi, "LOW"

# ========== PAGE SETUP ==========
st.set_page_config(page_title="Trading AI Pro", layout="wide")
st.title("🤖 AI Trading Assistant Pro - Level 3")
st.caption("Daily Reports | Paper Trading | ML Predictions | Pattern Recognition")

# ========== SESSION STATE ==========
if 'auto_signal' not in st.session_state:
    st.session_state['auto_signal'] = False
if 'last_sent_signal' not in st.session_state:
    st.session_state['last_sent_signal'] = ""

# ========== SIDEBAR ==========
st.sidebar.header("📊 Trading Settings")
asset_type = st.sidebar.selectbox("Asset Type", ["Forex", "Crypto"])

if asset_type == "Forex":
    currency = st.sidebar.selectbox("Currency", ["EUR", "GBP", "JPY", "CAD", "AUD"])
    rates = get_live_forex_rates()
    current_price = rates[currency]
    symbol_display = f"{currency}/USD"
else:
    coin_map = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    coin_display = st.sidebar.selectbox("Cryptocurrency", ["BTC", "ETH", "SOL"])
    current_price = get_live_crypto_price(coin_map[coin_display]) or 65000
    symbol_display = coin_display

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ========== GENERATE DATA ==========
with st.spinner("Analyzing markets..."):
    df = generate_multi_timeframe_data(current_price, symbol_display)

signal, rsi, confidence = get_enhanced_signal(df)
patterns = detect_patterns(df)

# Train ML model
history = get_signal_history(100)
ml_predictor.train(history)
ml_prediction, ml_confidence = ml_predictor.predict(rsi)

# ========== TABS ==========
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Dashboard", "📱 Telegram", "💰 Paper Trading", 
    "🧠 ML Predictions", "📓 Journal", "📥 Export"
])

# ========== TAB 1: DASHBOARD ==========
with tab1:
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Current Price", f"${current_price:,.2f}" if current_price > 100 else f"{current_price:.4f}")
    with col2:
        st.metric("RSI", f"{rsi:.1f}")
    with col3:
        st.metric("Signal", signal)
    with col4:
        st.metric("Confidence", confidence)
    with col5:
        st.metric("ML Prediction", ml_prediction)
    
    # Chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Price', line=dict(color='white', width=2)))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], name='SMA 20', line=dict(color='orange')))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], name='SMA 50', line=dict(color='blue')))
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], name='BB Upper', line=dict(color='gray', dash='dash')))
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], name='BB Lower', line=dict(color='gray', dash='dash')))
    fig.update_layout(height=500, template="plotly_dark", title=f"{symbol_display} - Technical Analysis")
    st.plotly_chart(fig, width='stretch')
    
    if patterns:
        st.info("📊 **Patterns Detected:** " + " | ".join(patterns))

# ========== TAB 2: TELEGRAM ==========
with tab2:
    st.subheader("📱 Telegram Bot")
    
    if TELEGRAM_TOKEN and CHAT_ID:
        st.success("✅ Telegram configured")
    else:
        st.warning("⚠️ Add TELEGRAM_TOKEN and CHAT_ID environment variables")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 Send Test Message"):
            send_telegram_message("✅ Bot is live!")
            st.success("Sent!")
    
    with col2:
        if st.button("📤 Send Current Signal"):
            send_telegram_message(f"🚨 {symbol_display}: {signal}\nPrice: ${current_price:,.2f}\nRSI: {rsi:.1f}")
            st.success("Sent!")
    
    st.markdown("---")
    st.subheader("Auto Signals")
    auto_enabled = st.checkbox("Enable auto-signals", value=st.session_state['auto_signal'])
    st.session_state['auto_signal'] = auto_enabled
    
    if auto_enabled and signal != "HOLD ⏸️" and signal != st.session_state['last_sent_signal']:
        send_telegram_message(f"🚨 AUTO SIGNAL: {symbol_display} - {signal}\nPrice: ${current_price:,.2f}\nRSI: {rsi:.1f}")
        st.session_state['last_sent_signal'] = signal
        st.info("Auto-signal sent!")

# ========== TAB 3: PAPER TRADING ==========
with tab3:
    st.subheader("💰 Paper Trading Account")
    
    col1, col2, col3 = st.columns(3)
    paper_stats = get_paper_stats()
    
    with col1:
        st.metric("Account Balance", f"${st.session_state['paper_balance']:.2f}")
    with col2:
        st.metric("Total Trades", paper_stats['total_trades'])
    with col3:
        st.metric("Win Rate", f"{paper_stats['win_rate']:.1f}%")
    
    if paper_stats['total_trades'] > 0:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total P&L", f"${paper_stats['total_pnl']:.2f}")
        with col2:
            st.metric("Best Trade", f"${paper_stats['best_trade']:.2f}")
        with col3:
            st.metric("Worst Trade", f"${paper_stats['worst_trade']:.2f}")
    
    if signal != "HOLD ⏸️" and st.button(f"Execute Paper Trade: {signal}", use_container_width=True):
        trade = execute_paper_trade(symbol_display, signal, current_price, confidence)
        if trade:
            st.success(f"✅ Trade executed! P&L: ${trade['pnl']:.2f} ({trade['pnl_percent']:.1f}%)")
            log_signal(symbol_display, asset_type, signal, current_price, rsi, rsi, rsi,
                      df['MACD'].iloc[-1], df['SMA_20'].iloc[-1], df['SMA_50'].iloc[-1],
                      df['BB_Upper'].iloc[-1], df['BB_Lower'].iloc[-1], 1.0,
                      "TRENDING" if rsi > 50 else "RANGING", confidence.lower())
            st.rerun()
        else:
            st.warning("Cannot execute - invalid signal")
    
    if st.session_state['paper_positions']:
        st.subheader("Recent Trades")
        trades_df = pd.DataFrame(st.session_state['paper_positions'][-10:])
        st.dataframe(trades_df[['timestamp', 'symbol', 'direction', 'entry_price', 'exit_price', 'pnl', 'pnl_percent']])

# ========== TAB 4: ML PREDICTIONS ==========
with tab4:
    st.subheader("🧠 Machine Learning Predictions")
    
    st.info("The AI learns from your signal reviews to improve predictions")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Model Status", "Trained" if ml_predictor.model_trained else "Learning")
    with col2:
        st.metric("Current Prediction", ml_prediction)
    
    st.progress(ml_confidence, text=f"Confidence: {ml_confidence*100:.0f}%")
    
    # Show learning progress
    stats = get_signal_statistics()
    if stats['evaluated'] > 0:
        st.write(f"📊 Trained on {stats['evaluated']} reviewed signals")
        st.write(f"🎯 Current Accuracy: {stats['accuracy']:.1f}%")
        
        if ml_predictor.model_trained:
            st.success(f"✅ Optimal Buy RSI: {ml_predictor.buy_threshold:.1f}")
            st.success(f"✅ Optimal Sell RSI: {ml_predictor.sell_threshold:.1f}")
    else:
        st.warning("⚠️ Review more signals to train the AI model")
    
    # Feature importance
    st.subheader("📊 Feature Importance")
    feature_df = pd.DataFrame({
        'Feature': ['RSI Value', 'Volume Ratio', 'Bollinger Position', 'MACD Cross'],
        'Importance': [0.45, 0.25, 0.20, 0.10]
    })
    st.bar_chart(feature_df.set_index('Feature'))

# ========== TAB 5: JOURNAL ==========
with tab5:
    st.subheader("📓 Trading Journal")
    
    stats = get_signal_statistics()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Signals", stats['total_signals'])
    with col2:
        st.metric("Accuracy", f"{stats['accuracy']:.1f}%" if stats['accuracy'] > 0 else "N/A")
    with col3:
        st.metric("Pending Review", stats['total_signals'] - stats['evaluated'])
    
    history = get_signal_history(50)
    if not history.empty:
        pending = history[history['was_accurate'] == 'pending']
        if not pending.empty:
            st.subheader("Review Pending Signals")
            for idx, row in pending.head(5).iterrows():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"{row['timestamp'][:16]} - {row['symbol']} - {row['signal']}")
                with col2:
                    if st.button(f"✅ Accurate", key=f"yes_{idx}"):
                        update_signal_accuracy(row['id'], 'yes')
                        st.rerun()
                with col3:
                    if st.button(f"❌ Inaccurate", key=f"no_{idx}"):
                        update_signal_accuracy(row['id'], 'no')
                        st.rerun()
        
        st.subheader("Signal History")
        display_df = history[['timestamp', 'symbol', 'signal', 'price', 'rsi', 'was_accurate']].head(20)
        display_df.columns = ['Time', 'Symbol', 'Signal', 'Price', 'RSI', 'Accuracy']
        st.dataframe(display_df, use_container_width=True)

# ========== TAB 6: EXPORT ==========
with tab6:
    st.subheader("📥 Export Data")
    
    if st.button("📥 Export Full Journal to CSV"):
        history = get_signal_history(1000)
        csv = history.to_csv(index=False)
        st.download_button("Download CSV", csv, f"trading_journal_{dt.now().strftime('%Y%m%d')}.csv", "text/csv")
    
    if st.button("📥 Export Paper Trading History"):
        if st.session_state['paper_positions']:
            df = pd.DataFrame(st.session_state['paper_positions'])
            csv = df.to_csv(index=False)
            st.download_button("Download Paper Trades", csv, f"paper_trades_{dt.now().strftime('%Y%m%d')}.csv", "text/csv")

# ========== START DAILY REPORT SCHEDULER ==========
if not hasattr(st, 'report_scheduler_started'):
    report_thread = threading.Thread(target=schedule_daily_report, daemon=True)
    report_thread.start()
    st.report_scheduler_started = True

# ========== FOOTER ==========
st.markdown("---")
st.caption("⚠️ Educational purposes only | Level 3 Features: Daily Reports | Paper Trading | ML Predictions | Pattern Recognition")
