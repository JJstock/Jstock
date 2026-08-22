import datetime
import gc
import json
from io import StringIO
import time
from fugle_marketdata import RestClient
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Jstok股價監控", layout="wide")
st.title("JStok 📊 MA20+60 與財報監控")


# --- 繪圖函式 ---
def plot_stock_chart(ticker):
    stock = yf.Ticker(ticker)
    df = stock.history(period="6mo")
    if not df.empty:
        df["Volume"] = df["Volume"].fillna(0)
        df["Date_Str"] = df.index.strftime("%Y-%m-%d")
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()

        prev_close = df["Close"].shift(1)
        conditions = [(df["Close"] > prev_close), (df["Close"] < prev_close)]
        choices = ["#EF553B", "#00CC96"]
        volume_colors = np.select(
            conditions, choices, default="#7F7F7F"
        ).tolist()

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],
        )
        fig.add_trace(
            go.Candlestick(
                x=df["Date_Str"],
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=df["Close"],
                name="股價",
                increasing_line_color="#EF553B",
                decreasing_line_color="#00CC96",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["Date_Str"],
                y=df["MA20"],
                name="MA20",
                line=dict(color="red", width=1.5),
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["Date_Str"],
                y=df["MA60"],
                name="MA60",
                line=dict(color="blue", width=1.5),
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=df["Date_Str"],
                y=df["Volume"],
                name="成交量",
                marker_color=volume_colors,
            ),
            row=2,
            col=1,
        )
        fig.update_layout(
            height=600,
            showlegend=False,
            xaxis_rangeslider_visible=False,
            xaxis=dict(type="category", showticklabels=False),
            xaxis2=dict(type="category", tickangle=45),
        )
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
    if df.empty:
        return None, None

    ma20 = df["Close"].rolling(window=20).mean().iloc[-1]
    price = df["Close"].iloc[-1]
    raw_peg = info.get("pegRatio")
    growth = info.get("earningsGrowth", 0)

    calc_peg = (
        info.get("trailingPE", 0) / (growth * 100)
        if (growth and growth != 0)
        else 0
    )
    PEG = f"{raw_peg} ({calc_peg:.2f})"

    status = (
        f"⚠️低於MA20 ({ma20:.2f})"
        if price < ma20
        else f"✅高於MA20 ({ma20:.2f})"
    )

    return {
        "現價": f"{price:.2f}",
        "狀態": status,
        "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
        "CurrentYear (PE/EPS)": f"{info.get('priceEpsCurrentYear', 0):.2f} (EPS: {info.get('epsCurrentYear', 0):.2f})",
        "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
        "PEG": PEG,
        "成長率": f"{growth*100:.2f}%",
    }, df


# --- 主程式流程 ---
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 主監控頁面",
    "📈 題材專區",
    "🏦 金農專區",
    "📈 月營收監控",
    "📊 重訊查詢",
    "🚀 查詢 ETF 成分股",
    "📈 本益比河流圖",
])

if "my_stocks" not in st.session_state:
    st.session_state.my_stocks = {
        "2330.TW": "台積電",
        "2454.TW": "聯發科",
        "2308.TW": "台達電",
        "2317.TW": "鴻海",
        "2383.TW": "台光電",
        "3711.TW": "日月光",
        "2303.TW": "聯電",              
        "3037.TW": "欣興",
    }

# 側邊欄：新增與刪除監控股票
@st.cache_data
def load_stock_names():
    try:
        # 請根據你 CSV 實際的檔名與編碼調整 (常見為 utf-8 或 utf-8-sig 或 big5)
        df = pd.read_csv("name.csv", encoding="utf-8-sig")
        return df
    except Exception as e:
        return None

