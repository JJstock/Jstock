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
tab1, tab2, tab3, tab4 ,tab5= st.tabs(["📊 主監控頁面", "🏦 金農專區","📊題材專區", "📈 月營收監控","📈EPS查詢"])

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
        "1303.TW": {"名稱": "南亞", "題材": "玻纖布 CCL"},
        "8261.TW": {"名稱": "富鼎", "題材": "功率元件mosfet"},
        "2408.TW": {"名稱": "南亞科", "題材": "DRAM製造"},
        "6488.TWO": {"名稱": "環球晶", "題材": "矽晶圓-美光"},
        "8299.TWO": {"名稱": "群聯", "題材": "快閃記憶體"}
    }
    topic_data = []
    
    # 修正後的 tab3 迴圈
    for sym, info_dict in topic_stocks.items():
        # 接收兩個回傳值 (metrics_dict, df)
        metrics_dict, df = get_stock_data(sym)
        
        # 【關鍵檢查】：檢查第一個回傳值是否為空
        if metrics_dict is None:
            continue
        
        # 合併資訊
        row = {
            "名稱": f"{sym} {info_dict['名稱']}", 
            "題材": info_dict["題材"]
        }
        # 只合併字典部分
        row.update(metrics_dict) 
        topic_data.append(row)

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
                "PEG": st.column_config.TextColumn("PEG (trail/growth)", width="small"),
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
      
with tab4:
    st.write("### 📊 上市櫃6月營收")

    import requests
    from io import StringIO

    def read_twse_csv_from_bytes(content_bytes):
        """
        依序嘗試常見編碼，並自動偵測標題列位置：
        - 有些版本第一行就是標題（header=0）
        - 有些版本第一行是說明文字，第二行才是標題（header=1）
        判斷依據：讀進來的欄位中是否包含「公司代號」
        """
        last_err = None
        for enc in ['utf-8-sig', 'big5', 'cp950']:
            for header_row in [0, 1]:
                try:
                    decoded_text = content_bytes.decode(enc)
                    tmp = pd.read_csv(StringIO(decoded_text), header=header_row)
                    tmp.columns = tmp.columns.str.strip().str.replace('\u3000', '', regex=False)
                    if '公司代號' in tmp.columns:
                        return tmp
                except (UnicodeDecodeError, UnicodeError, Exception) as e:
                    last_err = e
                    continue
        raise ValueError(f"無法辨識檔案格式（已嘗試多種編碼與標題列位置）：{last_err}")

    @st.cache_data(ttl=3600)
    def fetch_and_merge_github_data():
        # 標記各檔案來源對應的後綴
        sources = [
            {"url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TW.csv", "suffix": ".TW"},
            {"url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TWO.csv", "suffix": ".TWO"}
        ]
        all_dfs = []
        for src in sources:
            try:
                response = requests.get(src["url"], timeout=15)
                response.raise_for_status()
                df = read_twse_csv_from_bytes(response.content)

                # 在公司代號後面加上來源後綴（.TW 或 .TWO）
                if '公司代號' in df.columns:
                    df['公司代號'] = df['公司代號'].astype(str).str.strip() + src["suffix"]

                all_dfs.append(df)
            except Exception as e:
                st.warning(f"讀取 {src['url']} 失敗: {e}")
        return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

    # 按鈕：手動同步資料
    col1, col2 = st.columns([1, 3])
    with col1:
        sync_clicked = st.button("🔄 同步最新營收資料", key="sync_revenue_btn")
    with col2:
        if 'revenue_data' in st.session_state:
            st.caption(f"✅ 目前已載入 {len(st.session_state.revenue_data)} 筆資料")

    if sync_clicked:
        with st.spinner("正在下載並解析資料..."):
            try:
                raw_df = fetch_and_merge_github_data()

                if not raw_df.empty:
                    # 欄位映射
                    mapping = {
                        '公司代號': '代號',
                        '公司名稱': '名稱',
                        '營業收入-上月比較增減(%)': '月增率(MoM%)',
                        '營業收入-去年同月增減(%)': '年增率(YoY%)',
                        '累計營業收入-前期比較增減(%)': '累計年增率(%)'
                    }
                    df = raw_df.rename(columns=mapping)

                    if '代號' not in df.columns:
                        st.error("找不到 '代號' 欄位，請檢查 CSV 的欄位名稱是否正確。")
                        st.write("讀取到的欄位名稱為：", raw_df.columns.tolist())
                        st.stop()

                    # 篩選欄位
                    cols_to_keep = ['代號', '名稱', '月增率(MoM%)', '年增率(YoY%)', '累計年增率(%)']
                    df = df[[c for c in cols_to_keep if c in df.columns]]

                    # 剔除頁尾備註等非資料列
                    # 注意：代號現在是 "1101.TW" 這種格式，所以要先去掉後綴再判斷是否為數字
                    code_numeric_part = df['代號'].astype(str).str.replace(r'\.(TW|TWO)$', '', regex=True)
                    df = df[pd.to_numeric(code_numeric_part, errors='coerce').notna()]

                    # 數據清理：強制轉為數值格式（處理 -、--、全形－ 等空值標記）
                    for col in ['月增率(MoM%)', '年增率(YoY%)', '累計年增率(%)']:
                        if col in df.columns:
                            df[col] = (
                                df[col].astype(str)
                                .str.strip()
                                .str.replace(',', '', regex=False)
                                .replace(r'^-+$', '0', regex=True)
                            )
                            df[col] = pd.to_numeric(df[col], errors='coerce')

                    # 去除重複代號（保留第一筆）
                    df = df.drop_duplicates(subset='代號', keep='first').reset_index(drop=True)

                    st.session_state.revenue_data = df
                    st.success(f"成功載入！共 {len(df)} 筆公司資料。")
                else:
                    st.error("未能讀取任何數據。")
            except Exception as e:
                st.error(f"同步過程發生錯誤：{e}")

