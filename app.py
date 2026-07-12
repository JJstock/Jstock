import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import gc

st.set_page_config(page_title="Jstok股價監控", layout="wide")
st.title("JStok 📊 MA20+60 與財報監控")

# --- 繪圖函式 ---
def plot_stock_chart(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="6mo")
    if not df.empty:
        df['Volume'] = df['Volume'].fillna(0)
        df['Date_Str'] = df.index.strftime('%Y-%m-%d')
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        
        prev_close = df['Close'].shift(1)
        conditions = [(df['Close'] > prev_close), (df['Close'] < prev_close)]
        choices = ['#EF553B', '#00CC96']
        volume_colors = np.select(conditions, choices, default='#7F7F7F').tolist()
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=df['Date_Str'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='股價', increasing_line_color='#EF553B', decreasing_line_color='#00CC96'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['Date_Str'], y=df['MA20'], name='MA20', line=dict(color='red', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['Date_Str'], y=df['MA60'], name='MA60', line=dict(color='blue', width=1.5)), row=1, col=1)
        fig.add_trace(go.Bar(x=df['Date_Str'], y=df['Volume'], name='成交量', marker_color=volume_colors), row=2, col=1)
        fig.update_layout(height=600, showlegend=False, xaxis_rangeslider_visible=False, xaxis=dict(type='category', showticklabels=False), xaxis2=dict(type='category', tickangle=45))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("無數據")

# --- 資料抓取函式 ---
@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    gc.collect()
    stock = yf.Ticker(ticker)
    info = stock.info if stock.info else {}
    df = stock.history(period="6mo")
    if df.empty: return None, None
    
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    price = df['Close'].iloc[-1]
    
    # 修正 f-string 引號衝突
    status = f"⚠️低於MA20 ({ma20:.2f})" if price < ma20 else f"✅高於MA20 ({ma20:.2f})"
    
    return {
        "現價": f"{price:.2f}",
        "狀態": status,
        "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
        "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})"
    }, df

# --- 分頁內容 ---
tab1, tab2 = st.tabs(["📊 主監控頁面", "🏦 金融股財務專區"])

with tab1:
    my_stocks = {"2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光", "2303.TW": "聯電", "2327.TW": "國巨", "2383.TW": "台光電", "2345.TW":"智邦","3037.TW": "欣興"}
    st.subheader("📋 監控清單總覽")
    # 確保資料抓取邏輯在 tab1 內執行
    data_list = []
    for symbol, name in my_stocks.items():
        d, _ = get_stock_data(symbol)
        if d:
            display_name = f"{symbol.replace('.TW', '')} {name}"
            d['名稱'] = display_name
            data_list.append(d)

    # 顯示表格
    if data_list:
        df_final = pd.DataFrame(data_list).set_index('名稱')
        st.dataframe(
            df_final, 
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn("股票名稱", width="medium"),
                "現價": st.column_config.TextColumn("現價", width="small"),
                "狀態": st.column_config.TextColumn("狀態", width="small"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS", width="medium"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS", width="medium"),
            }
        )
    else:
        st.info("正在讀取資料，請稍候...")
    
    st.subheader("📈 個股趨勢圖")
    selected_ticker = st.selectbox("請選擇股票", list(my_stocks.keys()), format_func=lambda x: my_stocks[x])
    if selected_ticker:
        plot_stock_chart(selected_ticker)

with tab2:
    st.subheader("🏦 金融股績效監控")
    financial_stocks = {"2881.TW": "富邦金", "2882.TW": "國泰金", "2883.TW": "凱基金", "2891.TW": "中信金", "2885.TW": "元大金", "2887.TW": "台新新光金", "2890.TW": "永豐金", "2889.TW": "國票金"}
    
    finance_data = []
    for sym, name in financial_stocks.items():
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="20d") # 為了計算 MA20，需至少取 20 天數據
        if hist.empty: continue
        
        info = ticker.info
        current_price = hist['Close'].iloc[-1]
        ma20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        
        # 修正 f-string 引號衝突並確保變數存在
        status = f"⚠️低於MA20 ({ma20:.2f})" if current_price < ma20 else f"✅高於MA20 ({ma20:.2f})"
        
        finance_data.append({
            "名稱": f"{sym.replace('.TW', '')} {name}",
            "現價": f"{current_price:.2f}",
            "狀態": status,
            "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
            "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
            "股價淨值比": f"{info.get('priceToBook', 0):.2f}",
            "殖利率": f"{info.get('dividendYield', 0) :.2f}%" if info.get('dividendYield') else "0.00%"
        })
           
    # 顯示表格
    df_fin = pd.DataFrame(finance_data).set_index('名稱')
    st.dataframe(
        df_fin, 
        use_container_width=True,
        column_config={
            "_index": st.column_config.TextColumn("股票名稱", width="medium"),
            "現價": st.column_config.TextColumn("現價", width="small"),
            "狀態": st.column_config.TextColumn("狀態", width="small"),
            "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing (PE/EPS)", width="medium"),
            "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS", width="medium"),
            "股價淨值比": st.column_config.TextColumn("股價淨值比", width="small"),
            "殖利率": st.column_config.TextColumn("殖利率", width="small"),
        }
    )
    
    st.divider()
    
    st.subheader("📈 金融股趨勢圖")
    fin_ticker = st.selectbox("選擇金融股", list(financial_stocks.keys()), format_func=lambda x: financial_stocks[x], key="fin_select")
    if fin_ticker:
        plot_stock_chart(fin_ticker)
