import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="個人股價監控")
st.title("📊 個人股票 MA20 與財報監控")

# 設定股票清單與名稱
my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光"}

# 1. 取得歷史資料的函數
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="1mo")
    return df  # 直接回傳 df

# 2. 網頁顯示邏輯
st.title("📈 個股趨勢監控")

selected_ticker = st.selectbox("請選擇股票", ["2330.TW", "2454.TW", "2317.TW"])

if selected_ticker:
    df = get_stock_data(selected_ticker)
    
    # 計算 MA20 方便對比
    df['MA20'] = df['Close'].rolling(window=20).mean()
    
    # 畫圖：只取 'Close' 和 'MA20' 這兩欄位繪製
    st.line_chart(df[['Close', 'MA20']])
    
    st.write("最新數據：", df.iloc[-1][['Close', 'MA20']])
    
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