# 載入資料
df_names = load_stock_names()
with st.sidebar:
    st.subheader("➕ 新增監控股票")
    market_type = st.radio(
        "選擇市場", ["上市 (.TW)", "上櫃 (.TWO)"], horizontal=True
    )
     # 2. 初始化 session_state 來存放輸入的代號與名稱
    if 'input_ticker' not in st.session_state:
        st.session_state.input_ticker = ""
    if 'input_name' not in st.session_state:
        st.session_state.input_name = ""

    # 3. 代號輸入框（當內容改變時觸發自動搜尋）
    def update_stock_name():
        ticker = st.session_state.input_ticker.strip()
        if df_names is not None and not df_names.empty and ticker:
            # 假設 CSV 的欄位名稱叫 '代號' 與 '名稱' (請依你的 CSV 欄位名稱修改)
            # 這裡把代號轉為字串比對，避免型態不合
            match = df_names[df_names['公司代號'].astype(str) == ticker]
            if not match.empty:
                # 找到對應的第一筆名稱，自動填入
                st.session_state.input_name = str(match.iloc[0]['公司名稱'])
            else:
                st.session_state.input_name = "" # 找不到則清空

    new_ticker = st.text_input(
        "輸入股票代號", 
        placeholder="例如: 2330", 
        key="input_ticker",
        on_change=update_stock_name # 當輸入框按 Enter 或失焦時觸發
    )
    
    # 4. 公司名稱輸入框（會自動帶入查到的結果，使用者也可以手動修改）
    new_name = st.text_input(
        "輸入公司名稱", 
        placeholder="例如: 台積電", 
        key="input_name"
    )

    if st.button("加入監控清單"):
        if new_ticker and new_name:
            suffix = ".TWO" if "上櫃" in market_type else ".TW"
            full_ticker = f"{new_ticker.strip()}{suffix}"

            st.write(f"正在驗證代號: {full_ticker}")
            with st.spinner("正在驗證股票代號..."):
                try:
                    test_ticker = yf.Ticker(full_ticker)
                    hist = test_ticker.history(period="1d")

                    if not hist.empty:
                        st.session_state.my_stocks[full_ticker] = new_name
                        st.success(
                            f"✅ {new_name} ({full_ticker}) 加入成功！"
                        )
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(
                            f"❌ 查無代號 {full_ticker}，請確認市場是否選對？"
                        )
                except Exception as e:
                    st.error(f"❌ 驗證失敗: {e}")
        else:
            st.warning("請輸入代號與名稱！")

    st.markdown("---")

    st.subheader("🗑️ 刪除監控股票")
    ticker_to_delete = st.selectbox(
        "選擇要刪除的項目",
        list(st.session_state.my_stocks.keys()),
        format_func=lambda x: st.session_state.my_stocks[x],
    )

    if st.button("刪除此項目"):
        if ticker_to_delete in st.session_state.my_stocks:
            del st.session_state.my_stocks[ticker_to_delete]
            st.warning(f"已刪除 {ticker_to_delete}")
            st.rerun()

# --- TAB 1: 主監控頁面 ---
with tab1:
    st.subheader("📋 監控清單總覽")
    data_list = []
    for symbol, name in st.session_state.my_stocks.items():
        d, _ = get_stock_data(symbol)
        if d:
            display_name = f"{symbol} {name}"
            d["名稱"] = display_name
            data_list.append(d)

    if data_list:
        df_final = pd.DataFrame(data_list).set_index("名稱")
        st.dataframe(
            df_final,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn(
                    "股票名稱", width="medium"
                ),
                "現價": st.column_config.TextColumn("現價", width="small"),
                "狀態": st.column_config.TextColumn("狀態", width="medium"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS", width="medium"),
                "CurrentYear (PE/EPS)": st.column_config.TextColumn("CurrentYear PE/EPS", width="medium"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS", width="medium"),
                "PEG": st.column_config.TextColumn("PEG (trail/growth)", width="small"),
                "成長率": st.column_config.TextColumn("成長率", width="small"),
            },
        )
    else:
        st.info("正在讀取資料，請稍候...")

    st.subheader("📈 個股趨勢圖")
    selected_ticker = st.selectbox(
        "請選擇股票",
        list(st.session_state.my_stocks.keys()),
        format_func=lambda x: st.session_state.my_stocks[x],
    )
    if selected_ticker:
        plot_stock_chart(selected_ticker)


# --- TAB 2: 題材專區 ---
with tab2:
    st.subheader("📋 題材專區")
    topic_stocks = {
        "2603.TW": {"名稱": "長榮", "題材": "海運"},
        "2615.TW": {"名稱": "萬海", "題材": "海運"},
        "2637.TW": {"名稱": "慧洋-KY", "題材": "散裝"},
        "3008.TW": {"名稱": "大立光", "題材": "光學鏡頭"},
        "3406.TW": {"名稱": "玉晶光", "題材": "光學鏡頭"},
        "3042.TW": {"名稱": "晶技", "題材": "石英元件"},
        "2059.TW": {"名稱": "川湖", "題材": "滑軌"},
        "3017.TW": {"名稱": "奇鋐", "題材": "散熱"},
        "2327.TW": {"名稱": "國巨", "題材": "被動元件"},
        "1303.TW": {"名稱": "南亞", "題材": "玻纖布 CCL"},
        "2382.TW": {"名稱": "廣達", "題材": "伺服器"},
        "3231.TW": {"名稱": "緯創", "題材": "伺服器"},
        "6669.TW": {"名稱": "緯穎", "題材": "伺服器"},
        "2408.TW": {"名稱": "南亞科", "題材": "DRAM製造"},
        "2344.TW": {"名稱": "華邦電", "題材": "記憶體"},
        "8299.TWO": {"名稱": "群聯", "題材": "快閃記憶體"},
        "6488.TWO": {"名稱": "環球晶", "題材": "矽晶圓-美光"},
        
    }
    topic_data = []

    for sym, info_dict in topic_stocks.items():
        metrics_dict, df = get_stock_data(sym)
        if metrics_dict is None:
            continue

        row = {
            "名稱": f"{sym} {info_dict['名稱']}",
            "題材": info_dict["題材"],
        }
        row.update(metrics_dict)
        topic_data.append(row)

    if topic_data:
        df_topic = pd.DataFrame(topic_data).set_index("名稱")
        st.dataframe(
            df_topic,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn(
                    "股票名稱", width="medium"
                ),
                "題材": st.column_config.TextColumn("題材", width="small"),
                "現價": st.column_config.TextColumn("現價", width="small"),
                "狀態": st.column_config.TextColumn("狀態", width="medium"),
                "Trailing (PE/EPS)": st.column_config.TextColumn(
                    "Trailing PE/EPS", width="medium"
                ),
                "Forward (PE/EPS)": st.column_config.TextColumn(
                    "Forward PE/EPS", width="medium"
                ),
                "PEG": st.column_config.TextColumn(
                    "PEG (trail/growth)", width="small"
                ),
                "成長率": st.column_config.TextColumn("成長率", width="small"),
            },
        )
    else:
        st.info("正在讀取資料，請稍候...")

    st.subheader("📈 題材趨勢圖")
    topic_ticker = st.selectbox(
        "選擇題材股",
        list(topic_stocks.keys()),
        format_func=lambda x: topic_stocks[x]["名稱"],
        key="topic_select",
    )
    if topic_ticker:
        plot_stock_chart(topic_ticker)

