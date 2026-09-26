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
import os

st.set_page_config(page_title="Jstok股價監控", layout="wide")
st.title("JStok 📊 MA20+60 與財報監控")

#讀取營收及三率三升
def read_twse_csv_from_bytes(content_bytes):
    last_err = None
    for enc in ["utf-8-sig", "big5", "cp950"]:
        for header_row in [0, 1]:
            try:
                decoded_text = content_bytes.decode(enc)
                tmp = pd.read_csv(StringIO(decoded_text), header=header_row)
                tmp.columns = tmp.columns.str.strip().str.replace("\u3000", "", regex=False)
                if "公司代號" in tmp.columns:
                    return tmp
            except Exception as e:
                last_err = e
                continue
    raise ValueError(f"無法辨識檔案格式（已嘗試多種編碼與標題列位置）：{last_err}")


@st.cache_data(ttl=3600)
def fetch_and_merge_github_data():
    sources = [
        {"url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TW.csv", "suffix": ".TW"},
        {"url": "https://raw.githubusercontent.com/JJstock/Jstock/refs/heads/main/TWO.csv", "suffix": ".TWO"},
    ]
    all_dfs = []
    for src in sources:
        try:
            response = requests.get(src["url"], timeout=15)
            response.raise_for_status()
            df = read_twse_csv_from_bytes(response.content)
            if "公司代號" in df.columns:
                df["公司代號"] = df["公司代號"].astype(str).str.strip() + src["suffix"]
            all_dfs.append(df)
        except Exception as e:
            st.warning(f"讀取 {src['url']} 失敗: {e}")
    return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()


