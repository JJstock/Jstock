import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import gc
import time
import datetime
from fugle_marketdata import RestClient
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
tab1, tab2, tab3, tab4 ,tab5 ,tab6= st.tabs(["📊 主監控頁面", "🏦 金農專區","📊題材專區", "📈 月營收監控","📊重訊查詢","🚀 查詢 ETF 成分股"])

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

def fetch_twse_news():
    now = datetime.datetime.now()
    year = str(now.year - 1911)
    month = str(now.month)
    day = str(now.day)
    
    url = "https://mops.twse.com.tw/mops/api/t05st02"
    payload = {"year": year, "month": month, "day": day}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://mops.twse.com.tw/mops/web/t05st02",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
            
        data = response.json()
        if data.get('code') == 200 and 'result' in data:
            data_list = data['result']['data']
            if not data_list: return pd.DataFrame()
            
            # 1. 建立 DataFrame
            df = pd.DataFrame(data_list, columns=['出表日期', '時間', '公司代號', '公司名稱', '主旨', '詳細資訊'])
            
            # 2. 處理日期：轉換為日期物件 (一定要在 return 之前做)
            def parse_date(date_str):
                try:
                    y, m, d = map(int, str(date_str).split('/'))
                    return datetime.date(y + 1911, m, d)
                except: return None
            
            df['出表日期'] = df['出表日期'].apply(parse_date)
            df = df.dropna(subset=['出表日期'])
            
            # 3. 檢查「詳細資訊」是否為字典型態 (API 回傳有時是字串，需轉為字典)
            # 如果它已經是字典就不需要轉，如果是字串才轉
            import json
            if isinstance(df['詳細資訊'].iloc[0], str):
                df['詳細資訊'] = df['詳細資訊'].apply(json.loads)
            
            # 【關鍵】這裡才 return，確保資料已經清洗過且包含完整欄位
            return df 
            
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"連線細節錯誤: {e}")
        return pd.DataFrame()

@st.dialog("重訊詳情", width="large")
def show_detail(row):
    url = "https://mops.twse.com.tw/mops/api/t05st02_detail"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://mops.twse.com.tw/mops/web/t05st02"
    }
    
    try:
        # 發送請求
        params = row['詳細資訊']['parameters']
        response = requests.post(url, json=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # 從 JSON 中提取關鍵資料
            info = data['result']['data'][0]
            
            # 顯示標題區塊
            st.subheader(f"{row['公司名稱']} ({row['公司代號']})")
            st.markdown(f"**主旨：** {info[6]}")
            st.divider()
            
            # 顯示發言人資訊
            # 使用 Markdown 的小字體語法 (將文字大小與一般內文一致)
            st.markdown(f"""
            **發言人：** {info[3]}  
            **職稱：** {info[4]}  
            **電話：** {info[5]}
            """)
            
            # 顯示說明內容 (將 \n 換行符號轉為 Markdown 顯示)
            st.markdown("### 說明內容")
            st.text(info[9]) 
            
            st.caption(f"事實發生日：{info[8]}")
        else:
            st.error("無法取得詳細內容")
            
    except Exception as e:
        st.error(f"解析資料時發生錯誤: {e}")
    
with tab5:
    st.subheader("📰 上市每日重大訊息")
    
    # 1. 同步按鈕
    if st.button("🔄 同步最新重大訊息"):
        with st.spinner('正在同步資料...'):
            df_temp = fetch_twse_news()
            if not df_temp.empty:
                st.session_state.news_data = df_temp
                st.success(f"同步完成，共獲取 {len(df_temp)} 筆資料")
            else:
                st.warning("目前無資料或同步失敗")

    if 'news_data' in st.session_state:
        df_news = st.session_state.news_data
        
       # 2. 篩選介面
        st.subheader("🔍 重訊篩選條件")
        col1, col2, col3 = st.columns(3) # 改為 3 欄
        
        with col1:
            search_query = st.text_input("包含關鍵字", value="自結|財報|財務|上半年|第二季")
        with col2:
            exclude_query = st.text_input("排除關鍵字", value="召開")
        with col3:
            date_range = st.date_input("日期區間", value=(df_news['出表日期'].min(), df_news['出表日期'].max()))

        # 3. 篩選邏輯
        # 包含關鍵字
        mask_text = df_news['主旨'].str.contains(search_query, case=False, na=False, regex=True)
        
        # 排除關鍵字 (若輸入框為空則不排除)
        if exclude_query.strip():
            mask_exclude = ~df_news['主旨'].str.contains(exclude_query, case=False, na=False, regex=True)
        else:
            mask_exclude = True
        
        # 日期篩選
        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask_date = (df_news['出表日期'] >= date_range[0]) & (df_news['出表日期'] <= date_range[1])
        else:
            mask_date = True
        
        # 合併所有條件
        filtered_news = df_news[mask_text & mask_exclude & mask_date]

        # 4. 顯示與點擊事件
        st.caption(f"共搜尋到 {len(filtered_news)} 筆相關重訊")
        
        # 使用 filtered_news 進行顯示，避免篩選條件失效
        event = st.dataframe(
            filtered_news[['出表日期', '公司代號', '公司名稱', '主旨']], 
            use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row"
        )

        if event.selection.rows:
            selected_index = event.selection.rows[0]
            # 注意：這裡要從 filtered_news 取資料，而不是原本的 df_news
            selected_row = filtered_news.iloc[selected_index]
            show_detail(selected_row)
            
        # 5. 下載
        csv = filtered_news.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        st.download_button("📥 下載篩選結果 CSV", data=csv, file_name="filtered_news.csv", mime="text/csv")

with tab6:
    st.subheader("🚀 查詢 ETF 成分股")
    
    # 建立輸入框
    ticker = st.text_input("輸入股票代號 (例如 0050, 2330):", placeholder="請輸入代號")
    
    if ticker:
        # 移除可能輸入的空白
        ticker = ticker.strip()
        
        # 組合網址
        target_url = f"https://www.pocket.tw/etf/tw/{ticker}/"
        
        # 使用 link_button 按鈕跳轉
        st.link_button(f"前往 {ticker} 詳細頁面", target_url)