# --- TAB 3: 金農專區 ---
with tab3:
    st.subheader("🏦 金融股績效監控")
    financial_stocks = {
        "2881.TW": "富邦金",
        "2882.TW": "國泰金",
        "2883.TW": "凱基金",
        "2891.TW": "中信金",
        "2885.TW": "元大金",
        "2887.TW": "台新新光金",
        "2890.TW": "永豐金",
    }

    finance_data = []
    for sym, name in financial_stocks.items():
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="20d")
        if hist.empty:
            continue

        info = ticker.info if ticker.info else {}
        current_price = hist["Close"].iloc[-1]
        ma20 = hist["Close"].rolling(window=20).mean().iloc[-1]

        status = (
            f"⚠️低於MA20 ({ma20:.2f})"
            if current_price < ma20
            else f"✅高於MA20 ({ma20:.2f})"
        )

        finance_data.append({
            "名稱": f"{sym.replace('.TW', '')} {name}",
            "現價": f"{current_price:.2f}",
            "狀態": status,
            "Trailing (PE/EPS)": f"{info.get('trailingPE', 0):.2f} (EPS: {info.get('trailingEps', 0):.2f})",
            "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
            "股價淨值比": f"{info.get('priceToBook', 0):.2f}",
            "殖利率": (
                f"{info.get('dividendYield', 0) :.2f}%"
                if info.get("dividendYield")
                else "0.00%"
            ),
        })

    if finance_data:
        df_fin = pd.DataFrame(finance_data).set_index("名稱")
        st.dataframe(
            df_fin,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn(
                    "股票名稱", width="medium"
                ),
                "現價": st.column_config.TextColumn("現價", width="small"),
                "狀態": st.column_config.TextColumn("狀態", width="small"),
                "Trailing (PE/EPS)": st.column_config.TextColumn(
                    "Trailing (PE/EPS)", width="medium"
                ),
                "Forward (PE/EPS)": st.column_config.TextColumn(
                    "Forward PE/EPS", width="medium"
                ),
                "股價淨值比": st.column_config.TextColumn(
                    "股價淨值比", width="small"
                ),
                "殖利率": st.column_config.TextColumn(
                    "殖利率", width="small"
                ),
            },
        )

    st.divider()
    st.subheader("📈 金融股趨勢圖")
    fin_ticker = st.selectbox(
        "選擇金融股",
        list(financial_stocks.keys()),
        format_func=lambda x: financial_stocks[x],
        key="fin_select",
    )
    if fin_ticker:
        plot_stock_chart(fin_ticker)

import streamlit as st
import pandas as pd
import requests
from io import StringIO

