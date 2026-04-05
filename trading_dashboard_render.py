# trading_dashboard_render.py - Render Cloud Version

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time
import os
import sqlite3
from datetime import datetime as dt

# ========== PERSISTENT DATABASE PATH ==========
# Render provides persistent storage
DB_PATH = "trading_journal.db"

# ========== TELEGRAM CONFIGURATION ==========
# Get from environment variables (set in Render dashboard)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

# ========== DATABASE FUNCTIONS ==========
def init_database():
    """Create database tables if they don't exist"""
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
            macd REAL,
            sma_20 REAL,
            sma_50 REAL,
            market_regime TEXT,
            confidence TEXT,
            was_accurate TEXT DEFAULT 'pending'
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")

def log_signal(symbol, asset_type, signal, price, rsi, macd, sma_20, sma_50, market_regime, confidence="medium"):
    """Log a trading signal to the database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signals (timestamp, symbol, asset_type, signal, price, rsi, macd, sma_20, sma_50, market_regime, confidence, was_accurate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (dt.now().isoformat(), symbol, asset_type, signal, price, rsi, macd, sma_20, sma_50, market_regime, confidence, 'pending'))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error logging signal: {e}")
        return False

def get_signal_history(limit=50):
    """Get recent signals"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM signals ORDER BY timestamp DESC LIMIT {limit}", conn)
    conn.close()
    return df

def get_signal_statistics():
    """Calculate performance statistics"""
    conn = sqlite3.connect(DB_PATH)
    signals_df = pd.read_sql_query("SELECT * FROM signals", conn)
    conn.close()
    
    if signals_df.empty:
        return {
            'total_signals': 0,
            'evaluated': 0,
            'pending_review': 0,
            'accuracy': 0,
            'buy_signals': 0,
            'sell_signals': 0,
            'forex_signals': 0,
            'crypto_signals': 0
        }
    
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
    """Update signal accuracy"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE signals SET was_accurate = ? WHERE id = ?', (was_correct, signal_id))
    conn.commit()
    conn.close()

def get_optimal_rsi_threshold():
    """Analyze past signals for optimal RSI levels"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM signals WHERE was_accurate != 'pending'", conn)
    conn.close()
    
    if df.empty or len(df) < 5:
        return {'buy_threshold': 30, 'sell_threshold': 70, 'confidence': 'low'}
    
    buy_df = df[df['signal'].str.contains('BUY', na=False)]
    if not buy_df.empty:
        accurate_buys = buy_df[buy_df['was_accurate'] == 'yes']
        if not accurate_buys.empty:
            optimal_buy = accurate_buys['rsi'].mean()
        else:
            optimal_buy = 30
    else:
        optimal_buy = 30
    
    sell_df = df[df['signal'].str.contains('SELL', na=False)]
    if not sell_df.empty:
        accurate_sells = sell_df[sell_df['was_accurate'] == 'yes']
        if not accurate_sells.empty:
            optimal_sell = accurate_sells['rsi'].mean()
        else:
            optimal_sell = 70
    else:
        optimal_sell = 70
    
    return {
        'buy_threshold': round(optimal_buy, 1),
        'sell_threshold': round(optimal_sell, 1),
        'confidence': 'high' if len(df) > 30 else 'medium'
    }

# Initialize database
init_database()

