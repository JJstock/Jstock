import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import gc
import time
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
    raw_peg = info.get('pegRatio')
    growth = info.get('earningsGrowth', 0)
    
    # 修正語法錯誤
    calc_peg = info.get('trailingPE', 0) / (growth * 100) if (growth and growth != 0) else 0
    PEG = f"{raw_peg} ({calc_peg:.2f})"
    
    status = f"⚠️低於MA20 ({ma20:.2f})" if price < ma20 else f"✅高於MA20 ({ma20:.2f})"
    
    return {
        "現價": f"{price:.2f}",
        "狀態": status,
        "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
        "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
        "PEG": PEG,
        "成長率": f"{growth*100:.2f}%"
    }, df

# --- 主程式流程 ---
tab1, tab2, tab3 = st.tabs(["📊 主監控頁面", "🏦 金農專區","📊題材專區"])

if 'my_stocks' not in st.session_state:
    st.session_state.my_stocks = {
        "2330.TW": "台積電", "2454.TW": "聯發科", "2308.TW": "台達電", "2317.TW": "鴻海", "3711.TW": "日月光", "2303.TW": "聯電", "2327.TW": "國巨", "2383.TW": "台光電", "2345.TW":"智邦","3037.TW": "欣興",
        
    }
# 新增監控股票
with st.sidebar:
    st.subheader("➕ 新增監控股票")
    # 1. 選擇市場
    market_type = st.radio("選擇市場", ["上市 (.TW)", "上櫃 (.TWO)"], horizontal=True)
    new_ticker = st.text_input("輸入股票代號", placeholder="例如: 2330")
    new_name = st.text_input("輸入公司名稱", placeholder="例如: 台積電")
    
    if st.button("加入監控清單"):
        if new_ticker and new_name:
            # 【關鍵修正】：根據你的 radio 選項來判斷後綴
            # 確保字串匹配正確
            if "上櫃" in market_type:
                suffix = ".TWO"
            else:
                suffix = ".TW"
                
            full_ticker = f"{new_ticker}{suffix}"
            
            # 除錯用：這裡會顯示你實際組合出來的代號，看看到底是哪邊抓錯了
            st.write(f"正在驗證代號: {full_ticker}")
            
            with st.spinner("正在驗證股票代號..."):
                try:
                    test_ticker = yf.Ticker(full_ticker)
                    hist = test_ticker.history(period="1d")
                    
                    if not hist.empty:
                        st.session_state.my_stocks[full_ticker] = new_name
                        st.success(f"✅ {new_name} ({full_ticker}) 加入成功！")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ 查無代號 {full_ticker}，請確認市場是否選對？")
                except Exception as e:
                    st.error(f"❌ 驗證失敗: {e}")
        else:
            st.warning("請輸入代號與名稱！")
    
    st.markdown("---") # 分隔線
    
    st.subheader("🗑️ 刪除監控股票")
    # 建立一個下拉選單供選擇要刪除的股票
    ticker_to_delete = st.selectbox(
        "選擇要刪除的項目", 
        list(st.session_state.my_stocks.keys()), 
        format_func=lambda x: st.session_state.my_stocks[x]
    )
    
    if st.button("刪除此項目"):
        if ticker_to_delete in st.session_state.my_stocks:
            del st.session_state.my_stocks[ticker_to_delete]
            st.warning(f"已刪除 {ticker_to_delete}")
            st.rerun() # 自動重新整理

# 3. 在 tab1 讀取時，改用 session_state 的資料
with tab1:
    st.subheader("📋 監控清單總覽")
    data_list = []
    # 使用 session_state 進行迴圈
    for symbol, name in st.session_state.my_stocks.items():
        d, _ = get_stock_data(symbol)
        if d:
            display_name = f"{symbol} {name}"
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
                "狀態": st.column_config.TextColumn("狀態", width="medium"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS", width="medium"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS", width="medium"),
                "PEG": st.column_config.TextColumn("PEG (trail/growth)", width="small"),
                "成長率": st.column_config.TextColumn("成長率", width="small")
            }
        )
    else:
        st.info("正在讀取資料，請稍候...")
    
    st.subheader("📈 個股趨勢圖")
    # 【關鍵修正】：這裡改用 session_state，新增的股票才會出現在下拉選單中
    selected_ticker = st.selectbox(
        "請選擇股票", 
        list(st.session_state.my_stocks.keys()), 
        format_func=lambda x: st.session_state.my_stocks[x]
    )
    if selected_ticker:
        plot_stock_chart(selected_ticker)

with tab2:
    st.subheader("🏦 金融股績效監控")
    financial_stocks = {"2881.TW": "富邦金", "2882.TW": "國泰金", "2883.TW": "凱基金", "2891.TW": "中信金", "2885.TW": "元大金", "2887.TW": "台新新光金", "2890.TW": "永豐金"}
    
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

with tab3:
    st.subheader("📋 題材專區")
    topic_stocks = {
        "3008.TW": {"名稱": "大立光", "題材": "光學鏡頭"},
        "3481.TW": {"名稱": "群創", "題材": "面板封裝"},
        "6488.TWO": {"名稱": "環球晶", "題材": "矽晶圓-美光"},
        "8261.TW": {"名稱": "富鼎", "題材": "功率元件mosfet"},
        "8299.TWO": {"名稱": "群聯", "題材": "快閃記憶體"}
    }
    topic_data = []
    
    # 修正：這裡應該用 sym, info_dict
    for sym, info_dict in topic_stocks.items():
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="20d")
        if hist.empty: continue
        
        info = ticker.info
        current_price = hist['Close'].iloc[-1]
        ma20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        
        status = f"⚠️低於MA20 ({ma20:.2f})" if current_price < ma20 else f"✅高於MA20 ({ma20:.2f})"
        
        topic_data.append({
            "名稱": f"{sym} {info_dict['名稱']}",
            "題材": info_dict["題材"], # 這裡正確抓取到了
            "現價": f"{current_price:.2f}",
            "狀態": status,
            "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
            "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
            "PEG": f"{info.get('pegRatio', 0):.2f}",
            "成長率": f"{info.get('earningsGrowth', 0)*100:.2f}%"
        })

    # 顯示表格
    if topic_data:
        df_topic = pd.DataFrame(topic_data).set_index('名稱')
        st.dataframe(
            df_topic, 
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn("股票名稱", width="medium"),
                "題材": st.column_config.TextColumn("題材", width="small"), # 新增這一行
                "現價": st.column_config.TextColumn("現價", width="small"),
                "狀態": st.column_config.TextColumn("狀態", width="medium"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS", width="medium"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS", width="medium"),
                "PEG": st.column_config.TextColumn("PEG", width="small"),
                "成長率": st.column_config.TextColumn("成長率", width="small")
            }
        )
    else:
        st.info("正在讀取資料，請稍候...")
    
    st.subheader("📈 題材趨勢圖")
    # 修正：format_func 也要對應調整，因為現在的 value 是字典
    topic_ticker = st.selectbox(
        "選擇題材股", 
        list(topic_stocks.keys()), 
        format_func=lambda x: topic_stocks[x]["名稱"], 
        key="topic_select"
    )
    if topic_ticker:
        plot_stock_chart(topic_ticker)
