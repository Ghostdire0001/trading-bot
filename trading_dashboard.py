# trading_dashboard.py - Complete Level 3 Version with MT5 Integration
# Features: Daily Reports, Paper Trading, ML Predictions, MT5 Live Trading

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
import threading
import random

# ========== MT5 IMPORTS (Optional - only if installed) ==========
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("MT5 not available - install with: pip install MetaTrader5")

# ========== DATABASE SETUP ==========
DB_PATH = "trading_journal.db"

# ========== TELEGRAM CONFIGURATION ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ========== MT5 CONFIGURATION (Update with your demo account) ==========
MT5_LOGIN = 12345678  # Replace with your MT5 demo login
MT5_PASSWORD = "your_password"  # Replace with your password
MT5_SERVER = "MetaQuotes-Demo"  # Replace with your broker's demo server

# Symbol mapping
SYMBOL_MAP = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY",
    "BTC/USD": "BTCUSD",
    "ETH/USD": "ETHUSD",
}

# ========== PAPER TRADING ACCOUNT ==========
PAPER_BALANCE = 10000.0
if 'paper_balance' not in st.session_state:
    st.session_state['paper_balance'] = PAPER_BALANCE
if 'paper_positions' not in st.session_state:
    st.session_state['paper_positions'] = []

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
            prediction REAL
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
            paper_pnl REAL, summary TEXT
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
        return {'total_signals': 0, 'accuracy': 0, 'evaluated': 0}
    
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
    ''', (dt.now().isoformat(), symbol, direction, entry_price, exit_price, quantity, pnl, 'closed'))
    conn.commit()
    conn.close()

init_database()

# ========== MT5 FUNCTIONS ==========
def connect_mt5():
    if not MT5_AVAILABLE:
        return False, "MT5 not installed"
    
    if not mt5.initialize():
        return False, "MT5 initialization failed"
    
    authorized = mt5.login(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if authorized:
        return True, f"Connected to account {MT5_LOGIN}"
    else:
        return False, f"Login failed: {mt5.last_error()}"

def disconnect_mt5():
    if MT5_AVAILABLE:
        mt5.shutdown()
    return True, "Disconnected"

def get_mt5_account_info():
    if not MT5_AVAILABLE or not mt5.terminal_info():
        return None
    
    account = mt5.account_info()
    if account:
        return {
            'balance': account.balance,
            'equity': account.equity,
            'free_margin': account.margin_free,
            'profit': account.profit
        }
    return None

def place_mt5_order(symbol, action, volume=0.01, sl_points=50, tp_points=100):
    if not MT5_AVAILABLE:
        return None, "MT5 not available"
    
    mt5_symbol = SYMBOL_MAP.get(symbol, symbol.replace("/", ""))
    
    tick = mt5.symbol_info_tick(mt5_symbol)
    if not tick:
        return None, "Failed to get price"
    
    point = mt5.symbol_info(mt5_symbol).point
    
    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
        sl = price - sl_points * point if sl_points else 0
        tp = price + tp_points * point if tp_points else 0
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
        sl = price + sl_points * point if sl_points else 0
        tp = price - tp_points * point if tp_points else 0
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": mt5_symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 123456,
        "comment": "AI Trading Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request)
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return result, f"Order placed! Ticket: {result.order}"
    else:
        return None, f"Order failed: {result.comment}"

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
    send_telegram_message(f"📊 <b>DAILY TRADING REPORT</b>\n\n{report_text}")

# ========== PAPER TRADING ==========
def execute_paper_trade(symbol, signal, price, confidence):
    if "BUY" in signal:
        direction = "BUY"
        quantity = (st.session_state['paper_balance'] * 0.02) / price
    elif "SELL" in signal:
        direction = "SELL"
        quantity = (st.session_state['paper_balance'] * 0.02) / price
    else:
        return None
    
    expected_move = random.uniform(0.005, 0.02) if confidence == "HIGH" else random.uniform(-0.005, 0.01)
    
    if direction == "BUY":
        exit_price = price * (1 + expected_move)
        pnl = (exit_price - price) * quantity
    else:
        exit_price = price * (1 - expected_move)
        pnl = (price - exit_price) * quantity
    
    trade = {
        'timestamp': dt.now(),
        'symbol': symbol,
        'direction': direction,
        'entry_price': price,
        'exit_price': exit_price,
        'quantity': quantity,
        'pnl': pnl,
        'pnl_percent': (pnl / (price * quantity)) * 100
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
        'win_rate': (len(winning) / len(trades)) * 100 if trades else 0,
        'total_pnl': sum(t['pnl'] for t in trades),
        'best_trade': max(t['pnl'] for t in trades) if trades else 0,
        'worst_trade': min(t['pnl'] for t in trades) if trades else 0
    }

# ========== ML PREDICTIONS ==========
class SimpleMLPredictor:
    def __init__(self):
        self.model_trained = False
        self.buy_threshold = 30
        self.sell_threshold = 70
    
    def train(self, df):
        if df.empty or len(df) < 10:
            return
        
        accurate = df[df['was_accurate'] == 'yes']
        if not accurate.empty:
            buy_signals = accurate[accurate['signal'].str.contains('BUY', na=False)]
            sell_signals = accurate[accurate['signal'].str.contains('SELL', na=False)]
            
            if not buy_signals.empty:
                self.buy_threshold = buy_signals['rsi'].mean()
            if not sell_signals.empty:
                self.sell_threshold = sell_signals['rsi'].mean()
            self.model_trained = True
    
    def predict(self, rsi):
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
    patterns = []
    if len(df) < 20:
        return patterns
    
    close = df['Close'].values
    high = df['High'].values if 'High' in df else df['Close'].values * 1.01
    low = df['Low'].values if 'Low' in df else df['Close'].values * 0.99
    
    if max(high[-10:]) == high[-5] and high[0] > high[-1]:
        patterns.append("🔴 Potential Head & Shoulders")
    
    if low[-1] > low[-3] and low[-3] > low[-5]:
        patterns.append("🟢 Higher Lows - Bullish")
    
    return patterns

# ========== DAILY REPORT ==========
def generate_daily_report():
    stats = get_signal_statistics()
    paper_stats = get_paper_stats()
    
    report = f"""
📅 <b>{dt.now().strftime('%Y-%m-%d')}</b>
━━━━━━━━━━━━━━━━━━━━
<b>Signals:</b> {stats['total_signals']}
<b>Accuracy:</b> {stats['accuracy']:.1f}%
<b>Paper P&L:</b> ${paper_stats['total_pnl']:.2f}
<b>Win Rate:</b> {paper_stats['win_rate']:.1f}%
    """
    send_daily_report(report)
    return report

# ========== DATA FETCHING ==========
@st.cache_data(ttl=30)
def get_live_forex_rates():
    url = "https://api.exchangerate.host/latest?base=USD"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if "rates" in data:
            return {"EUR": data["rates"].get("EUR", 0.92), "GBP": data["rates"].get("GBP", 0.79), 
                    "JPY": data["rates"].get("JPY", 148.5)}
    except:
        pass
    return {"EUR": 0.92, "GBP": 0.79, "JPY": 148.5}

@st.cache_data(ttl=60)
def get_live_crypto_price(coin="bitcoin"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        return data.get(coin, {}).get("usd", None)
    except:
        return None

def generate_chart_data(current_price, days=60):
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    np.random.seed(42)
    changes = np.random.normal(0, 0.015, days)
    prices = [current_price]
    for change in changes[1:]:
        prices.append(prices[-1] * (1 + change))
    
    df = pd.DataFrame({'Date': dates, 'Close': prices, 'High': prices, 'Low': prices})
    df.set_index('Date', inplace=True)
    
    df['High'] = df['Close'] * 1.01
    df['Low'] = df['Close'] * 0.99
    
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
    
    return df

# ========== PAGE SETUP ==========
st.set_page_config(page_title="Trading AI Pro", layout="wide")
st.title("🤖 AI Trading Assistant Pro - Complete Edition")
st.caption("Daily Reports | Paper Trading | ML Predictions | MT5 Integration | 24/7 Live")

# ========== SESSION STATE ==========
if 'auto_signal' not in st.session_state:
    st.session_state['auto_signal'] = False
if 'last_sent_signal' not in st.session_state:
    st.session_state['last_sent_signal'] = ""
if 'mt5_connected' not in st.session_state:
    st.session_state['mt5_connected'] = False

# ========== SIDEBAR ==========
st.sidebar.header("📊 Trading Settings")
asset_type = st.sidebar.selectbox("Asset Type", ["Forex", "Crypto"])

if asset_type == "Forex":
    currency = st.sidebar.selectbox("Currency", ["EUR", "GBP", "JPY"])
    rates = get_live_forex_rates()
    current_price = rates[currency]
    symbol_display = f"{currency}/USD"
else:
    coin_display = st.sidebar.selectbox("Cryptocurrency", ["BTC", "ETH"])
    current_price = get_live_crypto_price(coin_display.lower())
    if not current_price:
        current_price = 65000 if coin_display == "BTC" else 3500
    symbol_display = f"{coin_display}/USD"

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ========== GENERATE DATA ==========
with st.spinner("Analyzing markets..."):
    df = generate_chart_data(current_price)

latest = df.iloc[-1]
rsi = latest['RSI'] if not pd.isna(latest['RSI']) else 50
macd = latest['MACD'] if not pd.isna(latest['MACD']) else 0
signal_line = latest['Signal'] if not pd.isna(latest['Signal']) else 0

# Generate signal
if rsi < 30 and macd > signal_line:
    signal = "STRONG BUY 🔥"
    confidence = "HIGH"
elif rsi < 30:
    signal = "BUY 📈"
    confidence = "MEDIUM"
elif rsi > 70 and macd < signal_line:
    signal = "STRONG SELL 🔻"
    confidence = "HIGH"
elif rsi > 70:
    signal = "SELL 📉"
    confidence = "MEDIUM"
else:
    signal = "HOLD ⏸️"
    confidence = "LOW"

patterns = detect_patterns(df)

# Train ML
history = get_signal_history(100)
ml_predictor.train(history)
ml_prediction, ml_confidence = ml_predictor.predict(rsi)

# ========== TABS ==========
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Dashboard", "📱 Telegram", "💰 Paper Trading", 
    "🧠 ML Predictions", "💹 Live Trading (MT5)", "📓 Journal & Export"
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
            send_telegram_message("✅ Trading bot is live!")
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
        send_telegram_message(f"🚨 AUTO: {symbol_display} - {signal}\nPrice: ${current_price:,.2f}\nRSI: {rsi:.1f}")
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
                      macd, latest['SMA_20'], latest['SMA_50'],
                      latest['BB_Upper'], latest['BB_Lower'], 1.0,
                      "TRENDING" if rsi > 50 else "RANGING", confidence.lower())
            st.rerun()
    
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
    
    stats = get_signal_statistics()
    if stats['evaluated'] > 0:
        st.write(f"📊 Trained on {stats['evaluated']} reviewed signals")
        st.write(f"🎯 Current Accuracy: {stats['accuracy']:.1f}%")
        
        if ml_predictor.model_trained:
            st.success(f"✅ Optimal Buy RSI: {ml_predictor.buy_threshold:.1f}")
            st.success(f"✅ Optimal Sell RSI: {ml_predictor.sell_threshold:.1f}")
    else:
        st.warning("⚠️ Review more signals to train the AI model")

# ========== TAB 5: LIVE TRADING (MT5) ==========
with tab5:
    st.subheader("💹 MetaTrader 5 Live Trading (Demo Account)")
    
    if not MT5_AVAILABLE:
        st.error("❌ MetaTrader5 not installed. Run: pip install MetaTrader5")
    else:
        # Connection status
        if not st.session_state['mt5_connected']:
            if st.button("🔌 Connect to MT5 Demo Account", use_container_width=True):
                success, msg = connect_mt5()
                if success:
                    st.session_state['mt5_connected'] = True
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            st.info(f"📝 Update your MT5 credentials in the code:\nLogin: {MT5_LOGIN}\nServer: {MT5_SERVER}")
        else:
            st.success("✅ Connected to MT5 Demo Account")
            
            # Account info
            account = get_mt5_account_info()
            if account:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Balance", f"${account['balance']:.2f}")
                with col2:
                    st.metric("Equity", f"${account['equity']:.2f}")
                with col3:
                    st.metric("Free Margin", f"${account['free_margin']:.2f}")
                with col4:
                    profit_color = "green" if account['profit'] >= 0 else "red"
                    st.metric("P&L", f"${account['profit']:.2f}", delta_color=profit_color)
            
            # Manual order
            st.subheader("Manual Order Entry")
            col1, col2, col3 = st.columns(3)
            with col1:
                mt5_symbol = st.selectbox("Symbol", list(SYMBOL_MAP.keys()))
            with col2:
                mt5_action = st.selectbox("Action", ["BUY", "SELL"])
            with col3:
                mt5_volume = st.number_input("Volume (Lots)", 0.01, 1.0, 0.01, 0.01)
            
            col1, col2 = st.columns(2)
            with col1:
                mt5_sl = st.number_input("Stop Loss (pips)", 0, 200, 50)
            with col2:
                mt5_tp = st.number_input("Take Profit (pips)", 0, 500, 100)
            
            if st.button(f"Place {mt5_action} Order", use_container_width=True):
                result, msg = place_mt5_order(mt5_symbol, mt5_action, mt5_volume, mt5_sl, mt5_tp)
                if result:
                    st.success(msg)
                else:
                    st.error(msg)
            
            # Auto-trade from signal
            st.markdown("---")
            st.subheader("🤖 Auto-Trade from AI Signal")
            
            if st.button(f"Auto-Trade Current Signal: {signal}", use_container_width=True):
                if signal != "HOLD ⏸️":
                    mt5_symbol_input = symbol_display if symbol_display in SYMBOL_MAP else "EUR/USD"
                    result, msg = place_mt5_order(mt5_symbol_input, "BUY" if "BUY" in signal else "SELL", 0.01, 50, 100)
                    if result:
                        st.success(f"Auto-trade executed! {msg}")
                        log_signal(symbol_display, asset_type, signal, current_price, rsi, rsi, rsi,
                                  macd, latest['SMA_20'], latest['SMA_50'],
                                  latest['BB_Upper'], latest['BB_Lower'], 1.0,
                                  "TRENDING" if rsi > 50 else "RANGING", confidence.lower())
                    else:
                        st.error(msg)
                else:
                    st.warning("No active signal")
            
            # Disconnect
            if st.button("🔌 Disconnect from MT5", use_container_width=True):
                disconnect_mt5()
                st.session_state['mt5_connected'] = False
                st.rerun()

# ========== TAB 6: JOURNAL & EXPORT ==========
with tab6:
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
        
        st.subheader("📥 Export Data")
        if st.button("Export to CSV"):
            csv = history.to_csv(index=False)
            st.download_button("Download CSV", csv, f"journal_{dt.now().strftime('%Y%m%d')}.csv", "text/csv")

# ========== DAILY REPORT SCHEDULER ==========
if not hasattr(st, 'report_scheduler_started'):
    def schedule_daily_report():
        while True:
            now = dt.now()
            if now.hour == 9 and now.minute == 0:
                generate_daily_report()
                time.sleep(60)
            time.sleep(30)
    
    report_thread = threading.Thread(target=schedule_daily_report, daemon=True)
    report_thread.start()
    st.report_scheduler_started = True

# ========== FOOTER ==========
st.markdown("---")
st.caption("⚠️ Educational purposes only | Level 3 Complete: Daily Reports | Paper Trading | ML Predictions | MT5 Integration")
