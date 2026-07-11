import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="個人股價監控", layout="wide")
st.title("📊 個人股票 MA20 與財報監控")

my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光","2303.TW": "聯電", "2327.TW": "國巨", "2383.TW": "台光電", "2345.TW":"智邦","3037.TW": "欣興"}

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    df = stock.history(period="1mo")
    
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    # 修正欄位名稱：yfinance 的 info 欄位通常是 trailingEps (注意大小寫)
    return {
        "現價": price,
        "MA20": ma20,
        "狀態": "低於" if price < ma20 else "高於",
        "Trailing PE": info.get('trailingPE', 0),
        "Trailing EPS": info.get('trailingEps', 0),
        "Forward PE": info.get('forwardPE', 0),
        "Forward EPS": info.get('forwardEps', 0)
    }, df

# --- 1. 顯示總覽表格 ---
st.subheader("📋 監控清單總覽")
data_list = []
for symbol, name in my_stocks.items():
    try:
        d, _ = get_stock_data(symbol)
        d['名稱'] = name
        data_list.append(d)
    except:
        continue

df_view = pd.DataFrame(data_list).set_index('名稱')

# 透過 styler 將「高於」設為綠色，「低於」設為紅色
def color_status(val):
    color = 'red' if val == '低於' else 'green'
    return f'color: {color}'

st.dataframe(df_view.style.map(color_status, subset=['狀態']).format("{:.2f}", subset=["現價", "MA20", "Trailing PE", "Trailing EPS", "Forward PE", "Forward EPS"]))

# --- 2. 個別趨勢圖 ---
st.divider()
st.subheader("📈 個股趨勢圖")
selected_ticker = st.selectbox("請選擇股票查看趨勢", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])

if selected_ticker:
    _, df = get_stock_data(selected_ticker)
    df['MA20'] = df['Close'].rolling(window=20).mean()
    st.line_chart(df[['Close', 'MA20']])