# --- TAB 4: 月營收監控 ---
with tab4:
    st.write("### 📊 上市櫃營收與三率三升監控")

    def read_twse_csv_from_bytes(content_bytes):
        last_err = None
        for enc in ["utf-8-sig", "big5", "cp950"]:
            for header_row in [0, 1]:
                try:
                    decoded_text = content_bytes.decode(enc)
                    tmp = pd.read_csv(
                        StringIO(decoded_text), header=header_row
                    )
                    tmp.columns = (
                        tmp.columns.str.strip().str.replace(
                            "\u3000", "", regex=False
                        )
                    )
                    if "公司代號" in tmp.columns:
                        return tmp
                except Exception as e:
                    last_err = e
                    continue
        raise ValueError(
            f"無法辨識檔案格式（已嘗試多種編碼與標題列位置）：{last_err}"
        )

    @st.cache_data(ttl=3600)
    def fetch_and_merge_github_data():
        sources = [
            {
                "url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TW.csv",
                "suffix": ".TW",
            },
            {
                "url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TWO.csv",
                "suffix": ".TWO",
            },
        ]
        all_dfs = []
        for src in sources:
            try:
                response = requests.get(src["url"], timeout=15)
                response.raise_for_status()
                df = read_twse_csv_from_bytes(response.content)

                if "公司代號" in df.columns:
                    df["公司代號"] = (
                        df["公司代號"].astype(str).str.strip() + src["suffix"]
                    )

                all_dfs.append(df)
            except Exception as e:
                st.warning(f"讀取 {src['url']} 失敗: {e}")
        return (
            pd.concat(all_dfs, ignore_index=True)
            if all_dfs
            else pd.DataFrame()
        )

    if "revenue_data" not in st.session_state:
        with st.spinner("正在自動載入與解析營收資料..."):
            try:
                raw_df = fetch_and_merge_github_data()

                if not raw_df.empty:
                    mapping = {
                        "公司代號": "代號",
                        "公司名稱": "名稱",
                        "營業收入-上月比較增減(%)": "月增率(MoM%)",
                        "營業收入-去年同月增減(%)": "年增率(YoY%)",
                        "累計營業收入-前期比較增減(%)": "累計年增率(%)",
                    }
                    df = raw_df.rename(columns=mapping)

                    # 1. 抓取欄位，確保包含累計年增率(%)
                    cols_to_keep = [
                        "代號",
                        "名稱",
                        "月增率(MoM%)",
                        "年增率(YoY%)",
                        "累計年增率(%)",
                    ]
                    df = df[[c for c in cols_to_keep if c in df.columns]]

                    code_numeric_part = (
                        df["代號"]
                        .astype(str)
                        .str.replace(r"\.(TW|TWO)$", "", regex=True)
                    )
                    df = df[
                        pd.to_numeric(
                            code_numeric_part, errors="coerce"
                        ).notna()
                    ]

                    for col in [
                        "月增率(MoM%)",
                        "年增率(YoY%)",
                        "累計年增率(%)",
                    ]:
                        if col in df.columns:
                            df[col] = (
                                df[col]
                                .astype(str)
                                .str.strip()
                                .str.replace(",", "", regex=False)
                                .replace(r"^-+$", "0", regex=True)
                            )
                            df[col] = pd.to_numeric(df[col], errors="coerce")

                    df = df.drop_duplicates(subset="代號", keep="first").reset_index(
                        drop=True
                    )
                    
                    # 2. 讀取 rate.csv 並安全合併三率三升資訊
                    import os
                    rate_csv_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "rate.csv"
                    )
                    try:
                        df_rate = None
                        last_err = None
                        for enc in ["utf-8-sig", "big5", "cp950", "utf-8"]:
                            try:
                                df_rate = pd.read_csv(
                                    rate_csv_path,
                                    dtype=str,
                                    encoding=enc,
                                    sep=None,
                                    engine="python",
                                )
                                df_rate.columns = df_rate.columns.str.strip()
                                break
                            except Exception as e:
                                last_err = e
                                df_rate = None
                                continue

                        if df_rate is None:
                            raise ValueError(f"無法辨識 rate.csv 編碼：{last_err}")

                        code_col_in_rate = (
                            "公司代號" if "公司代號" in df_rate.columns else "代號"
                        )

                        if code_col_in_rate not in df_rate.columns:
                            raise ValueError(
                                f"rate.csv 缺少公司代號欄位，實際欄位為：{list(df_rate.columns)}"
                            )
                        if "三率三升" not in df_rate.columns:
                            raise ValueError(
                                f"rate.csv 缺少三率三升欄位，實際欄位為：{list(df_rate.columns)}"
                            )

                        df_rate["temp_merge_code"] = (
                            df_rate[code_col_in_rate]
                            .astype(str)
                            .str.strip()
                            .str.replace(r"\.(TW|TWO)$", "", regex=True)
                        )
                        df_rate_dedup = df_rate.drop_duplicates(
                            subset="temp_merge_code", keep="first"
                        )

                        df["temp_merge_code"] = (
                            df["代號"]
                            .astype(str)
                            .str.strip()
                            .str.replace(r"\.(TW|TWO)$", "", regex=True)
                        )

                        df = pd.merge(
                            df,
                            df_rate_dedup[["temp_merge_code", "三率三升"]],
                            on="temp_merge_code",
                            how="left",
                        )

                        df["三率三升"] = df["三率三升"].fillna("0")
                        df["三率三升"] = df["三率三升"].apply(
                            lambda x: "🔥 三率三升"
                            if str(x).strip() in ["1", "1.0", "True", "true"]
                            else "-"
                        )

                        df = df.drop(columns=["temp_merge_code"])

                    except FileNotFoundError:
                        st.warning(f"⚠️ 找不到 rate.csv（預期路徑：{rate_csv_path}）")
                        df["三率三升"] = "-"
                    except Exception as e:
                        st.warning(f"⚠️ 讀取 rate.csv 發生錯誤：{e}")
                        df["三率三升"] = "-"
                        if "temp_merge_code" in df.columns:
                            df = df.drop(columns=["temp_merge_code"])

                    # 3. 調整欄位順序：確保「三率三升」放在最後一欄
                    base_cols = ["代號", "名稱", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
                    existing_base = [c for c in base_cols if c in df.columns]
                    # 將三率三升固定在最後
                    other_cols = [c for c in df.columns if c not in existing_base and c != "三率三升"]
                    df = df[existing_base + other_cols + (["三率三升"] if "三率三升" in df.columns else [])]

                    st.session_state.revenue_data = df
                else:
                    st.error("未能讀取任何數據。")
            except Exception as e:
                st.error(f"自動載入過程發生錯誤：{e}")

    if "revenue_data" in st.session_state:
        df = st.session_state.revenue_data

        
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            yoy_threshold = st.slider(
                "年增率門檻 (%)", 0, 200, 20, step=5, key="yoy_slider"
            )
        with c2:
            mom_threshold = st.slider(
                "月增率門檻 (%)", -50, 100, 5, step=5, key="mom_slider"
            )
        with c3:
            st.write("")  # 對齊 slider 高度用的留白
            only_triple_rise = st.checkbox(
                "🔥 只顯示三率三升", value=False, key="triple_rise_checkbox"
            )

        strong_growth = df[
            (df["年增率(YoY%)"] > yoy_threshold)
            & (df["月增率(MoM%)"] > mom_threshold)
        ].dropna(subset=["年增率(YoY%)"])

        if only_triple_rise:
            strong_growth = strong_growth[strong_growth["三率三升"] == "🔥 三率三升"]

        strong_growth = strong_growth.sort_values("年增率(YoY%)", ascending=False)

        st.caption(
            f"共符合 {len(strong_growth)} 筆（年增率 > {yoy_threshold}% 且 月增率 >"
            f" {mom_threshold}%）"
        )

        def highlight_negative(val):
            color = "red" if isinstance(val, (int, float)) and val < 0 else "black"
            return f"color: {color}"

        styled_df = strong_growth.style.map(
            highlight_negative, subset=["年增率(YoY%)", "月增率(MoM%)"]
        )

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "年增率(YoY%)": st.column_config.NumberColumn(
                    "年增率(YoY%)", format="%.2f%%"
                ),
                "月增率(MoM%)": st.column_config.NumberColumn(
                    "月增率(MoM%)", format="%.2f%%"
                ),
                "累計年增率(%)": st.column_config.NumberColumn(
                    "累計年增率(%)", format="%.2f%%"
                ),
            },
        )

        csv = strong_growth.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 下載篩選結果 CSV",
            data=csv,
            file_name="strong_growth_stocks.csv",
            mime="text/csv",
        )
    else:
        st.info("⏳ 正在初始化資料，請稍候...")

