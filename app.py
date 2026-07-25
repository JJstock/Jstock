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
        "Forward (PE/EPS)": f"{info.get('forwardPE', 0):.2f} (EPS: {info.get('forwardEps', 0):.2f})",
        "PEG": PEG,
        "成長率": f"{growth*100:.2f}%",
    }, df


# --- 主程式流程 ---
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 主監控頁面",
    "🏦 金農專區",
    "📊 題材專區",
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
        "3711.TW": "日月光",
        "2303.TW": "聯電",
        "2327.TW": "國巨",
        "2383.TW": "台光電",
        "3037.TW": "欣興",
    }

# 側邊欄：新增與刪除監控股票
with st.sidebar:
    st.subheader("➕ 新增監控股票")
    market_type = st.radio(
        "選擇市場", ["上市 (.TW)", "上櫃 (.TWO)"], horizontal=True
    )
    new_ticker = st.text_input("輸入股票代號", placeholder="例如: 2330")
    new_name = st.text_input("輸入公司名稱", placeholder="例如: 台積電")

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

    st.subheader("📈 個股趨勢圖")
    selected_ticker = st.selectbox(
        "請選擇股票",
        list(st.session_state.my_stocks.keys()),
        format_func=lambda x: st.session_state.my_stocks[x],
    )
    if selected_ticker:
        plot_stock_chart(selected_ticker)

# --- TAB 2: 金農專區 ---
with tab2:
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

