import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="個人股價監控", layout="wide")
st.title("📊 個人股價與財報監控")

my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光","2303.TW": "聯電", "2327.TW": "國巨", "2383.TW": "台光電", "2345.TW":"智邦","3037.TW": "欣興"}

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    df = stock.history(period="6mo")
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    t_pe = info.get('trailingPE', 0)
    t_eps = info.get('trailingEps', 0)
    return {"現價": price, "MA20": ma20, "狀態": "低於" if price < ma20 else "高於",
            "Trailing (PE/EPS)": f"{t_pe:.2f} (EPS: {t_eps:.2f})"}, df

st.subheader("📋 監控清單總覽")
data_list = []
for symbol, name in my_stocks.items():
    try:
        d, _ = get_stock_data(symbol)
        d['名稱'] = name
        data_list.append(d)
    except: continue

df_view = pd.DataFrame(data_list).set_index('名稱')
st.dataframe(df_view)

st.divider()
selected_ticker = st.selectbox("請選擇股票", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])

if selected_ticker:
    stock = yf.Ticker(selected_ticker)
    df = stock.history(period="3mo")
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close']), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], name='MA60'), row=1, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='成交量'), row=2, col=1)
    fig.update_layout(height=600, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