# --- TAB 5: 重訊查詢 ---
def fetch_twse_news():
    now = datetime.datetime.now()
    year = str(now.year - 1911)
    month = str(now.month)
    day = str(now.day)

    url = "https://mops.twse.com.tw/mops/api/t05st02"
    payload = {"year": year, "month": month, "day": day}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
        "Referer": "https://mops.twse.com.tw/mops/web/t05st02",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=10
        )
        if response.status_code != 200:
            return pd.DataFrame()

        data = response.json()
        if data.get("code") == 200 and "result" in data:
            data_list = data["result"]["data"]
            if not data_list:
                return pd.DataFrame()

            df = pd.DataFrame(
                data_list,
                columns=[
                    "出表日期",
                    "時間",
                    "公司代號",
                    "公司名稱",
                    "主旨",
                    "詳細資訊",
                ],
            )

            def parse_date(date_str):
                try:
                    y, m, d = map(int, str(date_str).split("/"))
                    return datetime.date(y + 1911, m, d)
                except:
                    return None

            df["出表日期"] = df["出表日期"].apply(parse_date)
            df = df.dropna(subset=["出表日期"])

            if isinstance(df["詳細資訊"].iloc[0], str):
                df["詳細資訊"] = df["詳細資訊"].apply(json.loads)

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
        "Referer": "https://mops.twse.com.tw/mops/web/t05st02",
    }

    try:
        params = row["詳細資訊"]["parameters"]
        response = requests.post(url, json=params, headers=headers)

        if response.status_code == 200:
            data = response.json()
            info = data["result"]["data"][0]

            st.subheader(f"{row['公司名稱']} ({row['公司代號']})")
            st.markdown(f"**主旨：** {info[6]}")
            st.divider()

            st.markdown(f"""
            **發言人：** {info[3]}  
            **職稱：** {info[4]}  
            **電話：** {info[5]}
            """)

            st.markdown("### 說明內容")
            st.text(info[9])
            st.caption(f"事實發生日：{info[8]}")
        else:
            st.error("無法取得詳細內容")

    except Exception as e:
        st.error(f"解析資料時發生錯誤: {e}")