# --- TAB 3: 題材專區 ---
with tab3:
    st.subheader("📋 題材專區")
    topic_stocks = {
        "3008.TW": {"名稱": "大立光", "題材": "光學鏡頭"},
        "3481.TW": {"名稱": "群創", "題材": "面板封裝"},
        "1303.TW": {"名稱": "南亞", "題材": "玻纖布 CCL"},
        "8261.TW": {"名稱": "富鼎", "題材": "mosfet"},
        "2408.TW": {"名稱": "南亞科", "題材": "DRAM製造"},
        "6435.TWO": {"名稱": "大中", "題材": "mosfet"},
        "6488.TWO": {"名稱": "環球晶", "題材": "矽晶圓-美光"},
        "8299.TWO": {"名稱": "群聯", "題材": "快閃記憶體"},
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

# --- TAB 4: 月營收監控 ---
with tab4:
    st.write("### 📊 上市櫃營收監控")

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

    col1, col2 = st.columns([1, 3])
    with col1:
        sync_clicked = st.button("🔄 同步最新營收資料", key="sync_revenue_btn")
    with col2:
        if "revenue_data" in st.session_state:
            st.caption(
                f"✅ 目前已載入 {len(st.session_state.revenue_data)} 筆資料"
            )

    if sync_clicked:
        with st.spinner("正在下載並解析資料..."):
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

                    if "代號" not in df.columns:
                        st.error("找不到 '代號' 欄位，請檢查 CSV 欄位名稱。")
                        st.stop()

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
                    st.session_state.revenue_data = df
                    st.success(f"成功載入！共 {len(df)} 筆公司資料。")
                else:
                    st.error("未能讀取任何數據。")
            except Exception as e:
                st.error(f"同步過程發生錯誤：{e}")

    if "revenue_data" in st.session_state:
        df = st.session_state.revenue_data

        st.divider()
        st.write("### 📈 營收強勢成長股清單")

        c1, c2 = st.columns(2)
        with c1:
            yoy_threshold = st.slider(
                "年增率門檻 (%)", 0, 200, 20, step=5, key="yoy_slider"
            )
        with c2:
            mom_threshold = st.slider(
                "月增率門檻 (%)", -50, 100, 5, step=5, key="mom_slider"
            )

        strong_growth = (
            df[
                (df["年增率(YoY%)"] > yoy_threshold)
                & (df["月增率(MoM%)"] > mom_threshold)
            ]
            .dropna(subset=["年增率(YoY%)"])
            .sort_values("年增率(YoY%)", ascending=False)
        )

        st.caption(
            f"共符合 {len(strong_growth)} 筆（年增率 > {yoy_threshold}% 且 月增率 >"
            f" {mom_threshold}%）"
        )

        def highlight_negative(val):
            color = "red" if val < 0 else "black"
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
        st.info("👆 請先點擊上方按鈕載入資料")


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


# --- TAB 7: 通用台股本益比河流圖 (彩虹版 - 修正時間精度與 TTM 邏輯 Bug) ---
with tab7:
    st.header("本益比河流圖 (上市/上櫃) - 彩虹色調")
    st.caption("資料來源：yfinance (自動進行 TTM EPS 與每日股價對齊)")

    # 1. 股票代號與控制參數設定區
    col_sym, col_market, col_period = st.columns([2, 1, 2])

    with col_sym:
        stock_code = st.text_input("輸入股票代號", value="2330").strip()

    with col_market:
        market_suffix = st.selectbox(
            "市場類別", options=[".TW", ".TWO"], index=0
        )

    with col_period:
        period_option = st.selectbox(
            "歷史時間範圍",
            options=["1y", "2y", "3y", "5y", "max"],
            index=3,  # 預設 5y
        )

    target_ticker = f"{stock_code}{market_suffix}" if stock_code else "2330.TW"

    # 控制選項與輸入框
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
        default_pe_ranges = [10, 12, 16, 20, 24, 28, 32]

        selected_pes = st.multiselect(
            "選擇本益比倍數區間",
            options=available_options,
            default=default_pe_ranges,
        )
        selected_pes = sorted(selected_pes)

    with col_eps:
        override_eps = st.number_input(
            "手動校正最新 TTM EPS ( > 0 優先採用)",
            value=0.0,
            step=0.5,
            format="%.2f",
            help="yfinance 季報常有延遲或數據誤差，若已知最新 TTM EPS，可在此手動輸入校正。",
        )

    # 2. 資料抓取與對齊函式
    @st.cache_data(ttl=3600)
    def fetch_pe_data_rainbow(symbol, period="5y"):
        try:
            ticker = yf.Ticker(symbol)

            # A. 抓取歷史股價
            hist_df = ticker.history(period=period)
            if hist_df.empty:
                return pd.DataFrame()

            hist_df = hist_df[["Close"]].copy()
            hist_df.index = (
                pd.to_datetime(hist_df.index).tz_localize(None).normalize()
            )
            hist_df = hist_df.sort_index()

            # B. 抓取季報並計算近四季累積 EPS (TTM EPS)
            q_financials = ticker.quarterly_financials
            if q_financials.empty:
                return pd.DataFrame()

            # 安全判斷 EPS 欄位
            eps_row = None
            for eps_name in [
                "Basic EPS",
                "Diluted EPS",
                "BasicEPS",
                "DilutedEPS",
            ]:
                if eps_name in q_financials.index:
                    eps_row = q_financials.loc[eps_name]
                    break

            if eps_row is None:
                return pd.DataFrame()

            # 整理季報 EPS 時間序列 (由舊到新排序)
            eps_df = (
                pd.DataFrame({"EPS": eps_row}).dropna().astype(float).sort_index()
            )
            eps_df.index = pd.to_datetime(eps_df.index).tz_localize(None)

            # 計算滾動近 4 季 EPS 之和 (Rolling TTM)
            eps_df["TTM_EPS"] = eps_df["EPS"].rolling(window=4).sum()

            # C. 將每日股價與季報 TTM EPS 進行合併，並向前填補 (ffill)
            merged_df = pd.merge(
                hist_df,
                eps_df[["TTM_EPS"]],
                left_index=True,
                right_index=True,
                how="left",
            )
            merged_df["TTM_EPS"] = merged_df["TTM_EPS"].ffill()

            # 剔除尚未累積滿 4 季 TTM EPS 的早期空值
            merged_df = merged_df.dropna(subset=["TTM_EPS", "Close"])
            merged_df.reset_index(inplace=True)
            merged_df.rename(columns={"index": "Date"}, inplace=True)

            return merged_df
        except Exception as e:
            st.error(f"資料抓取失敗: {e}")
            return pd.DataFrame()

    # 3. 讀取資料與套用 override_eps
    with st.spinner(
        f"正在讀取 {target_ticker} 歷史價格與財務數據 (彩虹版)..."
    ):
        df_pe = fetch_pe_data_rainbow(
            symbol=target_ticker, period=period_option
        )

    if df_pe.empty or len(selected_pes) < 2:
        st.warning(
            f"⚠️ 無法取得 {target_ticker} 資料，或請至少選擇 2 個以上的本益比倍數！"
        )
    else:
        df_pe = df_pe.copy()

        # 🌟【修正後的手動覆寫邏輯】：精確替換最後一段（最新一季）的 TTM EPS
        if override_eps > 0:
            latest_ttm_original = df_pe["TTM_EPS"].iloc[-1]
            # 找到最後連續等於最新原始 TTM 的 index 進行安全替換，避免誤傷歷史同數值的區間
            last_segment_mask = (
                df_pe["TTM_EPS"] == latest_ttm_original
            ) & (df_pe.index >= df_pe[df_pe["TTM_EPS"] == latest_ttm_original].index.max() - 120)
            df_pe.loc[last_segment_mask, "TTM_EPS"] = override_eps

        # 計算各 PE 河流線條
        for pe in selected_pes:
            df_pe[f"{pe}x"] = df_pe["TTM_EPS"] * pe

        # 4. 繪製圖表
        fig = go.Figure()

        rainbow_colors = [
            "rgba(148, 0, 211, 0.25)",  # 紫
            "rgba(0, 0, 255, 0.25)",  # 藍
            "rgba(0, 255, 0, 0.25)",  # 綠
            "rgba(255, 255, 0, 0.25)",  # 黃
            "rgba(255, 165, 0, 0.25)",  # 橙
            "rgba(255, 0, 0, 0.25)",  # 紅
        ]

        # 繪製最低本益比基底線
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

        # 填滿本益比彩虹區間
        num_intervals = len(selected_pes) - 1
        for i in range(num_intervals):
            low_pe_val = selected_pes[i]
            high_pe_val = selected_pes[i + 1]

            color_idx = i % len(rainbow_colors)
            current_fill_color = rainbow_colors[color_idx]

            fig.add_trace(
                go.Scatter(
                    x=df_pe["Date"],
                    y=df_pe[f"{high_pe_val}x"],
                    mode="lines",
                    line=dict(width=0.5, color="rgba(150, 150, 150, 0.2)"),
                    fill="tonexty",
                    fillcolor=current_fill_color,
                    name=f"{low_pe_val}x - {high_pe_val}x PE",
                    hovertemplate=f"<b>{low_pe_val}x - {high_pe_val}x 區間</b><br>上限價: %{{y:.1f}} TWD<extra></extra>",
                )
            )

        # 🌟【補上】：實際收盤價（Close）折線，置於最上層
        fig.add_trace(
            go.Scatter(
                x=df_pe["Date"],
                y=df_pe["Close"],
                mode="lines",
                name="收盤價",
                line=dict(color="black", width=2),
                hovertemplate="<b>日期</b>: %{x|%Y-%m-%d}<br><b>收盤價</b>: %{y:.2f} TWD<extra></extra>",
            )
        )

        # 圖表樣式設定
        fig.update_layout(
            title=f"{target_ticker} 本益比河流圖",
            xaxis_title="日期",
            yaxis_title="價格 (TWD)",
            hovermode="x unified",
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
            margin=dict(l=20, r=20, t=60, b=20),
        )

        st.plotly_chart(fig, use_container_width=True)

        # 股價實體線
        fig.add_trace(
            go.Scatter(
                x=df_pe["Date"],
                y=df_pe["Close"],
                mode="lines",
                name=f"{target_ticker} 收盤價",
                line=dict(color="#D32F2F", width=3),
                hovertemplate="<b>收盤價</b>: NT$%{y:.1f}<extra></extra>",
            )
        )

        fig.update_layout(
            title=dict(
                text=f"{target_ticker} 本益比河流圖 ({period_option}) - 彩虹版",
                font=dict(size=20),
            ),
            xaxis_title="日期",
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

        col_chart, col_metric = st.columns([3.5, 1])

        with col_chart:
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )

        with col_metric:
            latest_data = df_pe.iloc[-1]
            if latest_data["TTM_EPS"] > 0:
                current_pe_ratio = (
                    latest_data["Close"] / latest_data["TTM_EPS"]
                )
            else:
                current_pe_ratio = 0

            st.subheader("📌 最新 Valuation")
            st.metric("標的代號", target_ticker)
            st.metric(
                "資料日期",
                pd.to_datetime(latest_data["Date"]).strftime("%Y-%m-%d"),
            )
            st.metric("當前股價", f"NT$ {latest_data['Close']:.1f}")

            eps_label = "TTM EPS (近四季)"
            if override_eps > 0:
                eps_label += " ✏️(已校正)"
            st.metric(eps_label, f"NT$ {latest_data['TTM_EPS']:.2f}")

            pe_color = "black"
            if current_pe_ratio > 0:
                if current_pe_ratio <= selected_pes[0]:
                    pe_color = "purple"
                elif current_pe_ratio >= selected_pes[-1]:
                    pe_color = "red"
                else:
                    pe_color = "green"

            st.markdown(
                f"當前本益比 (PE): <span style='color:{pe_color}; font-size:24px; font-weight:bold;'>{current_pe_ratio:.2f} 倍</span>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"選取範圍: {selected_pes[0]}x (紫) ~ {selected_pes[-1]}x (紅)"
            )

        with st.expander("查看完整原始數據對齊明細"):
            st.dataframe(
                df_pe.sort_values("Date", ascending=False).style.format({
                    "Close": "{:.1f}",
                    "TTM_EPS": "{:.2f}",
                    **{f"{pe}x": "{:.1f}" for pe in selected_pes},
                }),
                use_container_width=True,
            )
