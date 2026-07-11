import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="個人股價監控", layout="wide")
st.title("📊 個人股票 MA20 與財報監控")

# 設定股票清單
my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光"}

# 取得資料函數 (整合版)
@st.cache_data(ttl=3600) # 快取一小時，避免重複請求太慢
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    df = stock.history(period="1mo")
    
    # 計算指標
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    return {
        "現價": price,
        "MA20": ma20,
        "Current PE": info.get('trailingPE', 0),
        "Forward PE": info.get('forwardPE', 0)
    }, df

# --- 1. 顯示總覽表格 ---
st.subheader("📋 監控清單總覽")
data_list = []
for symbol, name in my_stocks.items():
    d, df = get_stock_data(symbol)
    d['名稱'] = name
    data_list.append(d)

df_view = pd.DataFrame(data_list).set_index('名稱')
st.table(df_view.style.format("{:.2f}"))

# --- 2. 個別趨勢圖 ---
st.divider()
st.subheader("📈 個股趨勢圖")
selected_ticker = st.selectbox("請選擇股票查看趨勢", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])

if selected_ticker:
    _, df = get_stock_data(selected_ticker)
    df['MA20'] = df['Close'].rolling(window=20).mean()
    st.line_chart(df[['Close', 'MA20']])