with tab5:
    st.subheader("📰 MOPS每日重大訊息")

    if st.button("🔄 同步最新重大訊息"):
        with st.spinner("正在同步資料..."):
            df_temp = fetch_twse_news()
            if not df_temp.empty:
                st.session_state.news_data = df_temp
                st.success(f"同步完成，共獲取 {len(df_temp)} 筆資料")
            else:
                st.warning("目前無資料或同步失敗")

    if "news_data" in st.session_state:
        df_news = st.session_state.news_data

        st.subheader("🔍 重訊篩選條件")
        col1, col2, col3 = st.columns(3)

        with col1:
            search_query = st.text_input(
                "包含關鍵字", value="自結|財報|財務|上半年|第二季"
            )
        with col2:
            exclude_query = st.text_input("排除關鍵字", value="召開")
        with col3:
            date_range = st.date_input(
                "日期區間",
                value=(
                    df_news["出表日期"].min(),
                    df_news["出表日期"].max(),
                ),
            )

        mask_text = df_news["主旨"].str.contains(
            search_query, case=False, na=False, regex=True
        )

        if exclude_query.strip():
            mask_exclude = ~df_news["主旨"].str.contains(
                exclude_query, case=False, na=False, regex=True
            )
        else:
            mask_exclude = True

        if isinstance(date_range, tuple) and len(date_range) == 2:
            mask_date = (df_news["出表日期"] >= date_range[0]) & (
                df_news["出表日期"] <= date_range[1]
            )
        else:
            mask_date = True

        filtered_news = df_news[mask_text & mask_exclude & mask_date]

        st.caption(f"共搜尋到 {len(filtered_news)} 筆相關重訊")

        event = st.dataframe(
            filtered_news[["出表日期", "公司代號", "公司名稱", "主旨"]],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )

        if event.selection.rows:
            selected_index = event.selection.rows[0]
            selected_row = filtered_news.iloc[selected_index]
            show_detail(selected_row)

        csv = filtered_news.to_csv(index=False, encoding="utf-8-sig").encode(
            "utf-8-sig"
        )
        st.download_button(
            "📥 下載篩選結果 CSV",
            data=csv,
            file_name="filtered_news.csv",
            mime="text/csv",
        )


# --- TAB 6: ETF 成分股與指數 ---
def get_taifex_holdings(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = "utf-8"

        dfs = pd.read_html(StringIO(response.text), header=0)
        if dfs:
            df = dfs[0]
            if df.shape[1] >= 4:
                df = df.iloc[:, :4]
            df.columns = ["排行", "代號", "名稱", "佔比"]
            return df.head(50)
    except Exception as e:
        return None


with tab6:
    st.subheader("🚀 ETF 成分股查詢區")

    # A區：Pocket ETF 查詢
    ticker = st.text_input(
        "輸入 Pocket ETF 代號 (例如 0050):", placeholder="請輸入代號"
    )
    if ticker:
        ticker = ticker.strip()
        target_url = f"https://www.pocket.tw/etf/tw/{ticker}/"
        st.link_button(f"前往 {ticker} 詳細頁面", target_url)

    st.divider()

    # B區：期交所成分股
    st.subheader("📊 指定指數成分股 (期交所)")
    data_source = st.selectbox(
        "選擇查詢指數:", options=["上市指數", "櫃買指數"]
    )

    urls = {
        "上市指數": "https://www.taifex.com.tw/cht/2/weightedPropertion",
        "櫃買指數": "https://www.taifex.com.tw/cht/2/tPEXPropertion",
    }

    if st.button("開始讀取資料"):
        with st.spinner("正在讀取資料..."):
            df_taifex = get_taifex_holdings(urls[data_source])
            if df_taifex is not None:
                st.write(f"### {data_source} 前50大成分股")
                st.dataframe(
                    df_taifex,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "排行": st.column_config.NumberColumn(
                            "排行", width="50"
                        ),
                        "代號": st.column_config.TextColumn("代號"),
                        "名稱": st.column_config.TextColumn("名稱"),
                        "佔比": st.column_config.TextColumn("佔比"),
                    },
                )
            else:
                st.error("無法抓取資料，請確認該頁面表格結構是否變更。")


