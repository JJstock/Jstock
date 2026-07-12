import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gc

# 1. 頁面設定
st.set_page_config(page_title="個人股價監控", layout="wide")
st.title("JStok 📊 MA20+60 與財報監控")

my_stocks = {
    "2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", 
    "2317.TW": "鴻海", "3711.TW": "日月光", "2303.TW": "聯電", 
    "2327.TW": "國巨", "2383.TW": "台光電", "2345.TW": "智邦", "3037.TW": "欣興"
}

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    gc.collect()
    stock = yf.Ticker(ticker)
    try:
        info = stock.info
    except:
        info = {}
    
    df = stock.history(period="6mo")
    if df.empty:
        return None, None
        
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    # 確保資料存在，若為 None 則給予 0
    t_pe = info.get('trailingPE') or 0
    t_eps = info.get('trailingEps') or 0
    f_pe = info.get('forwardPE') or 0
    f_eps = info.get('forwardEps') or 0
    
    return {
        "現價": f"{price:.2f}", # 這裡改為字串格式化
        "MA20": f"{ma20:.2f}", # 同樣處理 MA20
        "狀態": "⚠️低於" if price < ma20 else "✅高於",
        "Trailing (PE/EPS)": f"{t_pe:.2f} (EPS: {t_eps:.2f})",
        "Forward (PE/EPS)": f"{f_pe:.2f} (EPS: {f_eps:.2f})"
    }, df

# --- 總覽表格 ---
st.subheader("📋 監控清單總覽")
data_list = []
for symbol, name in my_stocks.items():
    d, _ = get_stock_data(symbol)
    if d:
        d['名稱'] = name
        data_list.append(d)

if data_list:
    st.dataframe(pd.DataFrame(data_list).set_index('名稱'), width='stretch')

st.divider()

# --- 個別趨勢圖 (成交量顏色 + 跳過假日) ---
st.subheader("📈 個股趨勢圖")
selected_ticker = st.selectbox("請選擇股票", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])

if selected_ticker:
    stock = yf.Ticker(selected_ticker)
    df = stock.history(period="3mo")
    
    if not df.empty:
        # 1. 數據前處理
        df['Volume'] = df['Volume'].fillna(0)
        df['Date_Str'] = df.index.strftime('%Y-%m-%d')
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        
        # 2. 精確的量價動能顏色邏輯 (Vectorized 向量運算)
        import numpy as np
        # 比較當日收盤與前一日收盤
        prev_close = df['Close'].shift(1)
        conditions = [
            (df['Close'] > prev_close), # 紅色：今日比昨日高
            (df['Close'] < prev_close)  # 綠色：今日比昨日低
        ]
        choices = ['#EF553B', '#00CC96']
        # 產生顏色序列，預設灰色
        volume_colors = np.select(conditions, choices, default='#7F7F7F').tolist()
        
        # 3. 建立雙子圖
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        # 4. 繪製蠟燭圖 (漲紅跌綠)
        fig.add_trace(go.Candlestick(
            x=df['Date_Str'], open=df['Open'], high=df['High'], 
            low=df['Low'], close=df['Close'], name='股價',
            increasing_line_color='#EF553B', decreasing_line_color='#00CC96'
        ), row=1, col=1)
        
        # 5. 繪製均線
        fig.add_trace(go.Scatter(x=df['Date_Str'], y=df['MA20'], name='MA20', line=dict(color='red', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['Date_Str'], y=df['MA60'], name='MA60', line=dict(color='blue', width=1.5)), row=1, col=1)
        
        # 6. 繪製成交量
        fig.add_trace(go.Bar(x=df['Date_Str'], y=df['Volume'], name='成交量', marker_color=volume_colors), row=2, col=1)
        
        # 7. 版面設定
        fig.update_layout(
            height=600, showlegend=False, xaxis_rangeslider_visible=False,
            xaxis=dict(type='category', showticklabels=False),
            xaxis2=dict(type='category', tickangle=45)
        )
        
        st.plotly_chart(fig, width='stretch')
    else:
        st.warning("目前無該個股歷史成交數據。")
