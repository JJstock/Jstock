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
    df = stock.history(period="6mo")
    
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    # 取得原始值
    t_pe = info.get('trailingPE', 0)
    t_eps = info.get('trailingEps', 0)
    f_pe = info.get('forwardPE', 0)
    f_eps = info.get('forwardEps', 0)
    
    return {
        "現價": price,
        "MA20": ma20,
        "狀態": "低於" if price < ma20 else "高於",
        # 合併顯示
        "Trailing (PE/EPS)": f"{t_pe:.2f}  (EPS: {t_eps:.2f})",
        "Forward (PE/EPS)": f"{f_pe:.2f}  (EPS: {f_eps:.2f})"
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

def color_status(val):
    color = 'red' if val == '低於' else 'green'
    return f'color: {color}'

# 只對數值欄位進行 format，合併後的文字欄位交給原始字串內容
st.dataframe(
    df_view.style
    .map(color_status, subset=['狀態'])
    .format("{:.2f}", subset=["現價", "MA20"])
)

# --- 2. 個別趨勢圖 (加入 MA60) ---
st.divider()
st.subheader("📈 個股趨勢圖 (MA20 vs MA60)")
selected_ticker = st.selectbox("請選擇股票查看趨勢", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])

import altair as alt

if selected_ticker:
    stock = yf.Ticker(selected_ticker)
    df = stock.history(period="6mo")
    
    # 計算均線
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # 準備繪圖資料：將資料轉為長格式 (Long format)
    df_melt = df[['Close', 'MA20', 'MA60']].tail(90).reset_index()
    df_melt = df_melt.melt('Date', var_name='Type', value_name='Price')
    
    # 繪製圖表
    chart = alt.Chart(df_melt).mark_line().encode(
        x='Date:T',
        y='Price:Q',
        color=alt.Color('Type', scale=alt.Scale(
            domain=['Close', 'MA20', 'MA60'],
            range=['#333333', 'red', 'blue'] # 自訂顏色：股價黑、MA20紅、MA60藍
        ))
    ).properties(width=700, height=400)
    
    st.altair_chart(chart, use_container_width=True)
