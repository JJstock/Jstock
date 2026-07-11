import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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



if selected_ticker:
    stock = yf.Ticker(selected_ticker)
    df = stock.history(period="3mo")
    
    # 計算 MA
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # 建立雙子圖：row_heights 設定上方佔 70%，下方佔 30%
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, subplot_titles=(f'{selected_ticker} 走勢', '成交量'),
                        row_heights=[0.7, 0.3])

    # 1. 加入蠟燭圖 (上方)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], 
                                 low=df['Low'], close=df['Close'], name='股價'), row=1, col=1)
    
    # 2. 加入均線 (上方)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='red', width=1.5), name='MA20'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='blue', width=1.5), name='MA60'), row=1, col=1)

    # 3. 加入成交量長條圖 (下方)
    # 用顏色區分漲跌：收盤 > 開盤為紅色(漲)，反之為綠色(跌)
    colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='成交量'), row=2, col=1)

    # 4. 版面設定
    fig.update_layout(xaxis_rangeslider_visible=False, height=600, showlegend=False)
    
    st.plotly_chart(fig, use_container_width=True)