# 顯示結果
    if 'revenue_data' in st.session_state:
        df = st.session_state.revenue_data

        st.divider()
        st.write("### 📈 營收強勢成長股清單")

        # 可調整篩選門檻
        c1, c2 = st.columns(2)
        with c1:
            yoy_threshold = st.slider("年增率門檻 (%)", 0, 200, 20, step=5, key="yoy_slider")
        with c2:
            mom_threshold = st.slider("月增率門檻 (%)", -50, 100, 5, step=5, key="mom_slider")

        # 1. 篩選與排序邏輯 (確保這裡向右縮排 8 個空格，與上方的 if 對齊)
        strong_growth = df[
            (df['年增率(YoY%)'] > yoy_threshold) &
            (df['月增率(MoM%)'] > mom_threshold)
        ].dropna(subset=['年增率(YoY%)']).sort_values('年增率(YoY%)', ascending=False)

        st.caption(f"共符合 {len(strong_growth)} 筆（年增率 > {yoy_threshold}% 且 月增率 > {mom_threshold}%）")

        # 2. 定義上色函式 (定義在函式內或上方皆可)
        def highlight_negative(val):
            color = 'red' if val < 0 else 'black'
            return f'color: {color}'

        # 3. 建立 Styler 物件並應用樣式
        styled_df = strong_growth.style.map(
            highlight_negative, 
            subset=['年增率(YoY%)', '月增率(MoM%)']
        )

        # 4. 顯示表格
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "年增率(YoY%)": st.column_config.NumberColumn("年增率(YoY%)", format="%.2f%%"),
                "月增率(MoM%)": st.column_config.NumberColumn("月增率(MoM%)", format="%.2f%%")
            }
        )

        # 下載按鈕
        csv = strong_growth.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載篩選結果 CSV",
            data=csv,
            file_name="strong_growth_stocks.csv",
            mime="text/csv"
        )
    else:
        st.info("👆 請先點擊上方按鈕載入資料")

with tab5:
    st.write("### 📊 EPS查詢")
    # 您的 富果API Key
    API_KEY = "ZTYzYjFmNDQtMjEyNC00MjgxLTg5NDQtNmEwNjhhMzY4OGY3IDMxZDY5OWJhLWQ1MDUtNDJkYy1hOWI4LTNlYmU3ZmE2MDEwNA=="

    def get_eps_from_fugle(symbol):
    # 使用 Fugle 的 Snapshot API
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/info/{symbol}"
    params = {"apiToken": API_KEY}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

# Streamlit 介面
st.title("台股 EPS 監測系統 (API 版)")
symbol = st.text_input("輸入股票代號 (例如 2330)", "2330")

# 修正縮排：將按鈕後的邏輯放入縮排內
if st.button("查詢財報數據"):
    info = get_eps_from_fugle(symbol)
    if info:
        st.success(f"已獲取 {symbol} 最新數據")
        st.json(info)  # 顯示完整的 JSON 結構
    else:
        st.error("查詢失敗，請檢查 API Key 或股票代號")