# --- TAB 7: 通用台股本益比河流圖 (彩虹填色版 + 日 K + 5年固定) ---
with tab7:
    st.header("本益比河流圖")
    st.caption("彩虹填色風格+5年日K線+歷史本益比區間統計")

    # 1. 控制選項 (資料固定 5 年)
    col_sym, col_market, col_freq = st.columns([2, 1, 1.5])
    with col_sym:
        stock_code = st.text_input(
            "輸入股票代號", value="2330", key="pe_stock_code"
        ).strip()
    with col_market:
        market_suffix = st.selectbox(
            "市場類別", options=[".TW", ".TWO"], index=0, key="pe_market"
        )
    with col_freq:
        interval_option = st.selectbox(
            "K線週期",
            options=["日 (1d)", "週 (1wk)", "月 (1mo)"],
            index=0,
            key="pe_freq",
        )
        freq_map = {"日 (1d)": "1d", "週 (1wk)": "1wk", "月 (1mo)": "1mo"}

    target_ticker = f"{stock_code}{market_suffix}" if stock_code else "2330.TW"
    period_option = "5y"  # 固定為 5 年

    col_pe, col_eps = st.columns([3, 2])
    with col_pe:
        available_options = [
            6,
            8,
            10,
            12,
            14,
            16,
            18,
            20,
            22,
            24,
            26,
            28,
            30,
            32,
            35,
            40,
            50,
        ]
        selected_pes = st.multiselect(
            "選擇本益比倍數區間",
            options=available_options,
            default=[10, 12, 16, 20, 24, 28, 32],
            key="pe_multiselect",
        )
        selected_pes = sorted(selected_pes)

    with col_eps:
        override_eps = st.number_input(
            "手動校正最新 TTM EPS ( > 0 優先採用)",
            value=0.0,
            step=0.5,
            format="%.2f",
            help="若 yfinance 缺漏數據，可直接輸入最新 TTM EPS 補救。",
            key="pe_override_eps",
        )

    # 2. 資料抓取與對齊 (固定 5 年)
    @st.cache_data(ttl=3600)
    def fetch_pe_data_rainbow_daily(symbol, period="5y", interval="1d"):
        try:
            ticker = yf.Ticker(symbol)

            # A. 抓取歷史股價
            hist_df = ticker.history(period=period, interval=interval)
            if hist_df.empty:
                return pd.DataFrame()

            hist_df = hist_df[["Close"]].copy()
            hist_df.index = (
                pd.to_datetime(hist_df.index).tz_localize(None).normalize()
            )
            hist_df = hist_df.sort_index().reset_index()
            hist_df.rename(columns={"index": "Date"}, inplace=True)

            # B. 抓取季報 EPS
            q_financials = ticker.quarterly_financials
            eps_series = None

            if not q_financials.empty:
                possible_eps_names = [
                    "Basic EPS",
                    "Diluted EPS",
                    "BasicEPS",
                    "DilutedEPS",
                    "Earnings Per Share",
                ]
                for name in possible_eps_names:
                    if name in q_financials.index:
                        eps_series = q_financials.loc[name].dropna()
                        if not eps_series.empty:
                            break

            if eps_series is None or len(eps_series) < 4:
                fallback_eps = ticker.info.get("trailingEps", None)
                if fallback_eps:
                    eps_df = pd.DataFrame(
                        {"TTM_EPS": [fallback_eps]},
                        index=[hist_df["Date"].min()],
                    )
                else:
                    return pd.DataFrame()
            else:
                eps_df = (
                    pd.DataFrame({"EPS": eps_series}).astype(float).sort_index()
                )
                eps_df.index = (
                    pd.to_datetime(eps_df.index).tz_localize(None).normalize()
                )
                eps_df["TTM_EPS"] = eps_df["EPS"].rolling(window=4).sum()
                eps_df = eps_df.dropna(subset=["TTM_EPS"])

            if eps_df.empty:
                return pd.DataFrame()

            eps_df = eps_df.reset_index()
            eps_df.rename(columns={"index": "Date"}, inplace=True)

            # C. 時間對齊 (僅向前補齊 ffill，避免預知未來資料)
            merged_df = pd.merge_asof(
                hist_df.sort_values("Date"),
                eps_df[["Date", "TTM_EPS"]].sort_values("Date"),
                on="Date",
                direction="backward",
            )

            merged_df["TTM_EPS"] = merged_df["TTM_EPS"].ffill()
            merged_df = merged_df.dropna(subset=["Close", "TTM_EPS"])

            # 計算每日歷史本益比
            merged_df["Hist_PE"] = merged_df["Close"] / merged_df["TTM_EPS"]

            return merged_df

        except Exception as e:
            st.error(f"解析 {symbol} 資料時發生錯誤: {e}")
            return pd.DataFrame()

    # 3. 讀取數據
    with st.spinner(f"正在讀取 {target_ticker} 近 5 年數據..."):
        df_pe = fetch_pe_data_rainbow_daily(
            symbol=target_ticker,
            period=period_option,
            interval=freq_map[interval_option],
        )

    if df_pe.empty or len(selected_pes) < 2:
        st.error(
            f"❌ 無法取得 {target_ticker} 數據，或本益比倍數選擇少於 2 個。"
        )
        st.info(
            "💡 提示：若為上櫃股票或季報缺失，可於「手動校正最新 TTM EPS」欄位手動填入數據。"
        )
    else:
        df_pe = df_pe.copy()

        # 手動覆寫最新 TTM EPS 邏輯
        if override_eps > 0:
            latest_ttm_original = df_pe["TTM_EPS"].iloc[-1]
            last_idx = df_pe[df_pe["TTM_EPS"] == latest_ttm_original].index
            df_pe.loc[last_idx, "TTM_EPS"] = override_eps
            df_pe["Hist_PE"] = df_pe["Close"] / df_pe["TTM_EPS"]

        # 計算本益比區間價格線
        for pe in selected_pes:
            df_pe[f"{pe}x"] = df_pe["TTM_EPS"] * pe

        # 4. 繪製彩虹版 Plotly 河流圖
        fig = go.Figure()
        rainbow_colors = [
            "rgba(148, 0, 211, 0.25)",
            "rgba(0, 0, 255, 0.25)",
            "rgba(0, 255, 0, 0.25)",
            "rgba(255, 255, 0, 0.25)",
            "rgba(255, 165, 0, 0.25)",
            "rgba(255, 0, 0, 0.25)",
        ]

        # 最底線 (底邊邊界)
        lowest_pe = selected_pes[0]
        fig.add_trace(
            go.Scatter(
                x=df_pe["Date"],
                y=df_pe[f"{lowest_pe}x"],
                mode="lines",
                line=dict(width=0.5, color="rgba(150, 150, 150, 0.3)"),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        # 彩虹區間填色
        for i in range(len(selected_pes) - 1):
            low_val, high_val = selected_pes[i], selected_pes[i + 1]
            color = rainbow_colors[i % len(rainbow_colors)]
            fig.add_trace(
                go.Scatter(
                    x=df_pe["Date"],
                    y=df_pe[f"{high_val}x"],
                    mode="lines",
                    line=dict(width=0.5, color="rgba(150, 150, 150, 0.2)"),
                    fill="tonexty",
                    fillcolor=color,
                    name=f"{low_val}x - {high_val}x PE",
                    hovertemplate=f"<b>{low_val}x - {high_val}x 區間</b><br>上限價: %{{y:.1f}} TWD<extra></extra>",
                )
            )

        # 收盤價實體線
        fig.add_trace(
            go.Scatter(
                x=df_pe["Date"],
                y=df_pe["Close"],
                mode="lines",
                name="收盤價",
                line=dict(color="#D32F2F", width=2.5),
                hovertemplate="<b>收盤價</b>: NT$%{y:.1f}<extra></extra>",
            )
        )

        # Layout 設置
        fig.update_layout(
            title=dict(
                text=f"{target_ticker} 本益比河流圖 (近 5 年) - 彩虹版",
                font=dict(size=20),
            ),
            xaxis=dict(
                title="日期",
                range=[df_pe["Date"].min(), df_pe["Date"].max()],
                showgrid=True,
                gridcolor="#E0E0E0",
                rangeselector=dict(
                    buttons=list(
                        [
                            dict(
                                count=6,
                                label="6月",
                                step="month",
                                stepmode="backward",
                            ),
                            dict(
                                count=1,
                                label="1年",
                                step="year",
                                stepmode="backward",
                            ),
                            dict(
                                count=3,
                                label="3年",
                                step="year",
                                stepmode="backward",
                            ),
                            dict(step="all", label="近5年"),
                        ]
                    )
                ),
                rangeslider=dict(visible=True),
                type="date",
            ),
            yaxis_title="價格 (TWD)",
            hovermode="x unified",
            template="plotly_white",
            height=650,
            margin=dict(l=10, r=10, t=60, b=10),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=12),
            ),
            yaxis=dict(tickformat=".1f"),
        )

        # 5. 版面排版：雙欄渲染 (左圖右統計)
        col_chart, col_metric = st.columns([3.2, 1.2])

        with col_chart:
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )

        with col_metric:
            latest_data = df_pe.iloc[-1]
            curr_eps = latest_data["TTM_EPS"]
            curr_price = latest_data["Close"]
            curr_pe = curr_price / curr_eps if curr_eps > 0 else 0

            # 計算近 5 年歷史 PE 統計
            valid_pes = (
                df_pe["Hist_PE"].replace([np.inf, -np.inf], np.nan).dropna()
            )

            pe_p20 = np.percentile(valid_pes, 20)
            pe_p50 = np.percentile(valid_pes, 50)
            pe_p80 = np.percentile(valid_pes, 80)

            pe_min = valid_pes.min()
            pe_max = valid_pes.max()
            pct_rank = (valid_pes < curr_pe).mean() * 100

            st.subheader("📌 當前 Valuation")
            st.metric("當前股價", f"NT$ {curr_price:.1f}")

            eps_label = "TTM EPS (近四季)"
            if override_eps > 0:
                eps_label += " ✏️(已校正)"
            st.metric(eps_label, f"NT$ {curr_eps:.2f}")

            # 便宜/合理/昂貴 判斷
            if curr_pe < pe_p20:
                status_color, status_text = "#43A047", "🟢 便宜 (偏低)"
            elif curr_pe > pe_p80:
                status_color, status_text = "#E53935", "🔴 昂貴 (偏高)"
            else:
                status_color, status_text = "#FB8C00", "🟡 合理 (適中)"

            st.markdown(
                f"**當前 PE:** <span style='color:{status_color}; font-size:22px; font-weight:bold;'>{curr_pe:.2f} 倍</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"**位階狀態:** <span style='color:{status_color}; font-weight:bold;'>{status_text}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"高於近 5 年歷史 {pct_rank:.0f}% 時間")

            st.markdown("---")
            st.subheader("📊 近 5 年歷史 PE 區間")

            pe_stats_data = {
                "位階別": [
                    "低點 (Min)",
                    "便宜 (20%)",
                    "合理 (50%)",
                    "昂貴 (80%)",
                    "高點 (Max)",
                ],
                "PE 倍數": [
                    f"{pe_min:.1f}x",
                    f"{pe_p20:.1f}x",
                    f"{pe_p50:.1f}x",
                    f"{pe_p80:.1f}x",
                    f"{pe_max:.1f}x",
                ],
                "對應目標價": [
                    f"{pe_min * curr_eps:.1f}",
                    f"{pe_p20 * curr_eps:.1f}",
                    f"{pe_p50 * curr_eps:.1f}",
                    f"{pe_p80 * curr_eps:.1f}",
                    f"{pe_max * curr_eps:.1f}",
                ],
            }
            st.dataframe(
                pd.DataFrame(pe_stats_data),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("查看近 5 年完整明細"):
            st.dataframe(
                df_pe.sort_values("Date", ascending=False).style.format({
                    "Close": "{:.1f}",
                    "TTM_EPS": "{:.2f}",
                    "Hist_PE": "{:.2f}",
                    **{f"{pe}x": "{:.1f}" for pe in selected_pes},
                }),
                use_container_width=True,
            )
