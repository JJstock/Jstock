import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="個人股價監控")
st.title("📊 個人股票 MA20 與財報監控")

# 設定股票清單與名稱
my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光"}

def get_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    df = stock.history(period="1mo")
    
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    return {
        "現價": price,
        "MA20": ma20,
        "Current PE": info.get('trailingPE', 'N/A'),
        "Forward PE": info.get('forwardPE', 'N/A')
    }

# 建立表格顯示
data_list = []
for symbol, name in my_stocks.items():
    d = get_data(symbol)
    d['名稱'] = name
    data_list.append(d)

df_view = pd.DataFrame(data_list).set_index('名稱')
st.table(df_view.style.format("{:.2f}")) # 自動保留兩位小數