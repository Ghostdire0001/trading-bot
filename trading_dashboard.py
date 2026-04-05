# trading_dashboard.py - Level 2 Enhanced Version
# Features: Multi-Timeframe, Volume, Bollinger Bands, CSV Export

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
import csv
import io

# ========== PERSISTENT DATABASE PATH ==========
DB_PATH = "trading_journal.db"

# ========== TELEGRAM CONFIGURATION ==========
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ========== DATABASE FUNCTIONS ==========
def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            asset_type TEXT,
            signal TEXT,
            price REAL,
            rsi REAL,
            rsi_1h REAL,
            rsi_4h REAL,
            macd REAL,
            sma_20 REAL,
            sma_50 REAL,
            bb_upper REAL,
            bb_lower REAL,
            volume REAL,
            market_regime TEXT,
            confidence TEXT,
            was_accurate TEXT DEFAULT 'pending'
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized")

def log_signal(symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h, macd, sma_20, sma_50, 
               bb_upper, bb_lower, volume, market_regime, confidence="medium"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO signals (timestamp, symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h, 
                           macd, sma_20, sma_50, bb_upper, bb_lower, volume, market_regime, confidence, was_accurate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (dt.now().isoformat(), symbol, asset_type, signal, price, rsi, rsi_1h, rsi_4h, 
          macd, sma_20, sma_50, bb_upper, bb_lower, volume, market_regime, confidence, 'pending'))
    
    conn.commit()
    conn.close()

def get_signal_history(limit=100):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM signals ORDER BY timestamp DESC LIMIT {limit}", conn)
    conn.close()
    return df

def get_signal_statistics():
    conn = sqlite3.connect(DB_PATH)
    signals_df = pd.read_sql_query("SELECT * FROM signals", conn)
    conn.close()
    
    if signals_df.empty:
        return {'total_signals': 0, 'evaluated': 0, 'pending_review': 0, 'accuracy': 0,
                'buy_signals': 0, 'sell_signals': 0, 'forex_signals': 0, 'crypto_signals': 0}
    
    evaluated = signals_df[signals_df['was_accurate'] != 'pending']
    
    if evaluated.empty:
        return {
            'total_signals': len(signals_df),
            'evaluated': 0,
            'pending_review': len(signals_df),
            'accuracy': 0,
            'buy_signals': len(signals_df[signals_df['signal'].str.contains('BUY', na=False)]),
            'sell_signals': len(signals_df[signals_df['signal'].str.contains('SELL', na=False)]),
            'forex_signals': len(signals_df[signals_df['asset_type'] == 'Forex']),
            'crypto_signals': len(signals_df[signals_df['asset_type'] == 'Crypto'])
        }
    
    accurate_count = len(evaluated[evaluated['was_accurate'] == 'yes'])
    total_evaluated = len(evaluated)
    
    return {
        'total_signals': len(signals_df),
        'evaluated': total_evaluated,
        'pending_review': len(signals_df) - total_evaluated,
        'accuracy': (accurate_count / total_evaluated * 100) if total_evaluated > 0 else 0,
        'buy_signals': len(signals_df[signals_df['signal'].str.contains('BUY', na=False)]),
        'sell_signals': len(signals_df[signals_df['signal'].str.contains('SELL', na=False)]),
        'forex_signals': len(signals_df[signals_df['asset_type'] == 'Forex']),
        'crypto_signals': len(signals_df[signals_df['asset_type'] == 'Crypto'])
    }

def update_signal_accuracy(signal_id, was_correct):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE signals SET was_accurate = ? WHERE id = ?', (was_correct, signal_id))
    conn.commit()
    conn.close()

def get_optimal_rsi_threshold():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM signals WHERE was_accurate != 'pending'", conn)
    conn.close()
    
    if df.empty or len(df) < 5:
        return {'buy_threshold': 30, 'sell_threshold': 70, 'confidence': 'low'}
    
    buy_df = df[df['signal'].str.contains('BUY', na=False)]
    if not buy_df.empty:
        accurate_buys = buy_df[buy_df['was_accurate'] == 'yes']
        optimal_buy = accurate_buys['rsi'].mean() if not accurate_buys.empty else 30
    else:
        optimal_buy = 30
    
    sell_df = df[df['signal'].str.contains('SELL', na=False)]
    if not sell_df.empty:
        accurate_sells = sell_df[sell_df['was_accurate'] == 'yes']
        optimal_sell = accurate_sells['rsi'].mean() if not accurate_sells.empty else 70
    else:
        optimal_sell = 70
    
    return {'buy_threshold': round(optimal_buy, 1), 'sell_threshold': round(optimal_sell, 1), 'confidence': 'high' if len(df) > 30 else 'medium'}

init_database()

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(message, parse_mode="HTML"):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return "⚠️ Telegram not configured"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": parse_mode}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return "✅ Message sent!"
        else:
            return f"❌ Error"
    except Exception as e:
        return f"❌ Connection error"

def send_trading_signal(symbol, signal, price, rsi, rsi_1h, rsi_4h, reason=""):
    emoji = "🟢" if "BUY" in signal else ("🔴" if "SELL" in signal else "⚪")
    
    if price < 10:
        price_str = f"{price:.5f}"
    elif price < 1000:
        price_str = f"{price:.4f}"
    else:
        price_str = f"${price:,.2f}"
    
    message = f"""
{emoji} <b>TRADING SIGNAL</b>
━━━━━━━━━━━━━━━━━━━━
<b>Symbol:</b> {symbol}
<b>Signal:</b> {signal}
<b>Price:</b> {price_str}
━━━━━━━━━━━━━━━━━━━━
<b>Multi-Timeframe RSI:</b>
• Daily: {rsi:.1f}
• 4H: {rsi_4h:.1f}
• 1H: {rsi_1h:.1f}
<b>Reason:</b> {reason}
━━━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    return send_telegram_message(message)

# ========== ENHANCED TECHNICAL INDICATORS ==========
def calculate_enhanced_indicators(df):
    """Calculate RSI, MACD, SMA, Bollinger Bands, Volume indicators"""
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Moving Averages
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal']
    
    # Bollinger Bands
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Middle'] + (bb_std * 2)
    df['BB_Lower'] = df['BB_Middle'] - (bb_std * 2)
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle'] * 100
    
    # Volume Indicators
    df['Volume_SMA'] = df['Volume'].rolling(window=20).mean() if 'Volume' in df.columns else 0
    if 'Volume' in df.columns:
        df['Volume_Ratio'] = df['Volume'] / df['Volume_SMA']
    else:
        df['Volume_Ratio'] = 1
    
    # ATR (Volatility)
    high_low = df['High'] - df['Low']
    high_close = abs(df['High'] - df['Close'].shift())
    low_close = abs(df['Low'] - df['Close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = true_range.rolling(window=14).mean()
    
    return df

def generate_multi_timeframe_data(current_price, symbol_name):
    """Generate simulated multi-timeframe data"""
    dates_daily = pd.date_range(end=datetime.now(), periods=60, freq='D')
    dates_4h = pd.date_range(end=datetime.now(), periods=240, freq='4H')
    dates_1h = pd.date_range(end=datetime.now(), periods=720, freq='H')
    
    np.random.seed(hash(symbol_name) % 2**32)
    
    # Daily
    changes_daily = np.random.normal(0, 0.015, 60)
    prices_daily = [current_price]
    for change in changes_daily[1:]:
        prices_daily.append(prices_daily[-1] * (1 + change))
    df_daily = pd.DataFrame({'Date': dates_daily, 'Close': prices_daily})
    df_daily.set_index('Date', inplace=True)
    df_daily = calculate_enhanced_indicators(df_daily)
    
    # 4H (more volatile)
    changes_4h = np.random.normal(0, 0.008, 240)
    prices_4h = [current_price]
    for change in changes_4h[1:]:
        prices_4h.append(prices_4h[-1] * (1 + change))
    df_4h = pd.DataFrame({'Date': dates_4h, 'Close': prices_4h})
    df_4h.set_index('Date', inplace=True)
    df_4h = calculate_enhanced_indicators(df_4h)
    
    # 1H
    changes_1h = np.random.normal(0, 0.005, 720)
    prices_1h = [current_price]
    for change in changes_1h[1:]:
        prices_1h.append(prices_1h[-1] * (1 + change))
    df_1h = pd.DataFrame({'Date': dates_1h, 'Close': prices_1h})
    df_1h.set_index('Date', inplace=True)
    df_1h = calculate_enhanced_indicators(df_1h)
    
    return df_daily, df_4h, df_1h

def get_enhanced_signal(daily, df_4h, df_1h):
    """Generate signal using all timeframes"""
    rsi_daily = daily['RSI'].iloc[-1] if not pd.isna(daily['RSI'].iloc[-1]) else 50
    rsi_4h = df_4h['RSI'].iloc[-1] if not pd.isna(df_4h['RSI'].iloc[-1]) else 50
    rsi_1h = df_1h['RSI'].iloc[-1] if not pd.isna(df_1h['RSI'].iloc[-1]) else 50
    
    macd_daily = daily['MACD'].iloc[-1] if not pd.isna(daily['MACD'].iloc[-1]) else 0
    signal_daily = daily['Signal'].iloc[-1] if not pd.isna(daily['Signal'].iloc[-1]) else 0
    
    bb_lower = daily['BB_Lower'].iloc[-1] if not pd.isna(daily['BB_Lower'].iloc[-1]) else 0
    bb_upper = daily['BB_Upper'].iloc[-1] if not pd.isna(daily['BB_Upper'].iloc[-1]) else 0
    current_price = daily['Close'].iloc[-1]
    
    volume_ratio = daily['Volume_Ratio'].iloc[-1] if not pd.isna(daily['Volume_Ratio'].iloc[-1]) else 1
    
    # Multi-timeframe alignment
    timeframes_aligned = (rsi_daily < 40 and rsi_4h < 40 and rsi_1h < 40) or \
                         (rsi_daily > 60 and rsi_4h > 60 and rsi_1h > 60)
    
    # Strong buy conditions
    if rsi_daily < 30 and rsi_4h < 35 and rsi_1h < 35 and macd_daily > signal_daily:
        confidence = "HIGH"
        signal = "STRONG BUY 🔥"
        reason = f"All timeframes oversold + MACD bullish"
    elif rsi_daily < 30 and rsi_4h < 40 and timeframes_aligned:
        confidence = "HIGH"
        signal = "STRONG BUY 🔥"
        reason = f"Multi-timeframe oversold (D:{rsi_daily:.0f}/4H:{rsi_4h:.0f}/1H:{rsi_1h:.0f})"
    elif rsi_daily < 30:
        confidence = "MEDIUM"
        signal = "BUY 📈"
        reason = f"Daily RSI oversold at {rsi_daily:.1f}"
    
    # Strong sell conditions
    elif rsi_daily > 70 and rsi_4h > 65 and rsi_1h > 65 and macd_daily < signal_daily:
        confidence = "HIGH"
        signal = "STRONG SELL 🔻"
        reason = f"All timeframes overbought + MACD bearish"
    elif rsi_daily > 70 and rsi_4h > 60 and timeframes_aligned:
        confidence = "HIGH"
        signal = "STRONG SELL 🔻"
        reason = f"Multi-timeframe overbought (D:{rsi_daily:.0f}/4H:{rsi_4h:.0f}/1H:{rsi_1h:.0f})"
    elif rsi_daily > 70:
        confidence = "MEDIUM"
        signal = "SELL 📉"
        reason = f"Daily RSI overbought at {rsi_daily:.1f}"
    
    # Bollinger Band signals
    elif current_price <= bb_lower and volume_ratio > 1.5:
        confidence = "MEDIUM"
        signal = "BUY 📈"
        reason = f"Price at lower BB + high volume"
    elif current_price >= bb_upper and volume_ratio > 1.5:
        confidence = "MEDIUM"
        signal = "SELL 📉"
        reason = f"Price at upper BB + high volume"
    
    else:
        confidence = "LOW"
        signal = "HOLD ⏸️"
        reason = "No clear alignment across timeframes"
    
    return signal, rsi_daily, rsi_4h, rsi_1h, macd_daily, signal_daily, bb_upper, bb_lower, volume_ratio, reason, confidence

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

# ========== PAGE SETUP ==========
st.set_page_config(page_title="Trading AI Pro", layout="wide")
st.title("🤖 AI Trading Assistant Pro")
st.caption("🚀 Multi-Timeframe Analysis | Bollinger Bands | Volume Indicators | 24/7 Live")

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
    st.sidebar.success(f"💵 1 USD = {current_price:.4f} {currency}")
else:
    coin_map = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    coin_display = st.sidebar.selectbox("Cryptocurrency", ["BTC", "ETH", "SOL"])
    current_price = get_live_crypto_price(coin_map[coin_display])
    symbol_display = coin_display
    if current_price:
        st.sidebar.success(f"💰 {coin_display} = ${current_price:,.2f}")
    else:
        current_price = 65000 if coin_display == "BTC" else (3500 if coin_display == "ETH" else 150)

risk_percent = st.sidebar.slider("Risk per Trade (%)", 0.5, 3.0, 1.0)
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("📡 **Features:**\n• Multi-Timeframe (Daily/4H/1H)\n• Bollinger Bands\n• Volume Analysis\n• CSV Export")

# ========== GENERATE MULTI-TIMEFRAME DATA ==========
with st.spinner("Analyzing multiple timeframes..."):
    df_daily, df_4h, df_1h = generate_multi_timeframe_data(current_price, symbol_display)

# Get enhanced signal
signal, rsi_daily, rsi_4h, rsi_1h, macd, macd_signal, bb_upper, bb_lower, volume_ratio, reason, confidence = \
    get_enhanced_signal(df_daily, df_4h, df_1h)

# Determine signal color
signal_colors = {"STRONG BUY 🔥": "green", "BUY 📈": "lightgreen", 
                 "STRONG SELL 🔻": "red", "SELL 📉": "salmon", "HOLD ⏸️": "gray"}
signal_color = signal_colors.get(signal, "gray")

# ========== TABS ==========
tab1, tab2, tab3, tab4 = st.tabs(["📊 Trading Dashboard", "📱 Telegram Bot", "📓 Trading Journal", "📥 Export Data"])

# ========== TAB 1: TRADING DASHBOARD ==========
with tab1:
    # Multi-timeframe metrics
    st.subheader("📊 Multi-Timeframe Analysis")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if current_price < 10:
            st.metric("Current Price", f"{current_price:.4f}")
        else:
            st.metric("Current Price", f"${current_price:,.2f}")
    with col2:
        st.metric("Daily RSI", f"{rsi_daily:.1f}")
    with col3:
        st.metric("4H RSI", f"{rsi_4h:.1f}")
    with col4:
        st.metric("1H RSI", f"{rsi_1h:.1f}")
    with col5:
        st.metric("Volume Ratio", f"{volume_ratio:.2f}x")
    
    st.markdown(f"<h2 style='color:{signal_color}; text-align:center;'>{signal}</h2>", unsafe_allow_html=True)
    st.caption(f"**Reason:** {reason} | **Confidence:** {confidence}")
    
    # Multi-timeframe chart
    st.subheader("📈 Multi-Timeframe Chart")
    
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                        subplot_titles=("Daily (RSI: " + f"{rsi_daily:.1f}" + ")", 
                                       "4 Hour (RSI: " + f"{rsi_4h:.1f}" + ")", 
                                       "1 Hour (RSI: " + f"{rsi_1h:.1f}" + ")"))
    
    # Daily chart
    fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['Close'], name='Daily', line=dict(color='white', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['BB_Upper'], name='BB Upper', line=dict(color='gray', width=0.5, dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['BB_Lower'], name='BB Lower', line=dict(color='gray', width=0.5, dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_daily.index, y=df_daily['SMA_20'], name='SMA 20', line=dict(color='orange', width=0.8)), row=1, col=1)
    
    # 4H chart
    fig.add_trace(go.Scatter(x=df_4h.index, y=df_4h['Close'], name='4H', line=dict(color='lightblue', width=1)), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_4h.index, y=df_4h['SMA_20'], name='SMA 20', line=dict(color='orange', width=0.8)), row=2, col=1)
    
    # 1H chart
    fig.add_trace(go.Scatter(x=df_1h.index, y=df_1h['Close'], name='1H', line=dict(color='lightgreen', width=0.8)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df_1h.index, y=df_1h['SMA_20'], name='SMA 20', line=dict(color='orange', width=0.8)), row=3, col=1)
    
    fig.update_layout(height=800, template="plotly_dark", showlegend=False)
    fig.update_xaxes(title_text="Date", row=3, col=1)
    st.plotly_chart(fig, width='stretch')
    
    # Bollinger Bands chart
    st.subheader("📊 Bollinger Bands & Volume")
    
    fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                         row_heights=[0.7, 0.3])
    
    fig2.add_trace(go.Scatter(x=df_daily.index, y=df_daily['Close'], name='Price', line=dict(color='white')), row=1, col=1)
    fig2.add_trace(go.Scatter(x=df_daily.index, y=df_daily['BB_Upper'], name='BB Upper', line=dict(color='red', width=0.8, dash='dash')), row=1, col=1)
    fig2.add_trace(go.Scatter(x=df_daily.index, y=df_daily['BB_Middle'], name='BB Middle', line=dict(color='orange', width=0.8)), row=1, col=1)
    fig2.add_trace(go.Scatter(x=df_daily.index, y=df_daily['BB_Lower'], name='BB Lower', line=dict(color='green', width=0.8, dash='dash')), row=1, col=1)
    
    fig2.add_trace(go.Bar(x=df_daily.index, y=df_daily['Volume_Ratio'], name='Volume Ratio', marker_color='purple'), row=2, col=1)
    fig2.add_hline(y=1, line_dash="dash", line_color="gray", row=2, col=1)
    
    fig2.update_layout(height=500, template="plotly_dark", title="Bollinger Bands with Volume Confirmation")
    st.plotly_chart(fig2, width='stretch')
    
    # RSI Heatmap
    st.subheader("📊 RSI Heatmap - All Timeframes")
    rsi_data = pd.DataFrame({
        'Timeframe': ['Daily', '4H', '1H'],
        'RSI': [rsi_daily, rsi_4h, rsi_1h]
    })
    
    colors = ['green' if x < 30 else ('red' if x > 70 else 'yellow') for x in rsi_data['RSI']]
    fig3 = go.Figure(data=[go.Bar(x=rsi_data['Timeframe'], y=rsi_data['RSI'], 
                                   marker_color=colors, text=rsi_data['RSI'].round(1),
                                   textposition='auto')])
    fig3.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold")
    fig3.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought")
    fig3.update_layout(height=300, template="plotly_dark", title="RSI by Timeframe")
    st.plotly_chart(fig3, width='stretch')

# ========== TAB 2: TELEGRAM BOT ==========
with tab2:
    st.subheader("📱 Telegram Bot")
    
    if TELEGRAM_TOKEN and CHAT_ID:
        st.success("✅ Telegram configured!")
    else:
        st.warning("⚠️ Telegram not configured")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 Send Test Message", use_container_width=True):
            result = send_telegram_message("✅ Trading bot is connected and ready!")
            st.info(result)
    
    with col2:
        if st.button("📤 Send Current Signal", use_container_width=True):
            result = send_trading_signal(symbol_display, signal, current_price, rsi_daily, rsi_4h, rsi_1h, reason)
            st.info(result)
            
            log_signal(symbol_display, asset_type, signal, current_price, rsi_daily, rsi_4h, rsi_1h,
                      macd, df_daily['SMA_20'].iloc[-1], df_daily['SMA_50'].iloc[-1],
                      bb_upper, bb_lower, volume_ratio, "TRENDING" if rsi_daily > 50 else "RANGING", 
                      confidence.lower())
            st.success("📊 Signal logged to database")
    
    st.markdown("---")
    
    st.subheader("🤖 Auto Trading Signals")
    auto_enabled = st.checkbox("Send automatic signals", value=st.session_state['auto_signal'])
    st.session_state['auto_signal'] = auto_enabled
    
    if auto_enabled and TELEGRAM_TOKEN and CHAT_ID:
        st.success("✅ Auto-signals ENABLED")
        
        if signal != "HOLD ⏸️" and signal != st.session_state['last_sent_signal']:
            result = send_trading_signal(symbol_display, signal, current_price, rsi_daily, rsi_4h, rsi_1h, reason)
            st.info(f"Auto-signal sent: {signal}")
            
            log_signal(symbol_display, asset_type, signal, current_price, rsi_daily, rsi_4h, rsi_1h,
                      macd, df_daily['SMA_20'].iloc[-1], df_daily['SMA_50'].iloc[-1],
                      bb_upper, bb_lower, volume_ratio, "TRENDING" if rsi_daily > 50 else "RANGING",
                      confidence.lower())
            
            st.session_state['last_sent_signal'] = signal
        else:
            st.caption(f"📊 Current Signal: {signal}")
    elif auto_enabled:
        st.error("Cannot enable: Telegram not configured")

# ========== TAB 3: TRADING JOURNAL ==========
with tab3:
    st.subheader("📓 Trading Journal")
    
    stats = get_signal_statistics()
    
    if stats and stats['total_signals'] > 0:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Signals", stats['total_signals'])
        with col2:
            accuracy_display = f"{stats['accuracy']:.1f}%" if stats['accuracy'] > 0 else "N/A"
            st.metric("Accuracy", accuracy_display)
        with col3:
            st.metric("Pending Review", stats['pending_review'])
        with col4:
            st.metric("Buy/Sell", f"{stats['buy_signals']}/{stats['sell_signals']}")
        
        optimal = get_optimal_rsi_threshold()
        st.info(f"🧠 **AI Learning:** Optimal Buy RSI: {optimal['buy_threshold']} | Optimal Sell RSI: {optimal['sell_threshold']}")
        
        history = get_signal_history(20)
        if not history.empty:
            display_cols = ['timestamp', 'symbol', 'signal', 'price', 'rsi', 'rsi_4h', 'rsi_1h', 'was_accurate']
            display_df = history[display_cols].head(10]
            display_df.columns = ['Time', 'Symbol', 'Signal', 'Price', 'RSI_D', 'RSI_4H', 'RSI_1H', 'Accuracy']
            st.dataframe(display_df, use_container_width=True)
            
            pending = history[history['was_accurate'] == 'pending']
            if not pending.empty:
                st.subheader("📝 Review Pending Signals")
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
    else:
        st.info("No signals logged yet. Send a signal to start your journal.")

# ========== TAB 4: EXPORT DATA ==========
with tab4:
    st.subheader("📥 Export Trading Data")
    
    st.markdown("""
    ### Export Options
    Download your trading journal data for external analysis in Excel, Google Sheets, or other tools.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        export_limit = st.number_input("Number of records to export", min_value=10, max_value=1000, value=100)
    
    with col2:
        export_format = st.selectbox("Export Format", ["CSV (Excel compatible)", "JSON"])
    
    if st.button("📥 Generate Export File", use_container_width=True):
        history = get_signal_history(export_limit)
        
        if not history.empty:
            # Prepare data for export
            export_df = history.copy()
            export_df = export_df.drop('id', axis=1)
            
            if export_format == "CSV (Excel compatible)":
                csv_data = export_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv_data,
                    file_name=f"trading_journal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            else:
                json_data = export_df.to_json(orient='records', indent=2)
                st.download_button(
                    label="📥 Download JSON",
                    data=json_data,
                    file_name=f"trading_journal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    use_container_width=True
                )
            
            st.success(f"✅ Exported {len(export_df)} records")
            
            # Show preview
            with st.expander("Preview exported data"):
                st.dataframe(export_df.head(10))
        else:
            st.warning("No data to export. Send some signals first!")
    
    st.markdown("---")
    st.subheader("📊 Export Statistics Summary")
    
    stats = get_signal_statistics()
    if stats and stats['total_signals'] > 0:
        summary_data = {
            "Metric": ["Total Signals", "Accuracy Rate", "Buy Signals", "Sell Signals", "Forex Signals", "Crypto Signals"],
            "Value": [stats['total_signals'], f"{stats['accuracy']:.1f}%", stats['buy_signals'], 
                     stats['sell_signals'], stats['forex_signals'], stats['crypto_signals']]
        }
        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df, hide_index=True, use_container_width=True)

# ========== KEEP ALIVE (for Render) ==========
import threading
def keep_alive():
    """Keep the bot alive on Render free tier"""
    while True:
        time.sleep(600)  # Every 10 minutes
        try:
            requests.get("https://trading-bot-u2qk.onrender.com", timeout=5)
            print(f"Keep-alive ping sent at {datetime.now()}")
        except Exception as e:
            print(f"Keep-alive error: {e}")

# Start keep-alive thread only on Render
if os.environ.get("RENDER"):
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()

st.markdown("---")
st.caption("⚠️ Educational purposes only | Multi-Timeframe Analysis | Bollinger Bands | Volume Confirmation")