def load_revenue_data():
    """把 Tab4 原本的資料處理邏輯包成一個函式，供全域先行呼叫。"""
    if "revenue_data" in st.session_state:
        return  # 已經載入過，不重複執行

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

                cols_to_keep = ["代號", "名稱", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
                df = df[[c for c in cols_to_keep if c in df.columns]]

                code_numeric_part = (
                    df["代號"].astype(str).str.replace(r"\.(TW|TWO)$", "", regex=True)
                )
                df = df[pd.to_numeric(code_numeric_part, errors="coerce").notna()]

                for col in ["月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]:
                    if col in df.columns:
                        df[col] = (
                            df[col].astype(str).str.strip()
                            .str.replace(",", "", regex=False)
                            .replace(r"^-+$", "0", regex=True)
                        )
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df.drop_duplicates(subset="代號", keep="first").reset_index(drop=True)

                # 讀取 rate.csv 並安全合併三率三升資訊
                rate_csv_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "rate.csv"
                )
                try:
                    df_rate = None
                    last_err = None
                    for enc in ["utf-8-sig", "big5", "cp950", "utf-8"]:
                        try:
                            df_rate = pd.read_csv(
                                rate_csv_path, dtype=str, encoding=enc, sep=None, engine="python"
                            )
                            df_rate.columns = df_rate.columns.str.strip()
                            break
                        except Exception as e:
                            last_err = e
                            df_rate = None

                    if df_rate is None:
                        raise ValueError(f"無法辨識 rate.csv 編碼：{last_err}")

                    code_col_in_rate = "公司代號" if "公司代號" in df_rate.columns else "代號"
                    if code_col_in_rate not in df_rate.columns:
                        raise ValueError(f"rate.csv 缺少公司代號欄位，實際欄位為：{list(df_rate.columns)}")
                    if "三率三升" not in df_rate.columns:
                        raise ValueError(f"rate.csv 缺少三率三升欄位，實際欄位為：{list(df_rate.columns)}")

                    df_rate["temp_merge_code"] = (
                        df_rate[code_col_in_rate].astype(str).str.strip()
                        .str.replace(r"\.(TW|TWO)$", "", regex=True)
                    )
                    df_rate_dedup = df_rate.drop_duplicates(subset="temp_merge_code", keep="first")

                    df["temp_merge_code"] = (
                        df["代號"].astype(str).str.strip()
                        .str.replace(r"\.(TW|TWO)$", "", regex=True)
                    )

                    df = pd.merge(
                        df, df_rate_dedup[["temp_merge_code", "三率三升"]],
                        on="temp_merge_code", how="left",
                    )
                    df["三率三升"] = df["三率三升"].fillna("0")
                    df["三率三升"] = df["三率三升"].apply(
                        lambda x: "🔥 三率三升" if str(x).strip() in ["1", "1.0", "True", "true"] else "-"
                    )
                    df = df.drop(columns=["temp_merge_code"])

                except FileNotFoundError:
                    st.warning(f"⚠️ 找不到 rate.csv（預期路徑：{rate_csv_path}）")
                    df["三率三升"] = "找不到檔案"
                except Exception as e:
                    st.warning(f"⚠️ 讀取 rate.csv 發生錯誤：{e}")
                    df["三率三升"] = "讀取錯誤"
                    if "temp_merge_code" in df.columns:
                        df = df.drop(columns=["temp_merge_code"])

                base_cols = ["代號", "名稱", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
                existing_base = [c for c in base_cols if c in df.columns]
                other_cols = [c for c in df.columns if c not in existing_base and c != "三率三升"]
                df = df[existing_base + other_cols + (["三率三升"] if "三率三升" in df.columns else [])]

                st.session_state.revenue_data = df
            else:
                st.session_state.revenue_data = pd.DataFrame()
                st.error("未能讀取任何數據。")
        except Exception as e:
            st.session_state.revenue_data = pd.DataFrame()
            st.error(f"自動載入過程發生錯誤：{e}")

@st.cache_data(ttl=3600)
def fetch_institutional_investors_raw(date_str):
    """抓某一天 TWSE T86 三大法人買賣超日報（僅上市股票）"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "OK" or not data.get("data"):
            return None
        df = pd.DataFrame(data["data"], columns=data["fields"])
        return df
    except Exception:
        return None


def to_roc_date(d):
    """西元日期轉民國格式 115/06/04"""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


@st.cache_data(ttl=3600)
def fetch_tpex_institutional_investors_raw(date_roc):
    """抓某一天 TPEx 三大法人買賣明細（僅上櫃股票）"""
    url = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
    params = {"type": "Daily", "sect": "EW", "date": date_roc, "id": "", "response": "json"}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        tables = data.get("tables") or []
        if not tables:
            return None
        rows = tables[0].get("data") or []
        if not rows:
            return None
        return rows
    except Exception:
        return None


def parse_tpex_rows(rows):
    """解析 TPEx 回傳的原始列資料為三大法人買賣超（張）"""
    records = []
    for r in rows:
        if not r or len(r) < 24:
            continue
        records.append({
            "code": str(r[0]).strip().strip("=").strip('"'),
            "外資買賣超(張)": r[10],
            "投信買賣超(張)": r[13],
            "自營商買賣超(張)": r[22],
        })
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    for col in ["外資買賣超(張)", "投信買賣超(張)", "自營商買賣超(張)"]:
        df[col] = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
        df[col] = (pd.to_numeric(df[col], errors="coerce").fillna(0) / 1000).round(0)

    df["代號"] = df["code"].astype(str).str.strip().str.zfill(4) + ".TWO"
    df["三大法人合計(張)"] = (
        df["外資買賣超(張)"] + df["投信買賣超(張)"] + df["自營商買賣超(張)"]
    )
    return df[["代號", "外資買賣超(張)", "投信買賣超(張)", "自營商買賣超(張)", "三大法人合計(張)"]]


def load_institutional_data():
    """全域載入最近一個有資料的交易日的三大法人買賣超（上市 TWSE + 上櫃 TPEx）"""
    if "institutional_data" in st.session_state:
        return

    from zoneinfo import ZoneInfo

    today = datetime.datetime.now(ZoneInfo("Asia/Taipei")).date()
    df_twse_raw = None
    used_date = None

    # 找最近一個有 TWSE 資料的交易日
    for i in range(10):
        check_date = today - datetime.timedelta(days=i)
        df_try = fetch_institutional_investors_raw(check_date.strftime("%Y%m%d"))
        if df_try is not None and not df_try.empty:
            df_twse_raw = df_try
            used_date = check_date
            break

    df_out_list = []

    # --- 處理 TWSE（上市）---
    if df_twse_raw is not None:
        df_twse_raw.columns = df_twse_raw.columns.str.strip()
        numeric_cols = [c for c in df_twse_raw.columns if c not in ["證券代號", "證券名稱"]]
        for col in numeric_cols:
            df_twse_raw[col] = df_twse_raw[col].astype(str).str.strip().str.replace(",", "", regex=False)
            df_twse_raw[col] = pd.to_numeric(df_twse_raw[col], errors="coerce").fillna(0)

        df_twse_raw["證券代號"] = df_twse_raw["證券代號"].astype(str).str.strip()

        def has(col):
            return col in df_twse_raw.columns

        foreign_buy = [c for c in ["外陸資買進股數(不含外資自營商)", "外資自營商買進股數"] if has(c)]
        foreign_sell = [c for c in ["外陸資賣出股數(不含外資自營商)", "外資自營商賣出股數"] if has(c)]
        dealer_buy = [c for c in ["自營商買進股數(自行買賣)", "自營商買進股數(避險)"] if has(c)]
        dealer_sell = [c for c in ["自營商賣出股數(自行買賣)", "自營商賣出股數(避險)"] if has(c)]

        df_twse_out = pd.DataFrame()
        df_twse_out["代號"] = df_twse_raw["證券代號"] + ".TW"
        df_twse_out["外資買賣超(張)"] = (
            (df_twse_raw[foreign_buy].sum(axis=1) - df_twse_raw[foreign_sell].sum(axis=1)) / 1000
        ).round(0)
        df_twse_out["投信買賣超(張)"] = (
            (df_twse_raw.get("投信買進股數", 0) - df_twse_raw.get("投信賣出股數", 0)) / 1000
        ).round(0)
        df_twse_out["自營商買賣超(張)"] = (
            (df_twse_raw[dealer_buy].sum(axis=1) - df_twse_raw[dealer_sell].sum(axis=1)) / 1000
        ).round(0)
        df_twse_out["三大法人合計(張)"] = (
            df_twse_out["外資買賣超(張)"] + df_twse_out["投信買賣超(張)"] + df_twse_out["自營商買賣超(張)"]
        )
        df_out_list.append(df_twse_out)

    # --- 處理 TPEx（上櫃）：用同一天的民國日期嘗試 ---
    if used_date is not None:
        tpex_rows = fetch_tpex_institutional_investors_raw(to_roc_date(used_date))
        if tpex_rows:
            df_tpex_out = parse_tpex_rows(tpex_rows)
            if not df_tpex_out.empty:
                df_out_list.append(df_tpex_out)

    if not df_out_list:
        st.session_state.institutional_data = pd.DataFrame()
        st.session_state.institutional_data_date = None
        return

    df_out = pd.concat(df_out_list, ignore_index=True)
    st.session_state.institutional_data = df_out
    st.session_state.institutional_data_date = used_date

# 🔑 關鍵：在所有 tab 定義之前，先呼叫一次
load_revenue_data()
load_institutional_data()
load_revenue_data()

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
tab1, tab2, tab3, tab4, tab5, tab6, tab7 ,tab8,tab9,tab10= st.tabs([
    "📊 主監控頁面",
    "📈 題材專區",
    "🏦 金農專區",
    "📈 月營收監控",
    "📊 重訊查詢",
    "🚀 查詢 ETF 成分股",
    "📈 本益比河流圖",
    "🧮 投資組合分析工具",
    "📊 三大法人",
    "⭐ 綜合評分",
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
            
    st.markdown("---")
    
    st.subheader("🔄 清除快取")
    if st.button("清除快取並重新載入", use_container_width=True):
        st.cache_data.clear()
        if "revenue_data" in st.session_state:
            del st.session_state["revenue_data"]
        if "institutional_data" in st.session_state:
            del st.session_state["institutional_data"]
        st.session_state["last_cache_clear"] = pd.Timestamp.now(tz="Asia/Taipei").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        st.success("✅ 快取已清除，正在重新載入...")
        time.sleep(1)
        st.rerun()

    if "last_cache_clear" in st.session_state:
        st.caption(f"上次清除快取：{st.session_state['last_cache_clear']} (台灣時間UTC+8)")

# --- TAB 1: 主監控頁面 ---
with tab1:
    st.subheader("📋 監控清單總覽")
    data_list = []
    for symbol, name in st.session_state.my_stocks.items():
        d, _ = get_stock_data(symbol)
        if d:
            display_name = f"{symbol} {name}"
            d["代號"] = symbol
            d["名稱"] = display_name
            data_list.append(d)
    if st.session_state.get("institutional_data_date"):
        st.caption(f"📅 三大法人資料日期：{st.session_state['institutional_data_date']}")
        
    if data_list:
        df_final = pd.DataFrame(data_list)

        # 合併 revenue_data（含三率三升、月增率、年增率、累計年增率），用代號比對
        merge_cols = ["三率三升", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
        revenue_df = st.session_state.get("revenue_data")

        if revenue_df is not None and not revenue_df.empty and "代號" in revenue_df.columns:
            existing_merge_cols = [c for c in merge_cols if c in revenue_df.columns]

            df_final["temp_merge_code"] = df_final["代號"].astype(str).str.strip()

            revenue_merge = revenue_df[["代號"] + existing_merge_cols].copy()
            revenue_merge["temp_merge_code"] = revenue_merge["代號"].astype(str).str.strip()
            revenue_merge = revenue_merge.drop_duplicates(subset="temp_merge_code", keep="first")

            df_final = pd.merge(
                df_final,
                revenue_merge[["temp_merge_code"] + existing_merge_cols],
                on="temp_merge_code",
                how="left",
            )
            df_final = df_final.drop(columns=["temp_merge_code"])

            if "三率三升" in df_final.columns:
                df_final["三率三升"] = df_final["三率三升"].fillna("-")
        else:
            st.warning("⚠️ 尚未取得營收資料（revenue_data），三率三升與營收欄位將顯示為空")

        for col in merge_cols:
            if col not in df_final.columns:
                df_final[col] = None if col != "三率三升" else "-"

        # 合併三大法人買賣超（僅上市 .TW 股票有資料，上櫃會是空白）
        insti_cols = ["外資買賣超(張)", "投信買賣超(張)", "自營商買賣超(張)", "三大法人合計(張)"]
        insti_df = st.session_state.get("institutional_data")

        if insti_df is not None and not insti_df.empty:
            df_final["temp_merge_code2"] = df_final["代號"].astype(str).str.strip()
            insti_merge = insti_df.copy()
            insti_merge["temp_merge_code2"] = insti_merge["代號"].astype(str).str.strip()
            insti_merge = insti_merge.drop_duplicates(subset="temp_merge_code2", keep="first")

            df_final = pd.merge(
                df_final,
                insti_merge[["temp_merge_code2"] + insti_cols],
                on="temp_merge_code2",
                how="left",
            )
            df_final = df_final.drop(columns=["temp_merge_code2"])

        for col in insti_cols:
            if col not in df_final.columns:
                df_final[col] = None

        # 顯示時不需要單獨的「代號」欄位（已經併入名稱顯示了）
        df_final = df_final.drop(columns=["代號"]).set_index("名稱")

        def highlight_negative(val):
            color = "red" if isinstance(val, (int, float)) and val < 0 else "black"
            return f"color: {color}"

        styled_df_final = df_final.style.map(
            highlight_negative,
            subset=["成長率","月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]+ insti_cols,
        )

        st.dataframe(
            styled_df_final,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn("股票名稱"),
                "現價": st.column_config.TextColumn("現價"),
                "狀態": st.column_config.TextColumn("狀態", width="medium"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS"),
                "CurrentYear (PE/EPS)": st.column_config.TextColumn("CurrentYear PE/EPS"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS"),
                "PEG": st.column_config.TextColumn("PEG (trail/growth)"),
                "成長率": st.column_config.NumberColumn("成長率", format="%.2f%%", width="small"),
                "三率三升": st.column_config.TextColumn("三率三升"),
                "月增率(MoM%)": st.column_config.NumberColumn("營收MoM", format="%.2f%%", width="small"),
                "年增率(YoY%)": st.column_config.NumberColumn("營收YoY", format="%.2f%%", width="small"),
                "累計年增率(%)": st.column_config.NumberColumn("累計年增率", format="%.2f%%", width="small"),
                "外資買賣超(張)": st.column_config.NumberColumn("外資買賣超(張)", format="%d", width="small"),
                "投信買賣超(張)": st.column_config.NumberColumn("投信買賣超(張)", format="%d", width="small"),
                "自營商買賣超(張)": st.column_config.NumberColumn("自營商買賣超(張)", format="%d", width="small"),
                "三大法人合計(張)": st.column_config.NumberColumn("三大法人合計(張)", format="%d", width="small"),
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

    if st.session_state.get("institutional_data_date"):
        st.caption(f"📅 三大法人資料日期：{st.session_state['institutional_data_date']}")

    topic_stocks = {
        "6139.TW": {"名稱": "亞翔", "題材": "廠務"},
        "2404.TW": {"名稱": "漢唐", "題材": "廠務"},
        "6691.TW": {"名稱": "洋基工程", "題材": "廠務"},
        "2409.TW": {"名稱": "友達", "題材": "玻璃基板-康寧"},
        "3481.TW": {"名稱": "群創", "題材": "玻璃基板-台積電"},
        "2049.TW": {"名稱": "上銀", "題材": "機器人"},
        "4576.TW": {"名稱": "大銀微系統", "題材": "精密定位-矽光子.先進封裝"},
        "3008.TW": {"名稱": "大立光", "題材": "光學鏡頭"},
        "3406.TW": {"名稱": "玉晶光", "題材": "光學鏡頭"},
        "2059.TW": {"名稱": "川湖", "題材": "滑軌"},
        "3017.TW": {"名稱": "奇鋐", "題材": "散熱"},
        "2327.TW": {"名稱": "國巨", "題材": "被動元件"},
        "1303.TW": {"名稱": "南亞", "題材": "玻纖布 CCL"},
        "2382.TW": {"名稱": "廣達", "題材": "伺服器"},
        "3231.TW": {"名稱": "緯創", "題材": "伺服器"},
        "6669.TW": {"名稱": "緯穎", "題材": "伺服器"},
        "2408.TW": {"名稱": "南亞科", "題材": "DRAM製造"},
        "2344.TW": {"名稱": "華邦電", "題材": "記憶體"},
        "3006.TW": {"名稱": "晶豪科", "題材": "記憶體"},
        "8299.TWO": {"名稱": "群聯", "題材": "快閃記憶體"},
    }
    topic_data = []
    for sym, info_dict in topic_stocks.items():
        metrics_dict, df = get_stock_data(sym)
        if metrics_dict is None:
            continue
        row = {
            "代號": sym,
            "名稱": f"{sym} {info_dict['名稱']}",
            "題材": info_dict["題材"],
        }
        row.update(metrics_dict)
        topic_data.append(row)

    if topic_data:
        df_topic = pd.DataFrame(topic_data)

        # 合併 revenue_data（含三率三升、月增率、年增率、累計年增率），用代號比對
        merge_cols = ["三率三升", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
        revenue_df = st.session_state.get("revenue_data")

        if revenue_df is not None and not revenue_df.empty and "代號" in revenue_df.columns:
            existing_merge_cols = [c for c in merge_cols if c in revenue_df.columns]

            df_topic["temp_merge_code"] = df_topic["代號"].astype(str).str.strip()

            revenue_merge = revenue_df[["代號"] + existing_merge_cols].copy()
            revenue_merge["temp_merge_code"] = revenue_merge["代號"].astype(str).str.strip()
            revenue_merge = revenue_merge.drop_duplicates(subset="temp_merge_code", keep="first")

            df_topic = pd.merge(
                df_topic,
                revenue_merge[["temp_merge_code"] + existing_merge_cols],
                on="temp_merge_code",
                how="left",
            )
            df_topic = df_topic.drop(columns=["temp_merge_code"])

            if "三率三升" in df_topic.columns:
                df_topic["三率三升"] = df_topic["三率三升"].fillna("-")
        else:
            st.warning("⚠️ 尚未取得營收資料（revenue_data），三率三升與營收欄位將顯示為空")

        for col in merge_cols:
            if col not in df_topic.columns:
                df_topic[col] = None if col != "三率三升" else "-"

        # 合併三大法人買賣超（上市 TWSE + 上櫃 TPEx），用代號比對
        insti_cols = ["外資買賣超(張)", "投信買賣超(張)", "自營商買賣超(張)", "三大法人合計(張)"]
        insti_df = st.session_state.get("institutional_data")

        if insti_df is not None and not insti_df.empty:
            df_topic["temp_merge_code2"] = df_topic["代號"].astype(str).str.strip()
            insti_merge = insti_df.copy()
            insti_merge["temp_merge_code2"] = insti_merge["代號"].astype(str).str.strip()
            insti_merge = insti_merge.drop_duplicates(subset="temp_merge_code2", keep="first")

            df_topic = pd.merge(
                df_topic,
                insti_merge[["temp_merge_code2"] + insti_cols],
                on="temp_merge_code2",
                how="left",
            )
            df_topic = df_topic.drop(columns=["temp_merge_code2"])

        for col in insti_cols:
            if col not in df_topic.columns:
                df_topic[col] = None

        # 顯示時不需要單獨的「代號」欄位（已經併入名稱顯示了）
        df_topic = df_topic.drop(columns=["代號"]).set_index("名稱")

        def highlight_negative(val):
            color = "red" if isinstance(val, (int, float)) and val < 0 else "black"
            return f"color: {color}"

        styled_df_topic = df_topic.style.map(
            highlight_negative,
            subset=["成長率", "月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"] + insti_cols,
        )

        st.dataframe(
            styled_df_topic,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn("股票名稱"),
                "題材": st.column_config.TextColumn("題材"),
                "現價": st.column_config.TextColumn("現價"),
                "狀態": st.column_config.TextColumn("狀態"),
                "Trailing (PE/EPS)": st.column_config.TextColumn("Trailing PE/EPS"),
                "Forward (PE/EPS)": st.column_config.TextColumn("Forward PE/EPS"),
                "PEG": st.column_config.TextColumn("PEG (trail/growth)"),
                "成長率": st.column_config.NumberColumn("成長率", format="%.2f%%", width="small"),
                "三率三升": st.column_config.TextColumn("三率三升"),
                "月增率(MoM%)": st.column_config.NumberColumn("營收MoM", format="%.2f%%", width="small"),
                "年增率(YoY%)": st.column_config.NumberColumn("營收YoY", format="%.2f%%", width="small"),
                "累計年增率(%)": st.column_config.NumberColumn("累計年增率", format="%.2f%%", width="small"),
                "外資買賣超(張)": st.column_config.NumberColumn("外資買賣超(張)", format="%d", width="small"),
                "投信買賣超(張)": st.column_config.NumberColumn("投信買賣超(張)", format="%d", width="small"),
                "自營商買賣超(張)": st.column_config.NumberColumn("自營商買賣超(張)", format="%d", width="small"),
                "三大法人合計(張)": st.column_config.NumberColumn("三大法人合計(張)", format="%d", width="small"),
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
        "2834.TW": "台企銀",
        "2801.TW": "彰銀",
        "2812.TW": "台中銀",
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
            "代號": sym,
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
        df_fin = pd.DataFrame(finance_data)

        # 合併 revenue_data 的月增率、年增率、累計年增率（不含三率三升），用代號比對
        merge_cols = ["月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"]
        revenue_df = st.session_state.get("revenue_data")

        if revenue_df is not None and not revenue_df.empty and "代號" in revenue_df.columns:
            existing_merge_cols = [c for c in merge_cols if c in revenue_df.columns]

            df_fin["temp_merge_code"] = df_fin["代號"].astype(str).str.strip()

            revenue_merge = revenue_df[["代號"] + existing_merge_cols].copy()
            revenue_merge["temp_merge_code"] = revenue_merge["代號"].astype(str).str.strip()
            revenue_merge = revenue_merge.drop_duplicates(subset="temp_merge_code", keep="first")

            df_fin = pd.merge(
                df_fin,
                revenue_merge[["temp_merge_code"] + existing_merge_cols],
                on="temp_merge_code",
                how="left",
            )
            df_fin = df_fin.drop(columns=["temp_merge_code"])
        else:
            st.warning("⚠️ 尚未取得營收資料（revenue_data），營收欄位將顯示為空")

        for col in merge_cols:
            if col not in df_fin.columns:
                df_fin[col] = None

        df_fin = df_fin.drop(columns=["代號"]).set_index("名稱")

        def highlight_negative(val):
            color = "red" if isinstance(val, (int, float)) and val < 0 else "black"
            return f"color: {color}"

        styled_df_fin = df_fin.style.map(
            highlight_negative,
            subset=["月增率(MoM%)", "年增率(YoY%)", "累計年增率(%)"],
        )

        st.dataframe(
            styled_df_fin,
            use_container_width=True,
            column_config={
                "_index": st.column_config.TextColumn(
                    "股票名稱", width="medium"
                ),
                "現價": st.column_config.TextColumn("現價"),
                "狀態": st.column_config.TextColumn("狀態"),
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
                "月增率(MoM%)": st.column_config.NumberColumn(
                    "營收MoM", format="%.2f%%", width="small"
                ),
                "年增率(YoY%)": st.column_config.NumberColumn(
                    "營收YoY", format="%.2f%%", width="small"
                ),
                "累計年增率(%)": st.column_config.NumberColumn(
                    "累計年增率", format="%.2f%%", width="small"
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

# --- TAB 4: 月營收監控 ---
with tab4:
    st.write("### 📊 上市櫃營收強勢成長股清單")

    if "revenue_data" in st.session_state and not st.session_state.revenue_data.empty:
        df = st.session_state.revenue_data
        
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            yoy_threshold = st.slider("年增率門檻 (%)", 0, 200, 20, step=5, key="yoy_slider")
        with c2:
            mom_threshold = st.slider("月增率門檻 (%)", -50, 100, 5, step=5, key="mom_slider")
        with c3:
            st.write("")
            only_triple_rise = st.checkbox("🔥 只顯示三率三升", value=False, key="triple_rise_checkbox")

        strong_growth = df[
            (df["年增率(YoY%)"] > yoy_threshold) & (df["月增率(MoM%)"] > mom_threshold)
        ].dropna(subset=["年增率(YoY%)"])

        if only_triple_rise:
            strong_growth = strong_growth[strong_growth["三率三升"] == "🔥 三率三升"]

        strong_growth = strong_growth.sort_values("年增率(YoY%)", ascending=False)

        st.caption(f"共符合 {len(strong_growth)} 筆（年增率 > {yoy_threshold}% 且 月增率 > {mom_threshold}%）")

        def highlight_negative(val):
            color = "red" if isinstance(val, (int, float)) and val < 0 else "black"
            return f"color: {color}"

        styled_df = strong_growth.style.map(highlight_negative, subset=["年增率(YoY%)", "月增率(MoM%)"])

        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "年增率(YoY%)": st.column_config.NumberColumn("年增率(YoY%)", format="%.2f%%"),
                "月增率(MoM%)": st.column_config.NumberColumn("月增率(MoM%)", format="%.2f%%"),
                "累計年增率(%)": st.column_config.NumberColumn("累計年增率(%)", format="%.2f%%"),
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
        st.info("⏳ 資料載入失敗或為空，請重新整理頁面。")

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
with tab8:
    st.write("### 🧮 投資組合分析工具")

    from scipy.optimize import minimize
    import plotly.graph_objects as go
    import plotly.express as px

    sub_tab1, sub_tab2, sub_tab3 = st.tabs(["📈 效率前緣", "🔗 相關性矩陣", "📊 營收成長迴歸"])

    # ============================================================
    # 共用：抓取歷史股價
    # ============================================================
    @st.cache_data(ttl=3600)
    def fetch_price_data(tickers, period="2y"):
        """抓取多檔股票的歷史收盤價，回傳 DataFrame（欄位為 ticker）"""
        data = yf.download(tickers, period=period, auto_adjust=True)["Close"]
        if isinstance(data, pd.Series):  # 只有一檔股票時會回傳 Series
            data = data.to_frame(name=tickers[0])
        data = data.dropna(how="all").ffill().dropna()
        return data

    # ============================================================
    # 分頁1：效率前緣 Efficient Frontier
    # ============================================================
    with sub_tab1:
        st.write("#### 效率前緣計算")
        st.caption("輸入多檔股票代號（以逗號分隔），計算不同權重組合下的風險/報酬，找出最適投資組合")

        tickers_input = st.text_input(
            "股票代號（範例：2330.TW, 2317.TW, 2454.TW）", 
            value="2330.TW, 2317.TW, 2454.TW",
            key="ef_tickers"
        )
        period = st.selectbox("歷史資料期間", ["6mo", "1y", "2y", "5y"], index=2, key="ef_period")
        risk_free_rate = st.number_input("無風險利率 (%)", value=1.5, step=0.1, key="ef_rf") / 100

        if st.button("🚀 計算效率前緣", key="ef_calc_btn"):
            tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]

            if len(tickers) < 2:
                st.error("請至少輸入 2 檔股票")
            else:
                with st.spinner("下載歷史股價中..."):
                    try:
                        prices = fetch_price_data(tickers, period)

                        if prices.empty or len(prices.columns) < 2:
                            st.error("無法取得足夠的股價資料，請確認代號正確")
                        else:
                            # 計算日報酬率
                            returns = prices.pct_change().dropna()

                            # 年化平均報酬與共變異數矩陣
                            mean_returns = returns.mean() * 252
                            cov_matrix = returns.cov() * 252

                            n_assets = len(mean_returns)

                            def portfolio_performance(weights):
                                ret = np.dot(weights, mean_returns)
                                vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
                                return ret, vol

                            def neg_sharpe(weights):
                                ret, vol = portfolio_performance(weights)
                                return -(ret - risk_free_rate) / vol

                            def portfolio_vol(weights):
                                return portfolio_performance(weights)[1]

                            constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
                            bounds = tuple((0, 1) for _ in range(n_assets))
                            init_guess = np.array([1 / n_assets] * n_assets)

                            # 1. 找出最大夏普比率的投資組合
                            opt_sharpe = minimize(neg_sharpe, init_guess, method='SLSQP',
                                                   bounds=bounds, constraints=constraints)
                            best_weights = opt_sharpe.x
                            best_ret, best_vol = portfolio_performance(best_weights)

                            # 2. 找出最小波動率的投資組合
                            opt_minvol = minimize(portfolio_vol, init_guess, method='SLSQP',
                                                   bounds=bounds, constraints=constraints)
                            minvol_weights = opt_minvol.x
                            minvol_ret, minvol_vol = portfolio_performance(minvol_weights)

                            # 3. 模擬效率前緣曲線（掃描目標報酬率）
                            target_returns = np.linspace(mean_returns.min(), mean_returns.max(), 50)
                            frontier_vols = []

                            for target in target_returns:
                                cons = (
                                    {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
                                    {'type': 'eq', 'fun': lambda w, target=target: portfolio_performance(w)[0] - target}
                                )
                                res = minimize(portfolio_vol, init_guess, method='SLSQP',
                                                bounds=bounds, constraints=cons)
                                frontier_vols.append(res.fun if res.success else np.nan)

                            # 4. 隨機模擬點（讓圖更豐富）
                            np.random.seed(42)
                            n_sim = 3000
                            sim_weights = np.random.dirichlet(np.ones(n_assets), n_sim)
                            sim_rets = sim_weights @ mean_returns.values
                            sim_vols = np.sqrt(np.einsum('ij,jk,ik->i', sim_weights, cov_matrix.values, sim_weights))
                            sim_sharpe = (sim_rets - risk_free_rate) / sim_vols

                            # 繪圖
                            fig = go.Figure()

                            fig.add_trace(go.Scatter(
                                x=sim_vols, y=sim_rets, mode='markers',
                                marker=dict(size=4, color=sim_sharpe, colorscale='Viridis',
                                            showscale=True, colorbar=dict(title="夏普比率")),
                                name="隨機模擬組合", opacity=0.5
                            ))

                            fig.add_trace(go.Scatter(
                                x=frontier_vols, y=target_returns, mode='lines',
                                line=dict(color='red', width=3), name="效率前緣"
                            ))

                            fig.add_trace(go.Scatter(
                                x=[best_vol], y=[best_ret], mode='markers',
                                marker=dict(size=15, color='gold', symbol='star'),
                                name="最大夏普比率組合"
                            ))

                            fig.add_trace(go.Scatter(
                                x=[minvol_vol], y=[minvol_ret], mode='markers',
                                marker=dict(size=15, color='blue', symbol='diamond'),
                                name="最小風險組合"
                            ))

                            fig.update_layout(
                                title="效率前緣 (Efficient Frontier)",
                                xaxis_title="年化波動率（風險）",
                                yaxis_title="年化預期報酬率",
                                height=550
                            )
                            st.plotly_chart(fig, use_container_width=True)

                            # 顯示最適權重
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write("##### ⭐ 最大夏普比率組合")
                                st.write(f"預期年報酬: **{best_ret*100:.2f}%**")
                                st.write(f"年化波動率: **{best_vol*100:.2f}%**")
                                st.write(f"夏普比率: **{(best_ret-risk_free_rate)/best_vol:.3f}**")
                                weight_df = pd.DataFrame({'股票': tickers, '權重': (best_weights*100).round(2)})
                                st.dataframe(weight_df, hide_index=True, use_container_width=True)

                            with col2:
                                st.write("##### 🛡️ 最小風險組合")
                                st.write(f"預期年報酬: **{minvol_ret*100:.2f}%**")
                                st.write(f"年化波動率: **{minvol_vol*100:.2f}%**")
                                weight_df2 = pd.DataFrame({'股票': tickers, '權重': (minvol_weights*100).round(2)})
                                st.dataframe(weight_df2, hide_index=True, use_container_width=True)

                    except Exception as e:
                        st.error(f"計算失敗：{e}")

    # ============================================================
    # 分頁2：相關性矩陣
    # ============================================================
    with sub_tab2:
        st.write("#### 多股票相關性矩陣")
        st.caption("觀察股票之間的價格連動程度，有助於分散投資風險")

        corr_tickers_input = st.text_input(
            "股票代號（以逗號分隔）", 
            value="2330.TW, 2317.TW, 2454.TW, 2412.TW, 3008.TW",
            key="corr_tickers"
        )
        corr_period = st.selectbox("歷史資料期間", ["6mo", "1y", "2y", "5y"], index=1, key="corr_period")

        if st.button("🔍 計算相關性", key="corr_calc_btn"):
            tickers = [t.strip().upper() for t in corr_tickers_input.split(",") if t.strip()]

            if len(tickers) < 2:
                st.error("請至少輸入 2 檔股票")
            else:
                with st.spinner("下載歷史股價中..."):
                    try:
                        prices = fetch_price_data(tickers, corr_period)

                        if prices.empty:
                            st.error("無法取得股價資料")
                        else:
                            returns = prices.pct_change().dropna()
                            corr_matrix = returns.corr()

                            fig = px.imshow(
                                corr_matrix,
                                text_auto=".2f",
                                color_continuous_scale="RdBu_r",
                                zmin=-1, zmax=1,
                                aspect="auto",
                                title="股票報酬率相關性矩陣"
                            )
                            fig.update_layout(height=500)
                            st.plotly_chart(fig, use_container_width=True)

                            # 找出最高/最低相關的配對
                            corr_pairs = corr_matrix.where(
                                np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
                            ).stack().sort_values(ascending=False)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.write("##### 🔺 相關性最高的配對")
                                st.dataframe(
                                    corr_pairs.head(3).reset_index().rename(
                                        columns={'level_0': '股票A', 'level_1': '股票B', 0: '相關係數'}
                                    ),
                                    hide_index=True
                                )
                            with col2:
                                st.write("##### 🔻 相關性最低的配對（分散風險佳）")
                                st.dataframe(
                                    corr_pairs.tail(3).reset_index().rename(
                                        columns={'level_0': '股票A', 'level_1': '股票B', 0: '相關係數'}
                                    ),
                                    hide_index=True
                                )

                    except Exception as e:
                        st.error(f"計算失敗：{e}")

    # ============================================================
    # 分頁3：營收成長趨勢迴歸
    # ============================================================
    with sub_tab3:
        st.write("#### 營收成長趨勢預測")
        st.caption("用歷史季度營收資料，透過線性迴歸預測未來成長趨勢")

        reg_ticker = st.text_input("股票代號（單一）", value="2330.TW", key="reg_ticker")
        forecast_periods = st.slider("預測未來幾季", 1, 8, 4, key="reg_periods")

        if st.button("📐 執行迴歸分析", key="reg_calc_btn"):
            with st.spinner("下載財報資料中..."):
                try:
                    stock = yf.Ticker(reg_ticker)
                    quarterly_rev = stock.quarterly_financials.loc["Total Revenue"].sort_index()

                    if quarterly_rev.empty or len(quarterly_rev) < 4:
                        st.error("歷史季度營收資料不足（需至少4季），無法進行迴歸")
                    else:
                        df_rev = quarterly_rev.reset_index()
                        df_rev.columns = ["季度", "營收"]
                        df_rev["期數"] = range(len(df_rev))

                        # 對營收取 log，讓成長率呈線性關係（複合成長模型）
                        df_rev["log營收"] = np.log(df_rev["營收"])

                        # 線性迴歸: log(revenue) = a + b * period
                        X = df_rev["期數"].values
                        y = df_rev["log營收"].values
                        b, a = np.polyfit(X, y, 1)  # slope, intercept

                        # 換算成每季成長率
                        quarterly_growth_rate = (np.exp(b) - 1) * 100

                        # 預測未來
                        future_periods = np.arange(len(df_rev), len(df_rev) + forecast_periods)
                        future_log_rev = a + b * future_periods
                        future_rev = np.exp(future_log_rev)

                        # 繪圖
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=df_rev["季度"].astype(str), y=df_rev["營收"],
                            mode='lines+markers', name="歷史營收", line=dict(color='blue')
                        ))

                        future_labels = [f"預測+{i+1}" for i in range(forecast_periods)]
                        fig.add_trace(go.Scatter(
                            x=future_labels, y=future_rev,
                            mode='lines+markers', name="預測營收",
                            line=dict(color='red', dash='dash')
                        ))

                        fig.update_layout(
                            title=f"{reg_ticker} 季度營收趨勢與預測",
                            xaxis_title="季度", yaxis_title="營收",
                            height=500
                        )
                        st.plotly_chart(fig, use_container_width=True)

                        st.success(f"估計每季複合成長率：**{quarterly_growth_rate:.2f}%**")

                        pred_df = pd.DataFrame({
                            "期別": future_labels,
                            "預測營收": [f"{v:,.0f}" for v in future_rev]
                        })
                        st.dataframe(pred_df, hide_index=True, use_container_width=True)

                        st.caption("⚠️ 此為簡易線性迴歸模型（假設固定複合成長率），實際營收受景氣循環、產業因素影響，僅供參考。")

                except Exception as e:
                    st.error(f"分析失敗：{e}（可能是該股票沒有足夠的季度財報資料）")


# ============================================================
# TAB 9：三大法人買賣超
# 高速批次版
# ============================================================

def _to_roc_date(date: datetime.date) -> str:
    """西元日期轉民國日期，例如 2026/09/23 → 115/09/23"""
    y = date.year - 1911
    return f"{y}/{date.month:02d}/{date.day:02d}"


def _get_last_trading_date_guess() -> datetime.date:
    """預設日期：週一～週五今天，週六回到週五，週日回到週五"""
    today = datetime.date.today()
    weekday = today.isoweekday()

    if weekday == 6:
        return today - datetime.timedelta(days=1)

    if weekday == 7:
        return today - datetime.timedelta(days=2)

    return today


def _clean_num(v) -> int:
    """將含逗號的數字轉成 int"""
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0


# ============================================================
# TWSE 上市
# ============================================================

def _fetch_twse(yyyymmdd: str) -> list:
    """
    取得 TWSE 三大法人買賣超
    """
    url = (
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={yyyymmdd}&selectType=ALL&response=json"
    )

    try:
        res = requests.get(url, timeout=15)

        if res.status_code != 200:
            return []

        data = res.json()

        if data.get("stat") != "OK" or not data.get("data"):
            return []

    except Exception:
        return []

    rows = []

    for row in data["data"]:

        rows.append([
            "上市",
            row[0],
            row[1],

            # 外資
            _clean_num(row[4]) + _clean_num(row[7]),

            # 投信
            _clean_num(row[10]),

            # 自營商
            _clean_num(row[11]),

            # 三大法人合計
            _clean_num(row[18]),
        ])

    return rows


# ============================================================
# TPEX 上櫃
# ============================================================

def _fetch_tpex(roc_date: str) -> list:
    """
    取得 TPEX 三大法人買賣超
    """

    url = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        "3itrade_hedge_result.php"
        f"?l=zh-tw&o=json&se=EW&t=D&d={roc_date}&s=0,asc"
    )

    headers = {
        "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
    }

    try:
        res = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        if res.status_code != 200:
            return []

        data = res.json()

    except Exception:
        return []

    raw_rows = (
        data.get("aaData")
        or (
            data.get("tables", [{}])[0].get("data")
            if data.get("tables")
            else []
        )
        or []
    )

    if not raw_rows:
        return []

    rows = []

    for row in raw_rows:

        rows.append([
            "上櫃",
            row[0],
            row[1],

            # 外資
            _clean_num(row[4]) + _clean_num(row[7]),

            # 投信
            _clean_num(row[13]),

            # 自營商
            _clean_num(row[22]),

            # 三大法人合計
            _clean_num(row[23]),
        ])

    return rows


# ============================================================
# Yahoo Finance 批次抓指定日期 Close
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _get_yfinance_prices(
    tickers: tuple,
    date: datetime.date
) -> dict:
    """
    一次批次取得所有股票指定日期的 Yahoo Finance Close。

    上市：
        2330.TW

    上櫃：
        6488.TWO

    不做 .TW / .TWO fallback。
    """

    if not tickers:
        return {}

    try:

        start_date = date
        end_date = date + datetime.timedelta(days=1)

        data = yf.download(
            tickers=list(tickers),
            start=start_date,
            end=end_date,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="column"
        )

        if data.empty:
            return {}

        prices = {}

        # ====================================================
        # 多檔股票
        # ====================================================

        if isinstance(data.columns, pd.MultiIndex):

            level0 = data.columns.get_level_values(0)

            if "Close" not in level0:
                return {}

            close_df = data["Close"]

            for ticker in tickers:

                try:

                    if ticker not in close_df.columns:
                        continue

                    series = close_df[ticker].dropna()

                    if not series.empty:
                        prices[ticker] = float(series.iloc[-1])

                except Exception:
                    continue

        # ====================================================
        # 單檔股票
        # ====================================================

        else:

            if "Close" in data.columns:

                series = data["Close"].dropna()

                if not series.empty:
                    prices[tickers[0]] = float(series.iloc[-1])

        return prices

    except Exception:
        return {}


# ============================================================
# TAB 9 主資料
# ============================================================

@st.cache_data(ttl=600, show_spinner=False)
def _load_data_tab9(date: datetime.date) -> pd.DataFrame:

    yyyymmdd = date.strftime("%Y%m%d")
    roc_date = _to_roc_date(date)

    # ========================================================
    # 抓上市 / 上櫃
    # ========================================================

    twse_rows = _fetch_twse(yyyymmdd)
    tpex_rows = _fetch_tpex(roc_date)

    columns = [
        "市場",
        "代號",
        "名稱",
        "外資買賣超(股)",
        "投信買賣超(股)",
        "自營商買賣超(股)",
        "三大法人合計(股)"
    ]

    df = pd.DataFrame(
        twse_rows + tpex_rows,
        columns=columns
    )

    if df.empty:
        return df

    # ========================================================
    # 排除權證
    # 名稱包含「購」或「售」直接排除
    # ========================================================

    df = df[
        ~df["名稱"]
        .astype(str)
        .str.contains("購|售", na=False)
    ].copy()

    if df.empty:
        return df

    # ========================================================
    # 建立 ticker
    #
    # 上市 → .TW
    # 上櫃 → .TWO
    #
    # 不做 fallback
    # ========================================================

    ticker_map = {}

    for _, row in df.iterrows():

        market = str(row["市場"]).strip()
        code = str(row["代號"]).strip()

        if market == "上市":
            ticker = f"{code}.TW"

        elif market == "上櫃":
            ticker = f"{code}.TWO"

        else:
            continue

        ticker_map[(market, code)] = ticker

    # ========================================================
    # 一次取得所有 Yahoo Finance Close
    # ========================================================

    tickers = tuple(
        sorted(set(ticker_map.values()))
    )

    prices = _get_yfinance_prices(
        tickers,
        date
    )

    # ========================================================
    # 將 Close 回填到 DataFrame
    # ========================================================

    df["收盤價"] = [
        prices.get(
            ticker_map.get(
                (
                    str(row["市場"]).strip(),
                    str(row["代號"]).strip()
                )
            )
        )
        for _, row in df.iterrows()
    ]

    # ========================================================
    # 三大法人買超金額
    #
    # 股數 × 當日 Close ÷ 1億
    #
    # 正數 = 買超
    # 負數 = 賣超
    # ========================================================

    df["買超金額(億)"] = (
        df["三大法人合計(股)"]
        * df["收盤價"]
        / 100_000_000
    ).round(2)

    # ========================================================
    # 不顯示收盤價欄位
    # ========================================================

    df = df.drop(
        columns=["收盤價"]
    )

    return df


# ============================================================
# TAB 9 UI
# ============================================================

with tab9:

    st.subheader("三大法人買賣超")

    # ========================================================
    # 日期
    # ========================================================

    default_date = _get_last_trading_date_guess()

    col1, col2 = st.columns([1, 3])

    with col1:

        tab9_date = st.date_input(
            "查詢日期",
            value=default_date,
            key="tab9_date"
        )

    with col2:

        st.write("")
        st.write("")

        tab9_refresh = st.button(
            "重新抓取",
            key="tab9_refresh"
        )

    # ========================================================
    # 重新抓取
    # ========================================================

    if tab9_refresh:

        _load_data_tab9.clear()
        _get_yfinance_prices.clear()

    # ========================================================
    # 抓取資料
    # ========================================================

    with st.spinner("抓取三大法人資料中..."):

        df_tab9 = _load_data_tab9(
            tab9_date
        )

    # ========================================================
    # 無資料
    # ========================================================

    if df_tab9.empty:

        st.warning(
            "查無資料，請確認日期是否為交易日，或稍後再試。"
        )

    else:

        st.caption(
            f"共 {len(df_tab9)} 筆 | "
            f"資料來源：TWSE / TPEX / Yahoo Finance"
        )

        # ====================================================
        # 市場篩選
        # ====================================================

        market_filter = st.multiselect(
            "市場別",
            options=sorted(
                df_tab9["市場"].unique()
            ),
            default=sorted(
                df_tab9["市場"].unique()
            ),
            key="tab9_market"
        )

        # ====================================================
        # 關鍵字
        # ====================================================

        keyword = st.text_input(
            "搜尋代號或名稱",
            key="tab9_search"
        )

        # ====================================================
        # 篩選
        # ====================================================

        view = df_tab9[
            df_tab9["市場"].isin(
                market_filter
            )
        ]

        if keyword:

            view = view[
                view["代號"]
                .astype(str)
                .str.contains(
                    keyword,
                    case=False,
                    na=False
                )
                |
                view["名稱"]
                .astype(str)
                .str.contains(
                    keyword,
                    case=False,
                    na=False
                )
            ]

        # ====================================================
        # 顯示
        # ====================================================

        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={

                "買超金額(億)": st.column_config.NumberColumn(
                    "買超金額(億)",
                    format="%.2f"
                ),

                "外資買賣超(股)": st.column_config.NumberColumn(
                    "外資買賣超(股)",
                    format="%d"
                ),

                "投信買賣超(股)": st.column_config.NumberColumn(
                    "投信買賣超(股)",
                    format="%d"
                ),

                "自營商買賣超(股)": st.column_config.NumberColumn(
                    "自營商買賣超(股)",
                    format="%d"
                ),

                "三大法人合計(股)": st.column_config.NumberColumn(
                    "三大法人合計(股)",
                    format="%d"
                ),
            }
        )

        # ====================================================
        # CSV
        # ====================================================

        csv_tab9 = view.to_csv(
            index=False
        ).encode("utf-8-sig")

        st.download_button(
            "下載 CSV",
            data=csv_tab9,
            file_name=(
                f"三大法人_"
                f"{tab9_date.strftime('%Y%m%d')}.csv"
            ),
            mime="text/csv",
            key="tab9_download"
        )

# ============================================================
# TAB 10：台股 100 分多因子評分 V2
# ============================================================
# 1. TAB 10 評分權重
# ============================================================

SCORE_WEIGHTS = {

    # --------------------------
    # 獲利能力 25 分
    # --------------------------
    "獲利能力": {
        "ROE": 8,
        "ROA": 5,
        "營業利益率": 6,
        "EPS": 6,
    },

    # --------------------------
    # 成長性 20 分
    # --------------------------
    "成長性": {
        "營收成長": 7,
        "EPS成長": 8,
        "三率三升": 5,
    },

    # --------------------------
    # 評價 15 分
    # 越低越好
    # --------------------------
    "評價": {
        "PE": 7,
        "PB": 4,
        "PEG": 4,
    },

    # --------------------------
    # 技術面 15 分
    # --------------------------
    "技術面": {
        "股價 > MA20": 3,
        "MA20 > MA60": 4,
        "股價 > MA120": 3,
        "MA60 > MA120": 3,
        "20日趨勢": 2,
    },

    # --------------------------
    # 籌碼面 15 分
    # --------------------------
    "籌碼面": {
        "外資": 5,
        "投信": 5,
        "自營商": 2,
        "三大法人": 3,
    },

    # --------------------------
    # 低波風險 10 分
    # 越低越好
    # --------------------------
    "低波風險": {
        "3個月波動率": 3,
        "6個月波動率": 3,
        "1年波動率": 2,
        "最大回撤": 2,
    },
}


# ============================================================
# 2. 工具函式
# ============================================================

def safe_float(value):
    """
    安全轉換數值
    """
    try:
        if value is None:
            return np.nan

        if isinstance(value, str):
            value = (
                value.replace(",", "")
                     .replace("%", "")
                     .replace("％", "")
                     .strip()
            )

        return float(value)

    except Exception:
        return np.nan


def clean_stock_name(ticker):
    """
    從 my_stocks 取得股票名稱
    """
    try:
        if ticker in my_stocks:
            return my_stocks[ticker]

        code = ticker.split(".")[0]

        for k, v in my_stocks.items():
            if k.split(".")[0] == code:
                return v

    except Exception:
        pass

    return ticker


def get_base_ticker(ticker):
    """
    取得股票代號
    2330.TW → 2330
    """
    return str(ticker).split(".")[0]


# ============================================================
# 3. Yahoo 股票資料
#
# 重要：
# @st.cache_data 會自動判斷是否已有快取
#
# 有快取：
#   不會重新執行 yf.Ticker()
#   不會重新呼叫 Yahoo
#
# 沒快取：
#   才會真正抓資料
# ============================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def get_score_stock_data(ticker):

    result = {
        "ticker": ticker,
        "name": clean_stock_name(ticker),

        # 基本面
        "roe": np.nan,
        "roa": np.nan,
        "operating_margin": np.nan,
        "eps": np.nan,

        # 成長
        "revenue_growth": np.nan,
        "eps_growth": np.nan,
        "triple_rise": np.nan,

        # 評價
        "pe": np.nan,
        "pb": np.nan,
        "peg": np.nan,

        # 技術
        "price": np.nan,
        "ma20": np.nan,
        "ma60": np.nan,
        "ma120": np.nan,
        "trend20": np.nan,

        # 風險
        "vol_3m": np.nan,
        "vol_6m": np.nan,
        "vol_1y": np.nan,
        "max_drawdown": np.nan,

        # 狀態
        "price_source": "",
        "data_error": "",
    }

    try:

        # ====================================================
        # 先抓 .TW
        # ====================================================

        candidates = []

        if ticker.endswith(".TW"):
            candidates = [ticker, ticker.replace(".TW", ".TWO")]
        elif ticker.endswith(".TWO"):
            candidates = [ticker, ticker.replace(".TWO", ".TW")]
        else:
            candidates = [ticker + ".TW", ticker + ".TWO"]

        info = {}
        hist = pd.DataFrame()
        used_ticker = ""

        for test_ticker in candidates:

            try:

                yt = yf.Ticker(test_ticker)

                # ----------------------------
                # Yahoo 基本資料
                # ----------------------------
                test_info = yt.info

                # ----------------------------
                # Yahoo 歷史價格
                # ----------------------------
                test_hist = yt.history(
                    period="1y",
                    auto_adjust=False
                )

                if (
                    test_hist is not None
                    and not test_hist.empty
                    and len(test_hist) >= 30
                ):
                    info = test_info if isinstance(test_info, dict) else {}
                    hist = test_hist.copy()
                    used_ticker = test_ticker
                    break

            except Exception:
                continue

        if hist.empty:
            result["data_error"] = "Yahoo 無價格資料"
            return result

        result["price_source"] = used_ticker

        # ====================================================
        # 價格整理
        # ====================================================

        if "Close" not in hist.columns:
            result["data_error"] = "沒有 Close"
            return result

        close = pd.to_numeric(
            hist["Close"],
            errors="coerce"
        ).dropna()

        if close.empty:
            result["data_error"] = "Close 無有效資料"
            return result

        # ====================================================
        # 最新股價
        # ====================================================

        result["price"] = float(close.iloc[-1])

        # ====================================================
        # 均線
        # ====================================================

        if len(close) >= 20:
            result["ma20"] = float(
                close.rolling(20).mean().iloc[-1]
            )

        if len(close) >= 60:
            result["ma60"] = float(
                close.rolling(60).mean().iloc[-1]
            )

        if len(close) >= 120:
            result["ma120"] = float(
                close.rolling(120).mean().iloc[-1]
            )

        # ====================================================
        # 20 日趨勢
        #
        # 使用 20 日前價格
        # ====================================================

        if len(close) >= 21:

            price_now = close.iloc[-1]
            price_20 = close.iloc[-21]

            if price_20 != 0:
                result["trend20"] = (
                    price_now / price_20 - 1
                )

        # ====================================================
        # Yahoo 基本面
        # ====================================================

        result["roe"] = safe_float(
            info.get("returnOnEquity")
        )

        result["roa"] = safe_float(
            info.get("returnOnAssets")
        )

        result["operating_margin"] = safe_float(
            info.get("operatingMargins")
        )

        # EPS
        eps_candidates = [
            info.get("trailingEps"),
            info.get("forwardEps"),
        ]

        for x in eps_candidates:
            x = safe_float(x)

            if pd.notna(x):
                result["eps"] = x
                break

        # ====================================================
        # 成長
        # ====================================================

        result["revenue_growth"] = safe_float(
            info.get("revenueGrowth")
        )

        result["eps_growth"] = safe_float(
            info.get("earningsGrowth")
        )

        # ====================================================
        # 評價
        # ====================================================

        result["pe"] = safe_float(
            info.get("trailingPE")
        )

        if pd.isna(result["pe"]):
            result["pe"] = safe_float(
                info.get("forwardPE")
            )

        result["pb"] = safe_float(
            info.get("priceToBook")
        )

        result["peg"] = safe_float(
            info.get("pegRatio")
        )

        # ====================================================
        # 波動率
        #
        # 使用 Close
        # 年化樣本標準差
        # ====================================================

        daily_return = close.pct_change().dropna()

        # 3 個月
        if len(daily_return) >= 30:
            r3 = daily_return.tail(63)

            if len(r3) >= 30:
                result["vol_3m"] = (
                    r3.std(ddof=1) * np.sqrt(252)
                )

        # 6 個月
        if len(daily_return) >= 60:
            r6 = daily_return.tail(126)

            if len(r6) >= 60:
                result["vol_6m"] = (
                    r6.std(ddof=1) * np.sqrt(252)
                )

        # 1 年
        if len(daily_return) >= 126:
            r1 = daily_return.tail(252)

            if len(r1) >= 126:
                result["vol_1y"] = (
                    r1.std(ddof=1) * np.sqrt(252)
                )

        # ====================================================
        # 最大回撤
        # ====================================================

        if len(close) >= 60:

            running_max = close.cummax()

            drawdown = (
                close / running_max - 1
            )

            result["max_drawdown"] = abs(
                float(drawdown.min())
            )

        return result

    except Exception as e:

        result["data_error"] = str(e)

        return result


# ============================================================
# 4. 百分位評分
# ============================================================

def percentile_score(series, higher_is_better=True):

    s = pd.to_numeric(
        series,
        errors="coerce"
    )

    valid = s.notna()

    result = pd.Series(
        np.nan,
        index=series.index
    )

    if valid.sum() == 0:
        return result

    if valid.sum() == 1:
        result.loc[valid] = 1.0
        return result

    ranks = s[valid].rank(
        method="average",
        ascending=not higher_is_better
    )

    result.loc[valid] = (
        ranks - 1
    ) / (
        valid.sum() - 1
    )

    return result


# ============================================================
# 5. 因子評分
#
# 缺資料時：
# 不直接給 0
# 而是將剩餘權重重新分配
# ============================================================

def calculate_factor_score(
    df,
    columns,
    weights,
    higher_map
):

    score = pd.Series(
        0.0,
        index=df.index
    )

    available_weight = pd.Series(
        0.0,
        index=df.index
    )

    for col in columns:

        if col not in df.columns:
            continue

        w = weights.get(col, 0)

        if w <= 0:
            continue

        values = pd.to_numeric(
            df[col],
            errors="coerce"
        )

        valid = values.notna()

        if valid.sum() == 0:
            continue

        p = percentile_score(
            values,
            higher_is_better=higher_map.get(
                col,
                True
            )
        )

        score.loc[valid] += (
            p.loc[valid] * w
        )

        available_weight.loc[valid] += w

    # ========================================================
    # 權重重新放大到該因子滿分
    # ========================================================

    total_weight = sum(
        weights.values()
    )

    final_score = pd.Series(
        np.nan,
        index=df.index
    )

    valid_factor = (
        available_weight > 0
    )

    final_score.loc[valid_factor] = (
        score.loc[valid_factor]
        / available_weight.loc[valid_factor]
        * total_weight
    )

    return final_score


# ============================================================
# 6. TAB 4 營收資料
# ============================================================

def get_revenue_data_from_tab4():

    revenue_data = st.session_state.get(
        "revenue_data",
        None
    )

    if revenue_data is None:
        return pd.DataFrame()

    try:

        if isinstance(
            revenue_data,
            pd.DataFrame
        ):
            return revenue_data.copy()

        return pd.DataFrame(
            revenue_data
        )

    except Exception:
        return pd.DataFrame()


# ============================================================
# 7. 將 TAB 4 營收資料合併到評分資料
# ============================================================

def merge_tab4_revenue(df):

    revenue_df = get_revenue_data_from_tab4()

    if revenue_df.empty:
        return df

    try:

        r = revenue_df.copy()

        # ----------------------------------------------------
        # 找股票代號欄位
        # ----------------------------------------------------

        code_col = None

        possible_code_cols = [
            "代號",
            "股票代號",
            "證券代號",
            "stock_id",
            "code",
            "Code",
        ]

        for c in possible_code_cols:

            if c in r.columns:
                code_col = c
                break

        if code_col is None:
            return df

        # ----------------------------------------------------
        # 找營收年增率
        # ----------------------------------------------------

        yoy_col = None

        possible_yoy_cols = [
            "年增率(YoY%)",
            "營收年增率",
            "營收年增率(%)",
            "YoY",
            "yoy",
        ]

        for c in possible_yoy_cols:

            if c in r.columns:
                yoy_col = c
                break

        if yoy_col is None:
            return df

        # ----------------------------------------------------
        # 找三率三升
        # ----------------------------------------------------

        triple_col = None

        possible_triple_cols = [
            "三率三升",
            "三率三升🔥",
            "三率三升標記",
        ]

        for c in possible_triple_cols:

            if c in r.columns:
                triple_col = c
                break

        # ----------------------------------------------------
        # 整理代號
        # ----------------------------------------------------

        r["_code"] = (
            r[code_col]
            .astype(str)
            .str.extract(r"(\d{4})", expand=False)
        )

        # ----------------------------------------------------
        # 年增率
        # ----------------------------------------------------

        r["_revenue_growth_tab4"] = (
            r[yoy_col]
            .apply(safe_float)
        )

        # ----------------------------------------------------
        # 三率三升
        # ----------------------------------------------------

        if triple_col is not None:

            r["_triple_rise"] = (
                r[triple_col]
                .astype(str)
                .str.contains(
                    "三率三升",
                    na=False
                )
                .astype(float)
            )

        else:

            r["_triple_rise"] = np.nan

        # ----------------------------------------------------
        # 同一股票只保留最後一筆
        # ----------------------------------------------------

        r = (
            r.dropna(subset=["_code"])
             .drop_duplicates(
                 "_code",
                 keep="last"
             )
        )

        # ----------------------------------------------------
        # 主表股票代號
        # ----------------------------------------------------

        df["_code"] = (
            df["ticker"]
            .astype(str)
            .str.extract(
                r"(\d{4})",
                expand=False
            )
        )

        # ----------------------------------------------------
        # Merge
        # ----------------------------------------------------

        df = df.merge(
            r[
                [
                    "_code",
                    "_revenue_growth_tab4",
                    "_triple_rise",
                ]
            ],
            on="_code",
            how="left"
        )

        # ----------------------------------------------------
        # TAB 4 優先
        # ----------------------------------------------------

        df["revenue_growth"] = np.where(
            df["_revenue_growth_tab4"].notna(),
            df["_revenue_growth_tab4"] / 100,
            df["revenue_growth"]
        )

        df["triple_rise"] = np.where(
            df["_triple_rise"].notna(),
            df["_triple_rise"],
            df.get(
                "triple_rise",
                np.nan
            )
        )

        df.drop(
            columns=[
                "_code",
                "_revenue_growth_tab4",
                "_triple_rise",
            ],
            inplace=True,
            errors="ignore"
        )

        return df

    except Exception:
        return df


# ============================================================
# 8. TAB 9 三大法人資料
# ============================================================

def get_institutional_data():

    data = st.session_state.get(
        "institutional_data",
        None
    )

    if data is None:
        return pd.DataFrame()

    try:

        if isinstance(
            data,
            pd.DataFrame
        ):
            return data.copy()

        return pd.DataFrame(data)

    except Exception:
        return pd.DataFrame()


# ============================================================
# 9. 合併 TAB 9 三大法人
# ============================================================

def merge_institutional_data(df):

    inst = get_institutional_data()

    if inst.empty:
        return df

    try:

        i = inst.copy()

        # ----------------------------------------------------
        # 找股票代號
        # ----------------------------------------------------

        code_col = None

        possible_code_cols = [
            "代號",
            "股票代號",
            "證券代號",
            "stock_id",
            "code",
            "Code",
        ]

        for c in possible_code_cols:

            if c in i.columns:
                code_col = c
                break

        if code_col is None:
            return df

        # ----------------------------------------------------
        # 找三大法人欄位
        # ----------------------------------------------------

        mapping = {

            "外資": [
                "外資",
                "外資買賣超",
                "外資買賣超(張)",
                "Foreign",
            ],

            "投信": [
                "投信",
                "投信買賣超",
                "投信買賣超(張)",
                "Investment Trust",
            ],

            "自營商": [
                "自營商",
                "自營商買賣超",
                "自營商買賣超(張)",
                "Dealer",
            ],

            "三大法人": [
                "三大法人",
                "三大法人買賣超",
                "三大法人買賣超(張)",
                "Total",
            ],
        }

        selected = {}

        for target, candidates in mapping.items():

            for c in candidates:

                if c in i.columns:

                    selected[target] = c
                    break

        if not selected:
            return df

        # ----------------------------------------------------
        # 股票代號
        # ----------------------------------------------------

        i["_code"] = (
            i[code_col]
            .astype(str)
            .str.extract(
                r"(\d{4})",
                expand=False
            )
        )

        # ----------------------------------------------------
        # 建立新欄位
        # ----------------------------------------------------

        for target, source in selected.items():

            i[
                f"_inst_{target}"
            ] = i[source].apply(
                safe_float
            )

        # ----------------------------------------------------
        # 只保留需要資料
        # ----------------------------------------------------

        keep_cols = [
            "_code"
        ]

        for target in selected:
            keep_cols.append(
                f"_inst_{target}"
            )

        i = (
            i.dropna(subset=["_code"])
             .drop_duplicates(
                 "_code",
                 keep="last"
             )
        )

        # ----------------------------------------------------
        # 主表代號
        # ----------------------------------------------------

        df["_code"] = (
            df["ticker"]
            .astype(str)
            .str.extract(
                r"(\d{4})",
                expand=False
            )
        )

        # ----------------------------------------------------
        # Merge
        # ----------------------------------------------------

        df = df.merge(
            i[keep_cols],
            on="_code",
            how="left"
        )

        # ----------------------------------------------------
        # 寫入
        # ----------------------------------------------------

        for target in selected:

            df[
                f"inst_{target}"
            ] = df[
                f"_inst_{target}"
            ]

        df.drop(
            columns=[
                "_code"
            ] + [
                f"_inst_{x}"
                for x in selected
            ],
            inplace=True,
            errors="ignore"
        )

        return df

    except Exception:
        return df


# ============================================================
# 10. TAB 10 主程式
# ============================================================

st.markdown(
    """
    <h2>📊 TAB 10：台股 100 分多因子評分 V2</h2>
    """,
    unsafe_allow_html=True
)

st.caption(
    "獲利 25｜成長 20｜評價 15｜技術 15｜籌碼 15｜低波風險 10"
)


# ============================================================
# 11. 快取控制
# ============================================================

col_refresh1, col_refresh2 = st.columns(
    [1, 5]
)

with col_refresh1:

    force_refresh = st.button(
        "🔄 強制更新",
        key="tab10_force_refresh"
    )

if force_refresh:

    # --------------------------------------------------------
    # 只有使用者主動要求時才清除
    # --------------------------------------------------------

    get_score_stock_data.clear()

    st.toast(
        "TAB 10 Yahoo 快取已清除，下一次將重新抓取資料",
        icon="🔄"
    )

    st.rerun()


# ============================================================
# 12. 股票池
# ============================================================

try:

    stock_items = list(
        my_stocks.items()
    )

except Exception:

    stock_items = []


if not stock_items:

    st.warning(
        "找不到 my_stocks 股票清單，請先確認 TAB 1 的股票清單。"
    )

    st.stop()


# ============================================================
# 13. 抓取股票資料
#
# 這裡看起來會呼叫函式，
# 但如果有 cache：
#
# Streamlit 直接回傳快取結果
# 不會執行函式內部 Yahoo API
# ============================================================

data_list = []

progress = st.progress(
    0,
    text="載入 TAB 10 評分資料..."
)

total_stocks = len(stock_items)

for idx, (ticker, name) in enumerate(
    stock_items
):

    row = get_score_stock_data(
        ticker
    )

    # 使用 watchlist 名稱
    row["name"] = name

    data_list.append(row)

    progress.progress(
        (idx + 1) / total_stocks,
        text=f"載入 {name} ({idx + 1}/{total_stocks})"
    )

progress.empty()


# ============================================================
# 14. DataFrame
# ============================================================

df = pd.DataFrame(
    data_list
)

if df.empty:

    st.warning(
        "目前沒有可評分的股票資料。"
    )

    st.stop()


# ============================================================
# 15. 合併 TAB 4 營收
# ============================================================

df = merge_tab4_revenue(
    df
)


# ============================================================
# 16. 合併 TAB 9 三大法人
# ============================================================

df = merge_institutional_data(
    df
)


# ============================================================
# 17. 若沒有三大法人欄位
# ============================================================

for c in [
    "inst_外資",
    "inst_投信",
    "inst_自營商",
    "inst_三大法人",
]:

    if c not in df.columns:

        df[c] = np.nan


# ============================================================
# 18. 籌碼面資料整理
# ============================================================

df["foreign"] = df[
    "inst_外資"
]

df["trust"] = df[
    "inst_投信"
]

df["dealer"] = df[
    "inst_自營商"
]

df["institutional_total"] = df[
    "inst_三大法人"
]


# ============================================================
# 19. 三率三升
#
# 如果 TAB 4 沒有資料，就保持 NaN
# ============================================================

if "triple_rise" not in df.columns:

    df["triple_rise"] = np.nan


# ============================================================
# 20. 技術條件
# ============================================================

df["price_ma20"] = np.where(
    df["price"].notna()
    & df["ma20"].notna(),
    (
        df["price"]
        > df["ma20"]
    ).astype(float),
    np.nan
)

df["ma20_ma60"] = np.where(
    df["ma20"].notna()
    & df["ma60"].notna(),
    (
        df["ma20"]
        > df["ma60"]
    ).astype(float),
    np.nan
)

df["price_ma120"] = np.where(
    df["price"].notna()
    & df["ma120"].notna(),
    (
        df["price"]
        > df["ma120"]
    ).astype(float),
    np.nan
)

df["ma60_ma120"] = np.where(
    df["ma60"].notna()
    & df["ma120"].notna(),
    (
        df["ma60"]
        > df["ma120"]
    ).astype(float),
    np.nan
)


# ============================================================
# 21. 獲利能力評分
# ============================================================

profit_weights = SCORE_WEIGHTS[
    "獲利能力"
]

df["score_profit"] = calculate_factor_score(

    df,

    [
        "roe",
        "roa",
        "operating_margin",
        "eps",
    ],

    profit_weights,

    {
        "roe": True,
        "roa": True,
        "operating_margin": True,
        "eps": True,
    }
)


# ============================================================
# 22. 成長性評分
# ============================================================

growth_weights = SCORE_WEIGHTS[
    "成長性"
]

df["score_growth"] = calculate_factor_score(

    df,

    [
        "revenue_growth",
        "eps_growth",
        "triple_rise",
    ],

    growth_weights,

    {
        "revenue_growth": True,
        "eps_growth": True,
        "triple_rise": True,
    }
)


# ============================================================
# 23. 評價評分
#
# PE / PB / PEG 越低越好
# ============================================================

valuation_weights = SCORE_WEIGHTS[
    "評價"
]

df["score_valuation"] = calculate_factor_score(

    df,

    [
        "pe",
        "pb",
        "peg",
    ],

    valuation_weights,

    {
        "pe": False,
        "pb": False,
        "peg": False,
    }
)


# ============================================================
# 24. 技術面評分
# ============================================================

technical_weights = SCORE_WEIGHTS[
    "技術面"
]

df["score_technical"] = calculate_factor_score(

    df,

    [
        "price_ma20",
        "ma20_ma60",
        "price_ma120",
        "ma60_ma120",
        "trend20",
    ],

    technical_weights,

    {
        "price_ma20": True,
        "ma20_ma60": True,
        "price_ma120": True,
        "ma60_ma120": True,
        "trend20": True,
    }
)


# ============================================================
# 25. 籌碼面評分
# ============================================================

chip_weights = SCORE_WEIGHTS[
    "籌碼面"
]

df["score_chip"] = calculate_factor_score(

    df,

    [
        "foreign",
        "trust",
        "dealer",
        "institutional_total",
    ],

    chip_weights,

    {
        "foreign": True,
        "trust": True,
        "dealer": True,
        "institutional_total": True,
    }
)


# ============================================================
# 26. 低波風險評分
#
# 波動越低越好
# 最大回撤越低越好
# ============================================================

risk_weights = SCORE_WEIGHTS[
    "低波風險"
]

df["score_risk"] = calculate_factor_score(

    df,

    [
        "vol_3m",
        "vol_6m",
        "vol_1y",
        "max_drawdown",
    ],

    risk_weights,

    {
        "vol_3m": False,
        "vol_6m": False,
        "vol_1y": False,
        "max_drawdown": False,
    }
)


# ============================================================
# 27. 總分
# ============================================================

score_columns = [
    "score_profit",
    "score_growth",
    "score_valuation",
    "score_technical",
    "score_chip",
    "score_risk",
]

df["total_score"] = (
    df[score_columns]
    .sum(axis=1, skipna=True)
)


# ============================================================
# 28. 資料完整度
#
# 六大因子中：
# 有實際可評分資料的權重 / 該因子總權重
# ============================================================

factor_completeness = {}

for factor_name, weights in SCORE_WEIGHTS.items():

    factor_score_col = {
        "獲利能力": "score_profit",
        "成長性": "score_growth",
        "評價": "score_valuation",
        "技術面": "score_technical",
        "籌碼面": "score_chip",
        "低波風險": "score_risk",
    }[factor_name]

    # --------------------------------------------------------
    # 每個子因子資料是否存在
    # --------------------------------------------------------

    if factor_name == "獲利能力":

        cols = [
            "roe",
            "roa",
            "operating_margin",
            "eps",
        ]

    elif factor_name == "成長性":

        cols = [
            "revenue_growth",
            "eps_growth",
            "triple_rise",
        ]

    elif factor_name == "評價":

        cols = [
            "pe",
            "pb",
            "peg",
        ]

    elif factor_name == "技術面":

        cols = [
            "price_ma20",
            "ma20_ma60",
            "price_ma120",
            "ma60_ma120",
            "trend20",
        ]

    elif factor_name == "籌碼面":

        cols = [
            "foreign",
            "trust",
            "dealer",
            "institutional_total",
        ]

    else:

        cols = [
            "vol_3m",
            "vol_6m",
            "vol_1y",
            "max_drawdown",
        ]

    available_weight = pd.Series(
        0.0,
        index=df.index
    )

    total_factor_weight = sum(
        weights.values()
    )

    for c in cols:

        if c not in df.columns:
            continue

        valid = df[c].notna()

        available_weight.loc[valid] += (
            weights.get(c, 0)
        )

    df[
        f"完整度_{factor_name}"
    ] = (
        available_weight
        / total_factor_weight
    )

    factor_completeness[
        factor_name
    ] = f"完整度_{factor_name}"


# ============================================================
# 29. 總資料完整度
# ============================================================

total_weight = sum(
    sum(x.values())
    for x in SCORE_WEIGHTS.values()
)

weighted_available = pd.Series(
    0.0,
    index=df.index
)

for factor_name, weights in SCORE_WEIGHTS.items():

    c = factor_completeness[
        factor_name
    ]

    factor_total = sum(
        weights.values()
    )

    weighted_available += (
        df[c] * factor_total
    )

df["資料完整度"] = (
    weighted_available
    / total_weight
)


# ============================================================
# 30. 排名
#
# 先總分
# 再資料完整度
# ============================================================

df = df.sort_values(
    [
        "total_score",
        "資料完整度",
    ],
    ascending=[
        False,
        False,
    ]
).reset_index(
    drop=True
)

df["排名"] = (
    df.index + 1
)


# ============================================================
# 31. 顯示用名稱
# ============================================================

df["股票"] = (
    df["ticker"]
    .astype(str)
    .str.replace(
        ".TW",
        "",
        regex=False
    )
    .str.replace(
        ".TWO",
        "",
        regex=False
    )
    + " "
    + df["name"].astype(str)
)


# ============================================================
# 32. KPI
# ============================================================

st.markdown("### 📌 評分總覽")

k1, k2, k3, k4 = st.columns(4)

with k1:

    st.metric(
        "股票數",
        len(df)
    )

with k2:

    st.metric(
        "平均分數",
        f"{df['total_score'].mean():.1f}"
    )

with k3:

    if len(df) > 0:

        st.metric(
            "最高分",
            f"{df['total_score'].max():.1f}"
        )

with k4:

    st.metric(
        "平均資料完整度",
        f"{df['資料完整度'].mean() * 100:.1f}%"
    )


# ============================================================
# 33. 排名表
# ============================================================

st.markdown("### 🏆 多因子股票排名")

display_df = df[
    [
        "排名",
        "股票",
        "total_score",
        "score_profit",
        "score_growth",
        "score_valuation",
        "score_technical",
        "score_chip",
        "score_risk",
        "資料完整度",
    ]
].copy()

display_df.columns = [
    "排名",
    "股票",
    "總分",
    "獲利",
    "成長",
    "評價",
    "技術",
    "籌碼",
    "低波",
    "資料完整度",
]

display_df["總分"] = (
    display_df["總分"]
    .round(1)
)

for c in [
    "獲利",
    "成長",
    "評價",
    "技術",
    "籌碼",
    "低波",
]:

    display_df[c] = (
        display_df[c]
        .round(1)
    )

display_df["資料完整度"] = (
    display_df["資料完整度"]
    .apply(
        lambda x:
        f"{x * 100:.0f}%"
        if pd.notna(x)
        else "-"
    )
)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "排名": st.column_config.NumberColumn(
            "排名",
            format="%d"
        ),
        "總分": st.column_config.NumberColumn(
            "總分",
            format="%.1f"
        ),
        "獲利": st.column_config.NumberColumn(
            "獲利",
            format="%.1f"
        ),
        "成長": st.column_config.NumberColumn(
            "成長",
            format="%.1f"
        ),
        "評價": st.column_config.NumberColumn(
            "評價",
            format="%.1f"
        ),
        "技術": st.column_config.NumberColumn(
            "技術",
            format="%.1f"
        ),
        "籌碼": st.column_config.NumberColumn(
            "籌碼",
            format="%.1f"
        ),
        "低波": st.column_config.NumberColumn(
            "低波",
            format="%.1f"
        ),
    }
)


# ============================================================
# 34. 選擇股票
# ============================================================

st.markdown("### 🔍 個股評分明細")

selected_ticker = st.selectbox(
    "選擇股票",
    df["ticker"].tolist(),
    format_func=lambda x:
        f"{get_base_ticker(x)}  {clean_stock_name(x)}"
)


selected_row = df[
    df["ticker"] == selected_ticker
].iloc[0]


# ============================================================
# 35. 個股總分
# ============================================================

m1, m2, m3, m4 = st.columns(4)

with m1:

    st.metric(
        "總分",
        f"{selected_row['total_score']:.1f} / 100"
    )

with m2:

    st.metric(
        "排名",
        f"{int(selected_row['排名'])} / {len(df)}"
    )

with m3:

    st.metric(
        "資料完整度",
        f"{selected_row['資料完整度'] * 100:.0f}%"
    )

with m4:

    if pd.notna(
        selected_row["price"]
    ):

        st.metric(
            "最新價格",
            f"{selected_row['price']:.2f}"
        )

    else:

        st.metric(
            "最新價格",
            "-"
        )


# ============================================================
# 36. 六大因子圖
# ============================================================

factor_display = pd.DataFrame({

    "因子": [
        "獲利能力",
        "成長性",
        "評價",
        "技術面",
        "籌碼面",
        "低波風險",
    ],

    "得分": [
        selected_row["score_profit"],
        selected_row["score_growth"],
        selected_row["score_valuation"],
        selected_row["score_technical"],
        selected_row["score_chip"],
        selected_row["score_risk"],
    ],

    "滿分": [
        25,
        20,
        15,
        15,
        15,
        10,
    ],
})


fig = go.Figure()

fig.add_trace(
    go.Bar(
        x=factor_display["因子"],
        y=factor_display["得分"],
        text=[
            f"{x:.1f}"
            if pd.notna(x)
            else "-"
            for x in factor_display["得分"]
        ],
        textposition="outside",
    )
)

fig.update_layout(
    title="六大因子評分",
    yaxis_title="分數",
    xaxis_title="",
    yaxis_range=[
        0,
        27
    ],
    height=400,
)

st.plotly_chart(
    fig,
    use_container_width=True
)


# ============================================================
# 37. 各因子完整度
# ============================================================

st.markdown("#### 📋 各因子資料完整度")

complete_cols = [
    "完整度_獲利能力",
    "完整度_成長性",
    "完整度_評價",
    "完整度_技術面",
    "完整度_籌碼面",
    "完整度_低波風險",
]

complete_names = [
    "獲利能力",
    "成長性",
    "評價",
    "技術面",
    "籌碼面",
    "低波風險",
]

for c, name in zip(
    complete_cols,
    complete_names
):

    value = selected_row[c]

    if pd.notna(value):

        st.write(
            f"{name}：{value * 100:.0f}%"
        )

        st.progress(
            float(value)
        )


# ============================================================
# 38. 基本面
# ============================================================

st.markdown("### 💰 獲利能力")

b1, b2, b3, b4 = st.columns(4)

with b1:

    value = selected_row["roe"]

    st.metric(
        "ROE",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with b2:

    value = selected_row["roa"]

    st.metric(
        "ROA",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with b3:

    value = selected_row[
        "operating_margin"
    ]

    st.metric(
        "營業利益率",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with b4:

    value = selected_row["eps"]

    st.metric(
        "EPS",
        f"{value:.2f}"
        if pd.notna(value)
        else "-"
    )


# ============================================================
# 39. 成長
# ============================================================

st.markdown("### 📈 成長性")

g1, g2, g3 = st.columns(3)

with g1:

    value = selected_row[
        "revenue_growth"
    ]

    st.metric(
        "營收成長",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with g2:

    value = selected_row[
        "eps_growth"
    ]

    st.metric(
        "EPS 成長",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with g3:

    value = selected_row[
        "triple_rise"
    ]

    if pd.isna(value):

        triple_text = "-"

    elif value >= 1:

        triple_text = "🔥 三率三升"

    else:

        triple_text = "否"

    st.metric(
        "三率三升",
        triple_text
    )


# ============================================================
# 40. 評價
# ============================================================

st.markdown("### 💵 評價")

v1, v2, v3 = st.columns(3)

with v1:

    value = selected_row["pe"]

    st.metric(
        "本益比 PE",
        f"{value:.2f}"
        if pd.notna(value)
        else "-"
    )

with v2:

    value = selected_row["pb"]

    st.metric(
        "股價淨值比 PB",
        f"{value:.2f}"
        if pd.notna(value)
        else "-"
    )

with v3:

    value = selected_row["peg"]

    st.metric(
        "PEG",
        f"{value:.2f}"
        if pd.notna(value)
        else "-"
    )


# ============================================================
# 41. 技術面
# ============================================================

st.markdown("### 📊 技術面")

t1, t2, t3, t4 = st.columns(4)

with t1:

    st.metric(
        "股價",
        f"{selected_row['price']:.2f}"
        if pd.notna(
            selected_row["price"]
        )
        else "-"
    )

with t2:

    st.metric(
        "MA20",
        f"{selected_row['ma20']:.2f}"
        if pd.notna(
            selected_row["ma20"]
        )
        else "-"
    )

with t3:

    st.metric(
        "MA60",
        f"{selected_row['ma60']:.2f}"
        if pd.notna(
            selected_row["ma60"]
        )
        else "-"
    )

with t4:

    st.metric(
        "MA120",
        f"{selected_row['ma120']:.2f}"
        if pd.notna(
            selected_row["ma120"]
        )
        else "-"
    )


t5, t6, t7 = st.columns(3)

with t5:

    value = selected_row[
        "price_ma20"
    ]

    st.metric(
        "股價 > MA20",
        "✅" if value == 1 else "❌"
        if pd.notna(value)
        else "-"
    )

with t6:

    value = selected_row[
        "ma20_ma60"
    ]

    st.metric(
        "MA20 > MA60",
        "✅" if value == 1 else "❌"
        if pd.notna(value)
        else "-"
    )

with t7:

    value = selected_row[
        "trend20"
    ]

    st.metric(
        "20日趨勢",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )


# ============================================================
# 42. 籌碼面
# ============================================================

st.markdown("### 🏦 三大法人")

c1, c2, c3, c4 = st.columns(4)

with c1:

    value = selected_row[
        "foreign"
    ]

    st.metric(
        "外資",
        f"{value:,.0f}"
        if pd.notna(value)
        else "-"
    )

with c2:

    value = selected_row[
        "trust"
    ]

    st.metric(
        "投信",
        f"{value:,.0f}"
        if pd.notna(value)
        else "-"
    )

with c3:

    value = selected_row[
        "dealer"
    ]

    st.metric(
        "自營商",
        f"{value:,.0f}"
        if pd.notna(value)
        else "-"
    )

with c4:

    value = selected_row[
        "institutional_total"
    ]

    st.metric(
        "三大法人",
        f"{value:,.0f}"
        if pd.notna(value)
        else "-"
    )


inst_date = st.session_state.get(
    "institutional_data_date",
    None
)

if inst_date:

    st.caption(
        f"TAB 9 三大法人資料日期：{inst_date}"
    )


# ============================================================
# 43. 低波風險
# ============================================================

st.markdown("### 🛡️ 低波風險")

r1, r2, r3, r4 = st.columns(4)

with r1:

    value = selected_row[
        "vol_3m"
    ]

    st.metric(
        "3個月波動率",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with r2:

    value = selected_row[
        "vol_6m"
    ]

    st.metric(
        "6個月波動率",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with r3:

    value = selected_row[
        "vol_1y"
    ]

    st.metric(
        "1年波動率",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )

with r4:

    value = selected_row[
        "max_drawdown"
    ]

    st.metric(
        "最大回撤",
        f"{value * 100:.2f}%"
        if pd.notna(value)
        else "-"
    )


# ============================================================
# 44. 資料來源
# ============================================================

st.markdown("### 🔗 資料來源")

source = selected_row[
    "price_source"
]

if source:

    st.write(
        f"Yahoo Finance：`{source}`"
    )

else:

    st.write(
        "Yahoo Finance：無資料"
    )


# ============================================================
# 45. 原始資料表
# ============================================================

with st.expander(
    "🔎 查看原始評分資料"
):

    raw_cols = [

        "ticker",
        "name",

        "roe",
        "roa",
        "operating_margin",
        "eps",

        "revenue_growth",
        "eps_growth",
        "triple_rise",

        "pe",
        "pb",
        "peg",

        "price",
        "ma20",
        "ma60",
        "ma120",
        "trend20",

        "foreign",
        "trust",
        "dealer",
        "institutional_total",

        "vol_3m",
        "vol_6m",
        "vol_1y",
        "max_drawdown",

        "score_profit",
        "score_growth",
        "score_valuation",
        "score_technical",
        "score_chip",
        "score_risk",

        "total_score",
        "資料完整度",
    ]

    raw_cols = [
        c for c in raw_cols
        if c in df.columns
    ]

    raw_df = df[raw_cols].copy()

    st.dataframe(
        raw_df,
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# 46. CSV 匯出
# ============================================================

st.markdown("### 📥 匯出")

csv_df = df.copy()

csv_df = csv_df[
    [
        "排名",
        "ticker",
        "name",

        "total_score",

        "score_profit",
        "score_growth",
        "score_valuation",
        "score_technical",
        "score_chip",
        "score_risk",

        "資料完整度",

        "roe",
        "roa",
        "operating_margin",
        "eps",

        "revenue_growth",
        "eps_growth",
        "triple_rise",

        "pe",
        "pb",
        "peg",

        "price",
        "ma20",
        "ma60",
        "ma120",
        "trend20",

        "foreign",
        "trust",
        "dealer",
        "institutional_total",

        "vol_3m",
        "vol_6m",
        "vol_1y",
        "max_drawdown",
    ]
]

csv_data = csv_df.to_csv(
    index=False,
    encoding="utf-8-sig"
)

st.download_button(
    label="📥 下載 TAB 10 評分 CSV",
    data=csv_data,
    file_name="台股100分多因子評分.csv",
    mime="text/csv",
)


# ============================================================
# 47. 評分規則
# ============================================================

with st.expander(
    "📖 查看 TAB 10 評分規則"
):

    st.markdown(
        """
### 台股 100 分多因子評分 V2

| 因子 | 滿分 |
|---|---:|
| 💰 獲利能力 | 25 |
| 📈 成長性 | 20 |
| 💵 評價 | 15 |
| 📊 技術面 | 15 |
| 🏦 籌碼面 | 15 |
| 🛡️ 低波風險 | 10 |
| **總計** | **100** |

#### 💰 獲利能力 25 分
- ROE：8
- ROA：5
- 營業利益率：6
- EPS：6

#### 📈 成長性 20 分
- 營收成長：7
- EPS 成長：8
- 三率三升：5

#### 💵 評價 15 分
- PE：7
- PB：4
- PEG：4
- **越低越有利**

#### 📊 技術面 15 分
- 股價 > MA20：3
- MA20 > MA60：4
- 股價 > MA120：3
- MA60 > MA120：3
- 20 日趨勢：2

#### 🏦 籌碼面 15 分
- 外資：5
- 投信：5
- 自營商：2
- 三大法人：3

#### 🛡️ 低波風險 10 分
- 3 個月波動率：3
- 6 個月波動率：3
- 1 年波動率：2
- 最大回撤：2
- **波動越低越有利**

---

### ⭐ V2 與 V1 的主要差異

**1. 缺資料不直接扣成 0 分**

例如某股票只有 ROE、ROA 資料，
則「獲利能力」會按照現有資料重新分配權重。

**2. TAB 4 營收資料優先**

如果 TAB 4 已經有：
`年增率(YoY%)`

則優先使用 TAB 4，
避免重新使用 Yahoo 的營收成長資料。

**3. TAB 9 三大法人直接使用**

直接讀取：
`st.session_state["institutional_data"]`

不重新呼叫 TAB 9 API。

**4. Yahoo 資料使用 Streamlit Cache**

相同股票已有快取時，
不會再次執行 Yahoo API。

**5. 只有按下「🔄 強制更新」才清除 TAB 10 Yahoo 快取。**

一般切換 Tab、重新執行 Streamlit、
修改其他 UI，
只要 cache key 沒變，就會直接使用快取。

**6. 排名同時顯示資料完整度**

避免某股票因資料缺失而造成不公平比較。
"""
    )


# ============================================================
# 48. Cache 狀態提示
# ============================================================

st.caption(
    "💡 TAB 10 Yahoo 資料快取時間：1 小時；一般重新執行不會重抓 Yahoo。"
)