# ========== TELEGRAM FUNCTIONS ==========
def send_telegram_message(message, parse_mode="HTML"):
    """Send a message to your Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return "⚠️ Telegram not configured. Add TELEGRAM_TOKEN and CHAT_ID environment variables."
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": parse_mode}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return "✅ Message sent to Telegram!"
        else:
            error_data = response.json()
            return f"❌ Error: {error_data.get('description', 'Unknown error')}"
    except Exception as e:
        return f"❌ Connection error: {str(e)}"

def send_trading_signal(symbol, signal, price, rsi, reason=""):
    """Format and send a trading signal alert"""
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
<b>RSI:</b> {rsi:.1f}
<b>Reason:</b> {reason}
━━━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    return send_telegram_message(message)

# ========== PAGE SETUP ==========
st.set_page_config(page_title="Trading AI Cloud", layout="wide")
st.title("🤖 AI Trading Assistant (Render Cloud)")
st.caption("🚀 Running 24/7 on Render.com | Database: SQLite")

# ========== SESSION STATE ==========
if 'auto_signal' not in st.session_state:
    st.session_state['auto_signal'] = False
if 'last_sent_rsi' not in st.session_state:
    st.session_state['last_sent_rsi'] = 50

# ========== DATA FETCHING ==========
@st.cache_data(ttl=30)
def get_live_forex_rates():
    url = "https://api.exchangerate.host/latest?base=USD"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        if "rates" in data:
            return {"EUR": data["rates"].get("EUR", 0.92), "GBP": data["rates"].get("GBP", 0.79), "JPY": data["rates"].get("JPY", 148.5)}
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

def generate_chart_data(current_price, days=50):
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    np.random.seed(42)
    changes = np.random.normal(0, 0.015, days)
    prices = [current_price]
    for change in changes[1:]:
        prices.append(prices[-1] * (1 + change))
    
    df = pd.DataFrame({'Date': dates, 'Close': prices})
    df.set_index('Date', inplace=True)
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Moving Averages
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    return df

def get_trading_signal(row):
    if pd.isna(row['RSI']):
        return "WAITING", "gray"
    if row['RSI'] < 30 and row['MACD'] > row['Signal']:
        return "STRONG BUY 🔥", "green"
    elif row['RSI'] < 30:
        return "BUY 📈", "lightgreen"
    elif row['RSI'] > 70 and row['MACD'] < row['Signal']:
        return "STRONG SELL 🔻", "red"
    elif row['RSI'] > 70:
        return "SELL 📉", "salmon"
    else:
        return "HOLD ⏸️", "gray"

# ========== SIDEBAR ==========
st.sidebar.header("📊 Trading Settings")
asset_type = st.sidebar.selectbox("Asset Type", ["Forex", "Crypto"])

if asset_type == "Forex":
    currency = st.sidebar.selectbox("Currency", ["EUR", "GBP", "JPY"])
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
st.sidebar.info("📡 Data: exchangerate.host + CoinGecko")

# ========== GENERATE DATA ==========
with st.spinner("Loading market data..."):
    df = generate_chart_data(current_price, 60)

latest = df.iloc[-1]
signal, signal_color = get_trading_signal(latest)

# ========== TABS ==========
tab1, tab2, tab3 = st.tabs(["📊 Trading Dashboard", "📱 Telegram Bot", "📓 Trading Journal"])

# ========== TAB 1: TRADING DASHBOARD ==========
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if current_price < 10:
            st.metric("Current Price", f"{current_price:.4f}")
        else:
            st.metric("Current Price", f"${current_price:,.2f}")
    with col2:
        st.metric("RSI (14)", f"{latest['RSI']:.1f}")
    with col3:
        st.markdown(f"<h3 style='color:{signal_color}'>{signal}</h3>", unsafe_allow_html=True)
    with col4:
        st.metric("Risk Setting", f"{risk_percent}%")
    
    # Chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name='Price', line=dict(color='white', width=2)))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], name='SMA 20', line=dict(color='orange', width=1)))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], name='SMA 50', line=dict(color='blue', width=1)))
    fig.update_layout(title=f"{asset_type}: {symbol_display}", height=500, template="plotly_dark", xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, width='stretch')
    
    # RSI Chart
    fig_rsi = go.Figure()
    fig_rsi.add_trace(go.Scatter(x=df.index, y=df['RSI'], name='RSI', line=dict(color='purple')))
    fig_rsi.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought")
    fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold")
    fig_rsi.update_layout(height=200, template="plotly_dark")
    st.plotly_chart(fig_rsi, width='stretch')

# ========== TAB 2: TELEGRAM BOT ==========
with tab2:
    st.subheader("📱 Telegram Bot")
    
    # Show config status
    if TELEGRAM_TOKEN and CHAT_ID:
        st.success("✅ Telegram configured!")
    else:
        st.warning("⚠️ Telegram not configured. Add TELEGRAM_TOKEN and CHAT_ID environment variables in Render dashboard.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📤 Send Test Message", use_container_width=True):
            if TELEGRAM_TOKEN and CHAT_ID:
                result = send_telegram_message("✅ Trading bot is connected and ready on Render!")
                if "✅" in result:
                    st.success(result)
                else:
                    st.error(result)
            else:
                st.error("Please configure Telegram environment variables first")
    
    with col2:
        if st.button("📤 Send Current Signal", use_container_width=True):
            if TELEGRAM_TOKEN and CHAT_ID:
                result = send_trading_signal(symbol_display, signal, current_price, latest['RSI'], f"Current RSI: {latest['RSI']:.1f}")
                if "✅" in result:
                    st.success(result)
                else:
                    st.error(result)
                
                log_signal(symbol_display, asset_type, signal, current_price, latest['RSI'], 
                          latest['MACD'], latest['SMA_20'], latest['SMA_50'], 
                          "TRENDING" if latest['RSI'] > 50 else "RANGING", "medium")
                st.info("📊 Signal logged to database")
            else:
                st.error("Please configure Telegram environment variables first")
    
    st.markdown("---")
    
    st.subheader("🤖 Auto Trading Signals")
    auto_enabled = st.checkbox("Send automatic signals", value=st.session_state['auto_signal'])
    st.session_state['auto_signal'] = auto_enabled
    
    if auto_enabled:
        if TELEGRAM_TOKEN and CHAT_ID:
            st.success("✅ Auto-signals ENABLED")
            current_rsi = latest['RSI']
            
            if (current_rsi < 30 or current_rsi > 70) and abs(current_rsi - st.session_state['last_sent_rsi']) > 5:
                if current_rsi < 30:
                    signal_type = "STRONG BUY 🔥" if current_rsi < 25 else "BUY 📈"
                    reason = f"RSI oversold at {current_rsi:.1f}"
                else:
                    signal_type = "STRONG SELL 🔻" if current_rsi > 75 else "SELL 📉"
                    reason = f"RSI overbought at {current_rsi:.1f}"
                
                result = send_trading_signal(symbol_display, signal_type, current_price, current_rsi, reason)
                st.info(f"Signal sent: {signal_type}")
                
                log_signal(symbol_display, asset_type, signal_type, current_price, current_rsi,
                          latest['MACD'], latest['SMA_20'], latest['SMA_50'],
                          "TRENDING" if current_rsi > 50 else "RANGING", "high" if "STRONG" in signal_type else "medium")
                
                st.session_state['last_sent_rsi'] = current_rsi
            else:
                st.caption(f"📊 Current RSI: {current_rsi:.1f} | Last signal RSI: {st.session_state['last_sent_rsi']:.1f}")
        else:
            st.error("Cannot enable auto-signals: Telegram not configured")

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
            display_df = history[['timestamp', 'symbol', 'signal', 'price', 'rsi', 'was_accurate']].head(10)
            display_df.columns = ['Time', 'Symbol', 'Signal', 'Price', 'RSI', 'Accuracy']
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

st.markdown("---")
st.caption("⚠️ Educational purposes only. Not financial advice. Running 24/7 on Render.com")
