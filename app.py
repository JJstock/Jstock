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
import re
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
# TAB 10：台股 100 分多因子評分 V4（修正版）
# 核心：絕對評分 50% + 相對排名 50%
# 修正紀錄：
#   1. 刪除檔案開頭的殘留/錯位程式碼（原本在函式與 df 定義前
#      就呼叫 calculate_factor_score，會直接 NameError）
#   2. 修正多處縮排錯誤（growth_weights / valuation_weights /
#      chip_weights / risk_weights / 獲利能力詳細拆解 expander）
#   3. 評價因子欄位改為 "pe"（原本用 "forward_pe"，
#      但資料欄位其實叫 "pe"，導致評價分數永遠是 NaN）
#   4. 籌碼面因子欄位改為 "foreign" / "trust" / "dealer"
#      （原本用 *_net 字尾，資料欄位沒有這個字尾）
#   5. required_numeric_cols 同步修正欄位名稱
#   6. 修正「獲利能力詳細拆解」迴圈覆蓋 row 變數的 bug
#      （改用 r，避免後面成長性/評價/技術面等 expander
#      顯示成最後一列股票的資料）
#   7. 刪除重複計算的第一次排名（原本用 rank() 算一次，
#      後面 sort_values 又算一次並覆蓋掉，保留後者）
#   8. 說明文字改為 eps 版權重（ROE8 / ROA5 / 營業利益率6 / EPS6）
# ============================================================

# ============================================================
# 2. 工具函式
# ============================================================

def safe_float(value):

    if value is None:
        return np.nan

    try:
        if pd.isna(value):
            return np.nan
    except Exception:
        pass

    try:
        if isinstance(value, str):
            value = (
                value
                .replace(",", "")
                .replace("%", "")
                .strip()
            )

            if value in [
                "",
                "-",
                "--",
                "N/A",
                "NA",
                "None",
                "nan"
            ]:
                return np.nan

        return float(value)

    except Exception:
        return np.nan


def clean_stock_name(value):

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    return str(value).strip()


def get_base_ticker(ticker):

    text = str(ticker).strip().upper()

    text = (
        text
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    match = re.search(
        r"(\d{4})",
        text
    )

    return (
        match.group(1)
        if match
        else text
    )


# ============================================================
# 3. TAB 1 股票清單
# ============================================================

def get_stock_pool():

    # --------------------------------------------------------
    # 最優先：TAB 1 已經存好的 my_stocks
    # --------------------------------------------------------

    if "my_stocks" in st.session_state:

        pool = st.session_state["my_stocks"]

        if isinstance(pool, dict) and pool:

            return [
                {
                    "ticker": str(ticker).strip(),
                    "name": clean_stock_name(name)
                }
                for ticker, name in pool.items()
                if str(ticker).strip()
            ]

    # --------------------------------------------------------
    # 兼容其他 session_state
    # --------------------------------------------------------

    for key in [
        "stock_list",
        "stocks",
        "watchlist",
        "stock_watchlist"
    ]:

        if key not in st.session_state:
            continue

        pool = st.session_state[key]

        if pool is None:
            continue

        if isinstance(pool, dict):

            return [
                {
                    "ticker": str(ticker).strip(),
                    "name": clean_stock_name(name)
                }
                for ticker, name in pool.items()
                if str(ticker).strip()
            ]

        if isinstance(pool, pd.DataFrame):

            ticker_col = next(
                (
                    c for c in [
                        "代號",
                        "股票代號",
                        "證券代號",
                        "ticker",
                        "Ticker",
                        "code",
                        "Code"
                    ]
                    if c in pool.columns
                ),
                None
            )

            name_col = next(
                (
                    c for c in [
                        "名稱",
                        "股票名稱",
                        "證券名稱",
                        "name",
                        "Name"
                    ]
                    if c in pool.columns
                ),
                None
            )

            if ticker_col:

                result = []

                for _, row in pool.iterrows():

                    ticker = str(
                        row[ticker_col]
                    ).strip()

                    if not ticker:
                        continue

                    name = ""

                    if name_col:
                        name = clean_stock_name(
                            row[name_col]
                        )

                    result.append({
                        "ticker": ticker,
                        "name": name
                    })

                return result

    # --------------------------------------------------------
    # 最後嘗試 global my_stocks
    # --------------------------------------------------------

    try:

        if isinstance(my_stocks, dict):

            return [
                {
                    "ticker": str(ticker).strip(),
                    "name": clean_stock_name(name)
                }
                for ticker, name in my_stocks.items()
                if str(ticker).strip()
            ]

    except Exception:
        pass

    return []


# ============================================================
# 4. Yahoo Finance
#
# 只抓一次：
# history + info
#
# cache 1 小時
# ============================================================

@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def get_score_stock_data(ticker):

    ticker = str(ticker).strip().upper()

    base = get_base_ticker(ticker)

    # --------------------------------------------------------
    # TW / TWO fallback
    # --------------------------------------------------------

    if ticker.endswith(".TW"):

        candidates = [
            ticker,
            base + ".TWO"
        ]

    elif ticker.endswith(".TWO"):

        candidates = [
            ticker,
            base + ".TW"
        ]

    else:

        candidates = [
            base + ".TW",
            base + ".TWO"
        ]

    info = {}
    hist = pd.DataFrame()
    actual_ticker = ""

    # --------------------------------------------------------
    # Yahoo
    # --------------------------------------------------------

    for tk in candidates:

        try:

            obj = yf.Ticker(tk)

            # ----------------------------
            # History
            # ----------------------------

            tmp_hist = obj.history(
                period="1y",
                auto_adjust=False
            )

            if (
                tmp_hist is None
                or tmp_hist.empty
                or "Close" not in tmp_hist.columns
            ):
                continue

            hist = tmp_hist.copy()
            actual_ticker = tk

            # ----------------------------
            # info
            # ----------------------------

            try:

                tmp_info = obj.info

                if isinstance(
                    tmp_info,
                    dict
                ):
                    info = tmp_info

            except Exception:

                info = {}

            break

        except Exception:

            continue

    # --------------------------------------------------------
    # 預設回傳
    # --------------------------------------------------------

    empty_result = {

        "actual_ticker": actual_ticker,

        "yahoo_name": (
            info.get("shortName")
            or info.get("longName")
            or ""
        ),

        "price": np.nan,

        "ma20": np.nan,
        "ma60": np.nan,
        "ma120": np.nan,
        "trend20": np.nan,

        "roe": np.nan,
        "roa": np.nan,
        "operating_margin": np.nan,
        "net_margin": np.nan,
        "eps": np.nan,

        "revenue_growth": np.nan,
        "eps_growth": np.nan,

        "pe": np.nan,
        "pb": np.nan,
        "peg": np.nan,

        "vol_3m": np.nan,
        "vol_6m": np.nan,
        "vol_1y": np.nan,

        "max_drawdown": np.nan,
    }

    if hist.empty:
        return empty_result

    # ========================================================
    # Close
    # ========================================================

    close = pd.to_numeric(
        hist["Close"],
        errors="coerce"
    ).dropna()

    if close.empty:
        return empty_result

    price = close.iloc[-1]

    # ========================================================
    # 均線
    # ========================================================

    ma20 = (
        close.rolling(20).mean().iloc[-1]
        if len(close) >= 20
        else np.nan
    )

    ma60 = (
        close.rolling(60).mean().iloc[-1]
        if len(close) >= 60
        else np.nan
    )

    ma120 = (
        close.rolling(120).mean().iloc[-1]
        if len(close) >= 120
        else np.nan
    )

    # ========================================================
    # 20 日趨勢
    # ========================================================

    trend20 = np.nan

    if len(close) >= 21:

        old_price = safe_float(
            close.iloc[-21]
        )

        if (
            not np.isnan(old_price)
            and old_price != 0
        ):

            trend20 = (
                price / old_price
            ) - 1

    # ========================================================
    # 基本面
    # ========================================================

    roe = safe_float(
        info.get("returnOnEquity")
    )

    roa = safe_float(
        info.get("returnOnAssets")
    )

    operating_margin = safe_float(
        info.get("operatingMargins")
    )

    # Yahoo Finance profitMargins：
    # 例如 0.45 = 45%
    net_margin = safe_float(
        info.get("profitMargins")
    )

    eps = safe_float(
        info.get("trailingEps")
    )

    revenue_growth = safe_float(
        info.get("revenueGrowth")
    )

    eps_growth = safe_float(
        info.get("earningsGrowth")
    )

    # ========================================================
    # 評價
    # ========================================================

    pe = safe_float(
        info.get("trailingPE")
    )

    if pd.isna(pe):

        pe = safe_float(
            info.get("forwardPE")
        )

    pb = safe_float(
        info.get("priceToBook")
    )

    peg = safe_float(
        info.get("pegRatio")
    )

    # ========================================================
    # 日報酬
    # ========================================================

    daily_return = (
        close
        .pct_change()
        .dropna()
    )

    # ========================================================
    # 波動率
    # ========================================================

    def annualized_vol(
        window,
        minimum
    ):

        if len(daily_return) < minimum:
            return np.nan

        r = daily_return.tail(window)

        if len(r) < minimum:
            return np.nan

        return (
            r.std()
            * np.sqrt(252)
        )

    vol_3m = annualized_vol(
        63,
        30
    )

    vol_6m = annualized_vol(
        126,
        60
    )

    vol_1y = annualized_vol(
        252,
        126
    )

    # ========================================================
    # 最大回撤
    # ========================================================

    running_max = close.cummax()

    drawdown = (
        close / running_max
    ) - 1

    max_drawdown = drawdown.min()

    # ========================================================
    # 回傳
    # ========================================================

    return {

        "actual_ticker": actual_ticker,

        "yahoo_name": (
            info.get("shortName")
            or info.get("longName")
            or ""
        ),

        "price": price,

        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "trend20": trend20,

        "roe": roe,
        "roa": roa,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "eps": eps,

        "revenue_growth": revenue_growth,
        "eps_growth": eps_growth,

        "pe": pe,
        "pb": pb,
        "peg": peg,

        "vol_3m": vol_3m,
        "vol_6m": vol_6m,
        "vol_1y": vol_1y,

        "max_drawdown": max_drawdown,
    }


# ============================================================
# 5. TAB 4
#
# 直接使用 TAB 4 已經完成的 revenue_data
#
# 不重新讀 rate.csv
# 不重新呼叫 API
# ============================================================

def merge_tab4_revenue_data(df):

    revenue_df = st.session_state.get(
        "revenue_data"
    )

    # --------------------------------------------------------
    # 預設欄位
    # --------------------------------------------------------

    default_cols = {
        "三率三升": "-",
        "月增率(MoM%)": np.nan,
        "年增率(YoY%)": np.nan,
        "累計年增率(%)": np.nan,
    }

    if revenue_df is None:

        for col, value in default_cols.items():
            df[col] = value

        return df

    if not isinstance(
        revenue_df,
        pd.DataFrame
    ):

        try:

            revenue_df = pd.DataFrame(
                revenue_df
            )

        except Exception:

            for col, value in default_cols.items():
                df[col] = value

            return df

    if revenue_df.empty:

        for col, value in default_cols.items():
            df[col] = value

        return df

    # --------------------------------------------------------
    # TAB 4 的代號
    # --------------------------------------------------------

    if "代號" not in revenue_df.columns:

        for col, value in default_cols.items():
            df[col] = value

        return df

    # --------------------------------------------------------
    # 只拿需要欄位
    # --------------------------------------------------------

    merge_cols = [
        "三率三升",
        "月增率(MoM%)",
        "年增率(YoY%)",
        "累計年增率(%)"
    ]

    existing_cols = [
        col
        for col in merge_cols
        if col in revenue_df.columns
    ]

    if not existing_cols:

        for col, value in default_cols.items():
            df[col] = value

        return df

    # --------------------------------------------------------
    # TAB 4 資料
    # --------------------------------------------------------

    right = revenue_df[
        ["代號"] + existing_cols
    ].copy()

    right["_base_code"] = (
        right["代號"]
        .astype(str)
        .str.strip()
        .apply(get_base_ticker)
    )

    # --------------------------------------------------------
    # 同代號保留第一筆
    # 與你 TAB 4 原本邏輯一致
    # --------------------------------------------------------

    right = (
        right
        .drop_duplicates(
            "_base_code",
            keep="first"
        )
    )

    # --------------------------------------------------------
    # TAB 10 股票代號
    # --------------------------------------------------------

    left = df.copy()

    left["_base_code"] = (
        left["ticker"]
        .astype(str)
        .str.strip()
        .apply(get_base_ticker)
    )

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------

    left = left.merge(
        right[
            ["_base_code"] + existing_cols
        ],
        on="_base_code",
        how="left"
    )

    # --------------------------------------------------------
    # 三率三升
    #
    # 完全沿用 TAB 4 已經算好的文字
    # --------------------------------------------------------

    if "三率三升" in left.columns:

        left["三率三升"] = (
            left["三率三升"]
            .fillna("-")
        )

    else:

        left["三率三升"] = "-"

    # --------------------------------------------------------
    # TAB 4 YoY → TAB 10 revenue_growth
    #
    # TAB 4：
    # 25.3 = 25.3%
    #
    # TAB 10：
    # 0.253
    # --------------------------------------------------------

    if "年增率(YoY%)" in left.columns:

        yoy = pd.to_numeric(
            left["年增率(YoY%)"],
            errors="coerce"
        )

        left["revenue_growth"] = (
            yoy / 100
        )

    # --------------------------------------------------------
    # 確保欄位存在
    # --------------------------------------------------------

    for col, value in default_cols.items():

        if col not in left.columns:
            left[col] = value

    left = left.drop(
        columns=["_base_code"],
        errors="ignore"
    )

    return left


# ============================================================
# 6. TAB 9
#
# 直接使用 institutional_data
# ============================================================

def merge_institutional_data(df):

    inst_df = st.session_state.get(
        "institutional_data"
    )

    # --------------------------------------------------------
    # 預設
    # --------------------------------------------------------

    for col in [
        "foreign",
        "trust",
        "dealer",
        "institutional_total"
    ]:

        if col not in df.columns:
            df[col] = np.nan

    if inst_df is None:
        return df

    if not isinstance(
        inst_df,
        pd.DataFrame
    ):

        try:

            inst_df = pd.DataFrame(
                inst_df
            )

        except Exception:

            return df

    if inst_df.empty:
        return df

    if "代號" not in inst_df.columns:
        return df

    # --------------------------------------------------------
    # 股票代號
    # --------------------------------------------------------

    right = inst_df.copy()

    right["_base_code"] = (
        right["代號"]
        .astype(str)
        .str.strip()
        .apply(get_base_ticker)
    )

    # --------------------------------------------------------
    # 找欄位
    # --------------------------------------------------------

    def find_column(candidates):

        for col in candidates:

            if col in right.columns:
                return col

        return None

    foreign_col = find_column([
        "外資買賣超(張)",
        "外資買賣超",
        "外資",
        "外資及陸資",
        "Foreign",
        "foreign"
    ])

    trust_col = find_column([
        "投信買賣超(張)",
        "投信買賣超",
        "投信",
        "Investment Trust",
        "trust"
    ])

    dealer_col = find_column([
        "自營商買賣超(張)",
        "自營商買賣超",
        "自營商",
        "Dealer",
        "dealer"
    ])

    total_col = find_column([
        "三大法人合計(張)",
        "三大法人合計",
        "三大法人",
        "合計",
        "總買賣超",
        "institutional_total"
    ])

    # --------------------------------------------------------
    # 建立 merge dataframe
    # --------------------------------------------------------

    merge_df = right[
        ["_base_code"]
    ].copy()

    if foreign_col:

        merge_df["foreign"] = pd.to_numeric(
            right[foreign_col],
            errors="coerce"
        )

    if trust_col:

        merge_df["trust"] = pd.to_numeric(
            right[trust_col],
            errors="coerce"
        )

    if dealer_col:

        merge_df["dealer"] = pd.to_numeric(
            right[dealer_col],
            errors="coerce"
        )

    if total_col:

        merge_df["institutional_total"] = pd.to_numeric(
            right[total_col],
            errors="coerce"
        )

    # --------------------------------------------------------
    # 沒有三大法人合計 → 自行加總
    # --------------------------------------------------------

    if "institutional_total" not in merge_df.columns:

        available = [
            col
            for col in [
                "foreign",
                "trust",
                "dealer"
            ]
            if col in merge_df.columns
        ]

        if available:

            merge_df[
                "institutional_total"
            ] = merge_df[
                available
            ].sum(
                axis=1,
                min_count=1
            )

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

    merge_df = (
        merge_df
        .drop_duplicates(
            "_base_code",
            keep="last"
        )
    )

    # --------------------------------------------------------
    # TAB 10 代號
    # --------------------------------------------------------

    left = df.copy()

    left["_base_code"] = (
        left["ticker"]
        .astype(str)
        .str.strip()
        .apply(get_base_ticker)
    )

    # --------------------------------------------------------
    # Merge
    # --------------------------------------------------------

    left = left.merge(
        merge_df,
        on="_base_code",
        how="left",
        suffixes=("", "_new")
    )

    # --------------------------------------------------------
    # 如果原欄位沒有資料
    # 才使用新資料
    # --------------------------------------------------------

    for col in [
        "foreign",
        "trust",
        "dealer",
        "institutional_total"
    ]:

        new_col = col + "_new"

        if new_col in left.columns:

            if col not in left.columns:
                left[col] = np.nan

            mask = (
                left[new_col].notna()
            )

            left.loc[
                mask,
                col
            ] = left.loc[
                mask,
                new_col
            ]

    left = left.drop(
        columns=[
            "_base_code",
            "foreign_new",
            "trust_new",
            "dealer_new",
            "institutional_total_new"
        ],
        errors="ignore"
    )

    return left


# ============================================================
# 7. 百分位評分
# ============================================================

def percentile_score(series, higher_is_better=True):
    """
    相對排名分數
    回傳 0~1
    """
    s = pd.to_numeric(series, errors="coerce")

    result = pd.Series(
        np.nan,
        index=s.index,
        dtype=float
    )

    valid = s.notna()
    n = valid.sum()

    if n == 0:
        return result

    if n == 1:
        result.loc[valid] = 1.0
        return result

    result.loc[valid] = (
        s.loc[valid]
        .rank(
            method="average",
            ascending=not higher_is_better,
            pct=True
        )
    )

    return result


def absolute_score(
    series,
    min_value,
    max_value,
    higher_is_better=True
):
    """
    絕對標準化分數
    回傳 0~1

    注意：
    Yahoo 財務比率通常是小數。
    例如：
        ROE 45% = 0.45
        ROA 20% = 0.20
        營益率 30% = 0.30
    """

    s = pd.to_numeric(series, errors="coerce")

    result = pd.Series(
        np.nan,
        index=s.index,
        dtype=float
    )

    valid = s.notna()

    if max_value <= min_value:
        return result

    if higher_is_better:

        result.loc[valid] = (
            (s.loc[valid] - min_value)
            / (max_value - min_value)
        )

    else:

        result.loc[valid] = (
            (max_value - s.loc[valid])
            / (max_value - min_value)
        )

    # 超過上限仍視為滿分
    # 低於下限視為 0 分
    result = result.clip(0, 1)

    return result


# ============================================================
# 8. 二元條件
#
# 真正：
# True  = 1
# False = 0
#
# 不使用 percentile
# ============================================================

def binary_score(condition):

    result = pd.Series(
        np.nan,
        index=condition.index,
        dtype=float
    )

    valid = condition.notna()

    result.loc[valid] = (
        condition.loc[valid]
        .astype(bool)
        .astype(float)
    )

    return result


# ============================================================
# 9. 大因子加權
#
# 評分方式：
# 連續型指標 =
# 50% 絕對評分
# +
# 50% 相對百分位排名
#
# 二元條件 =
# True  = 1
# False = 0
#
# 缺資料：
# 不直接給 0
# 只使用有資料的指標
# 並重新分配該因子的權重
# ============================================================

def calculate_factor_score(
    df,
    factor_name,
    total_weight,
    weight_map,
    higher_map,
    absolute_ranges=None,
    absolute_weight=0.5,
    relative_weight=0.5
):
    """
    多因子評分

    continuous factor：
        絕對評分 × absolute_weight
        +
        相對排名 × relative_weight

    binary factor：
        直接使用 0 / 1

    最終：
        各指標分數 × 指標權重
    """

    if absolute_ranges is None:
        absolute_ranges = {}

    # --------------------------------------------------------
    # 二元條件
    # --------------------------------------------------------

    binary_keys = {
        "price_ma20",
        "ma20_ma60",
        "price_ma120",
        "ma60_ma120",
        "triple_rise",
    }

    score_columns = []
    valid_weight_columns = []

    # --------------------------------------------------------
    # 計算各指標
    # --------------------------------------------------------

    for key, weight in weight_map.items():

        if key not in df.columns:
            continue

        if weight <= 0:
            continue

        # ====================================================
        # 二元指標
        # ====================================================

        if key in binary_keys:

            score = pd.to_numeric(
                df[key],
                errors="coerce"
            )

            score = score.clip(0, 1)

            score_col = f"_score_{factor_name}_{key}"
            weight_col = f"_weight_{factor_name}_{key}"

            df[score_col] = score
            df[weight_col] = np.where(
                score.notna(),
                weight,
                np.nan
            )

            score_columns.append(score_col)
            valid_weight_columns.append(weight_col)

            continue

        # ====================================================
        # 連續指標
        # ====================================================

        series = pd.to_numeric(
            df[key],
            errors="coerce"
        )

        higher_is_better = higher_map.get(
            key,
            True
        )

        # ----------------------------------------------------
        # 相對排名
        # ----------------------------------------------------

        relative = percentile_score(
            series,
            higher_is_better
        )

        relative_col = (
            f"_relative_{factor_name}_{key}"
        )

        df[relative_col] = relative

        # ----------------------------------------------------
        # 絕對評分
        # ----------------------------------------------------

        if key in absolute_ranges:

            min_value, max_value = (
                absolute_ranges[key]
            )

            absolute = absolute_score(
                series,
                min_value,
                max_value,
                higher_is_better
            )

        else:

            absolute = pd.Series(
                np.nan,
                index=df.index,
                dtype=float
            )

        absolute_col = (
            f"_absolute_{factor_name}_{key}"
        )

        df[absolute_col] = absolute

        # ----------------------------------------------------
        # 綜合分數
        # ----------------------------------------------------

        combined = pd.Series(
            np.nan,
            index=df.index,
            dtype=float
        )

        # 同時有絕對 + 相對
        both_valid = (
            absolute.notna()
            & relative.notna()
        )

        combined.loc[both_valid] = (
            absolute.loc[both_valid]
            * absolute_weight
            +
            relative.loc[both_valid]
            * relative_weight
        )

        # 只有相對排名
        relative_only = (
            absolute.isna()
            & relative.notna()
        )

        combined.loc[relative_only] = (
            relative.loc[relative_only]
        )

        # 只有絕對分
        absolute_only = (
            absolute.notna()
            & relative.isna()
        )

        combined.loc[absolute_only] = (
            absolute.loc[absolute_only]
        )

        score_col = (
            f"_score_{factor_name}_{key}"
        )

        weight_col = (
            f"_weight_{factor_name}_{key}"
        )

        df[score_col] = combined

        df[weight_col] = np.where(
            combined.notna(),
            weight,
            np.nan
        )

        score_columns.append(score_col)
        valid_weight_columns.append(weight_col)

    # ========================================================
    # 權重重新分配
    # ========================================================

    if not score_columns:

        df[f"{factor_name}得分"] = np.nan
        df[f"{factor_name}完整度"] = 0

        return df

    score_matrix = df[score_columns]
    weight_matrix = df[valid_weight_columns]

    weighted_score = (
        score_matrix * weight_matrix
    ).sum(axis=1, skipna=True)

    valid_weight = (
        weight_matrix
        .sum(axis=1, skipna=True)
    )

    # --------------------------------------------------------
    # 缺資料時，把剩餘權重重新放大
    # --------------------------------------------------------

    factor_score = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    valid = valid_weight > 0

    factor_score.loc[valid] = (
        weighted_score.loc[valid]
        / valid_weight.loc[valid]
        * total_weight
    )

    df[f"{factor_name}得分"] = (
        factor_score
    )

    # 完整度
    df[f"{factor_name}完整度"] = (
        valid_weight
        / total_weight
    )

    return df


# ============================================================
# 9.5 六大因子權重設定
#
# 修正：SCORE_WEIGHTS 原本整個檔案都沒有定義，
# 只有在下面 growth_weights / valuation_weights /
# chip_weights / risk_weights 被拿來使用，
# 導致 NameError: name 'SCORE_WEIGHTS' is not defined。
#
# 總分分配（對齊上方 st.caption 的說明）：
# 獲利 25｜成長 20｜評價 15｜技術 15｜籌碼 15｜低波 10
#
# 獲利能力的細項權重是直接寫死在
# calculate_factor_score(df, "獲利能力", 25, {...}) 呼叫裡，
# 沒有透過 SCORE_WEIGHTS，所以這裡不需要放 "獲利能力"。
#
# 各細項權重目前是依總分等比例分配的預設值，
# 如果想改變各指標的相對重要性，直接調整這裡的數字即可
# （同一個因子底下的細項總和務必等於該因子的 total）。
# ============================================================

SCORE_WEIGHTS = {

    "成長性": {
        "total": 20,
        "revenue_growth": 10,
        "eps_growth": 10,
    },

    "評價": {
        "total": 15,
        "forward_pe": 5,
        "pb": 5,
        "peg": 5,
    },

    "技術面": {
        "total": 15,
        "price_ma20": 3,
        "ma20_ma60": 3,
        "price_ma120": 3,
        "ma60_ma120": 3,
        "triple_rise": 3,
    },

    "籌碼面": {
        "total": 15,
        "foreign_net": 6,
        "trust_net": 5,
        "dealer_net": 4,
    },

    "低波風險": {
        "total": 10,
        "vol_3m": 3,
        "vol_6m": 3,
        "vol_1y": 2,
        "max_drawdown": 2,
    },
}


# ============================================================
# 10. TAB 10 主畫面
# ============================================================

with tab10:

    st.subheader(
        "🏆 台股 100 分多因子評分"
    )

    st.caption(
        "獲利 25｜成長 20｜評價 15｜"
        "技術 15｜籌碼 15｜低波 10"
    )

    # ========================================================
    # 股票池
    # ========================================================

    stock_pool = get_stock_pool()

    if not stock_pool:

        st.warning(
            "⚠️ 尚未取得 TAB 1 股票清單"
        )

        st.code(
            'st.session_state["my_stocks"] = my_stocks.copy()',
            language="python"
        )

        st.stop()

    # ========================================================
    # 強制更新
    # ========================================================

    col1, col2 = st.columns(
        [1, 5]
    )

    with col1:

        force_refresh = st.button(
            "🔄 更新 Yahoo",
            key="tab10_force_refresh"
        )

    with col2:

        st.caption(
            f"目前 {len(stock_pool)} 檔｜"
            "Yahoo 快取 1 小時｜"
            "TAB 4 / TAB 9 使用既有資料"
        )

    if force_refresh:

        # ----------------------------------------------------
        # 非常重要：
        # 只清 TAB 10 Yahoo cache
        #
        # 不要：
        # st.cache_data.clear()
        #
        # 否則 TAB 1～9 也會全部重新抓
        # ----------------------------------------------------

        get_score_stock_data.clear()

        st.rerun()

    # ========================================================
    # Yahoo 資料
    # ========================================================

    data_list = []

    progress = st.progress(
        0,
        text="載入 Yahoo Finance..."
    )

    total = len(stock_pool)

    for i, item in enumerate(
        stock_pool
    ):

        ticker = item["ticker"]

        name = item["name"]

        data = get_score_stock_data(
            ticker
        )

        data["ticker"] = ticker

        # ----------------------------------------------------
        # 名稱：
        # 先使用 TAB 1
        # 沒有才使用 cache 裡 Yahoo 名稱
        #
        # 不再重新呼叫 yf.Ticker().info
        # ----------------------------------------------------

        if not name:

            name = data.get(
                "yahoo_name",
                ""
            )

        data["name"] = name

        data_list.append(
            data
        )

        progress.progress(
            (i + 1) / total,
            text=f"{ticker} {name}"
        )

    progress.empty()

    # ========================================================
    # DataFrame
    # ========================================================

    df = pd.DataFrame(
        data_list
    )

    # ========================================================
    # TAB 4
    #
    # 一次取得：
    # 三率三升
    # MoM
    # YoY
    # 累計YoY
    # ========================================================

    df = merge_tab4_revenue_data(
        df
    )

    # ========================================================
    # TAB 9
    # ========================================================

    df = merge_institutional_data(
        df
    )

    # ========================================================
    # 確保必要欄位
    #
    # 修正：欄位名稱對齊實際資料
    #   trailing_pe / forward_pe → pe
    #   foreign_net / trust_net / dealer_net → foreign / trust / dealer
    # ========================================================

    required_numeric_cols = [
        "roe",
        "roa",
        "operating_margin",
        "net_margin",
        "eps",

        "revenue_growth",
        "eps_growth",

        "pe",
        "pb",
        "peg",

        "foreign",
        "trust",
        "dealer",

        "vol_3m",
        "vol_6m",
        "vol_1y",
        "max_drawdown",
    ]

    for col in required_numeric_cols:

        if col not in df.columns:
            df[col] = np.nan

    # ========================================================
    # 評價資料清理
    #
    # 負 PE / PB / PEG 沒有評價意義
    # ========================================================

    df.loc[
        (df["pe"] <= 0)
        | (df["pe"] > 200),
        "pe"
    ] = np.nan

    df.loc[
        (df["pb"] <= 0)
        | (df["pb"] > 50),
        "pb"
    ] = np.nan

    df.loc[
        (df["peg"] <= 0)
        | (df["peg"] > 20),
        "peg"
    ] = np.nan

    # ========================================================
    # 三率三升
    #
    # TAB 4 的：
    # 🔥 三率三升 → 1
    # - → 0
    # ========================================================

    def triple_rise_to_score(value):

        if pd.isna(value):
            return np.nan

        text = str(
            value
        ).strip()

        if text in [
            "🔥 三率三升",
            "三率三升",
            "🔥",
            "是",
            "Y",
            "YES",
            "True",
            "TRUE",
            "1",
            "1.0",
            "✓",
            "✔"
        ]:

            return 1.0

        if text in [
            "-",
            "否",
            "N",
            "NO",
            "False",
            "FALSE",
            "0",
            "0.0",
            "✗",
            "✘",
            ""
        ]:

            return 0.0

        try:

            number = float(value)

            return (
                1.0
                if number > 0
                else 0.0
            )

        except Exception:

            return np.nan

    df["triple_rise"] = (
        df["三率三升"]
        .apply(triple_rise_to_score)
    )

    # ========================================================
    # 技術二元條件
    #
    # 真正 0 / 1
    # ========================================================

    df["price_ma20"] = np.where(

        df["price"].notna()
        & df["ma20"].notna(),

        df["price"]
        > df["ma20"],

        np.nan
    )

    df["ma20_ma60"] = np.where(

        df["ma20"].notna()
        & df["ma60"].notna(),

        df["ma20"]
        > df["ma60"],

        np.nan
    )

    df["price_ma120"] = np.where(

        df["price"].notna()
        & df["ma120"].notna(),

        df["price"]
        > df["ma120"],

        np.nan
    )

    df["ma60_ma120"] = np.where(

        df["ma60"].notna()
        & df["ma120"].notna(),

        df["ma60"]
        > df["ma120"],

        np.nan
    )

    # ========================================================
    # 11. 六大因子
    # ========================================================

    # --------------------------------------------------------
    # 獲利能力（eps 版：ROE 8 / ROA 5 / 營業利益率 6 / EPS 6）
    # --------------------------------------------------------

    df = calculate_factor_score(

        df,

        "獲利能力",

        25,

        {
            "roe": 8,
            "roa": 5,
            "operating_margin": 6,
            "eps": 6
        },

        {
            "roe": True,
            "roa": True,
            "operating_margin": True,
            "eps": True
        },

        absolute_ranges={
            "roe": (0.00, 0.30),
            "roa": (0.00, 0.15),
            "operating_margin": (0.00, 0.30),
        },

        absolute_weight=0.5,
        relative_weight=0.5,
    )

    # --------------------------------------------------------
    # 成長性
    # --------------------------------------------------------

    growth_weights = SCORE_WEIGHTS["成長性"]

    df = calculate_factor_score(
        df,
        "成長性",
        growth_weights["total"],
        {
            "revenue_growth": growth_weights["revenue_growth"],
            "eps_growth": growth_weights["eps_growth"],
        },
        {
            "revenue_growth": True,
            "eps_growth": True,
        }
    )

    # --------------------------------------------------------
    # 評價
    #
    # PE / PB / PEG 越低越好
    # 修正：forward_pe → pe（對齊實際資料欄位）
    # --------------------------------------------------------

    valuation_weights = SCORE_WEIGHTS["評價"]

    df = calculate_factor_score(
        df,
        "評價",
        valuation_weights["total"],
        {
            "pe": valuation_weights["forward_pe"],
            "pb": valuation_weights["pb"],
            "peg": valuation_weights["peg"],
        },
        {
            "pe": False,
            "pb": False,
            "peg": False,
        }
    )

    # --------------------------------------------------------
    # 技術面
    # --------------------------------------------------------

    technical_weights = SCORE_WEIGHTS["技術面"]

    df = calculate_factor_score(
        df,
        "技術面",
        technical_weights["total"],
        {
            "price_ma20": technical_weights["price_ma20"],
            "ma20_ma60": technical_weights["ma20_ma60"],
            "price_ma120": technical_weights["price_ma120"],
            "ma60_ma120": technical_weights["ma60_ma120"],
            "triple_rise": technical_weights["triple_rise"],
        },
        {
            "price_ma20": True,
            "ma20_ma60": True,
            "price_ma120": True,
            "ma60_ma120": True,
            "triple_rise": True,
        }
    )

    # --------------------------------------------------------
    # 籌碼面
    # 修正：foreign_net/trust_net/dealer_net → foreign/trust/dealer
    # --------------------------------------------------------

    chip_weights = SCORE_WEIGHTS["籌碼面"]

    df = calculate_factor_score(
        df,
        "籌碼面",
        chip_weights["total"],
        {
            "foreign": chip_weights["foreign_net"],
            "trust": chip_weights["trust_net"],
            "dealer": chip_weights["dealer_net"],
        },
        {
            "foreign": True,
            "trust": True,
            "dealer": True,
        }
    )

    # --------------------------------------------------------
    # 低波風險
    # 波動率：
    # 越低越好
    # 最大回撤：
    # -10% > -30%
    # 所以越高越好
    # --------------------------------------------------------

    risk_weights = SCORE_WEIGHTS["低波風險"]

    df = calculate_factor_score(
        df,
        "低波風險",
        risk_weights["total"],
        {
            "vol_3m": risk_weights["vol_3m"],
            "vol_6m": risk_weights["vol_6m"],
            "vol_1y": risk_weights["vol_1y"],
            "max_drawdown": risk_weights["max_drawdown"],
        },
        {
            "vol_3m": False,
            "vol_6m": False,
            "vol_1y": False,

            # 例如：
            # -10% > -30%
            # 因此越大越好
            "max_drawdown": True,
        }
    )

    # ============================================================
    # 100 分總分
    # ============================================================

    factor_score_cols = [
        "獲利能力得分",
        "成長性得分",
        "評價得分",
        "技術面得分",
        "籌碼面得分",
        "低波風險得分",
    ]

    df["總分"] = df[
        factor_score_cols
    ].sum(axis=1, min_count=1)

    # 避免因為極端資料造成超過 100
    df["總分"] = df["總分"].clip(0, 100)

    # ========================================================
    # 13. 資料完整度
    # ========================================================

    completeness_cols = [

        "獲利能力完整度",
        "成長性完整度",
        "評價完整度",
        "技術面完整度",
        "籌碼面完整度",
        "低波風險完整度"
    ]

    df["資料完整度"] = (
        df[completeness_cols]
        .mean(axis=1)
    )

    # ========================================================
    # 14. 排名
    #
    # 修正：原本前面已用 rank() 算過一次排名，
    # 這裡又用 sort_values 重算並覆蓋，等於白算一次，
    # 故只保留這一版（依總分 → 資料完整度排序）
    # ========================================================

    df = df.sort_values(

        by=[
            "總分",
            "資料完整度"
        ],

        ascending=[
            False,
            False
        ],

        na_position="last"
    ).reset_index(
        drop=True
    )

    df["排名"] = (
        np.arange(
            len(df)
        ) + 1
    )

    # ========================================================
    # 15. KPI
    # ========================================================

    st.markdown(
        "### 📊 評分總覽"
    )

    k1, k2, k3, k4 = st.columns(4)

    valid_count = (
        df["總分"]
        .notna()
        .sum()
    )

    with k1:

        st.metric(
            "監控股票",
            f"{len(df)} 檔"
        )

    with k2:

        st.metric(
            "有評分資料",
            f"{valid_count} 檔"
        )

    with k3:

        if valid_count:

            st.metric(
                "平均分數",
                f"{df['總分'].mean():.1f}"
            )

        else:

            st.metric(
                "平均分數",
                "—"
            )

    with k4:

        if valid_count:

            st.metric(
                "最高分",
                f"{df['總分'].max():.1f}"
            )

        else:

            st.metric(
                "最高分",
                "—"
            )

    # ========================================================
    # 16. 排名表
    # ========================================================

    st.markdown(
        "### 🏆 多因子總排名"
    )

    ranking_df = df[
        [
            "排名",
            "ticker",
            "name",
            "總分",
            "資料完整度",
            "獲利能力得分",
            "成長性得分",
            "評價得分",
            "技術面得分",
            "籌碼面得分",
            "低波風險得分"
        ]
    ].copy()

    ranking_df.columns = [

        "排名",
        "代號",
        "名稱",
        "總分",
        "資料完整度",
        "獲利",
        "成長",
        "評價",
        "技術",
        "籌碼",
        "低波"
    ]

    for col in [
        "總分",
        "獲利",
        "成長",
        "評價",
        "技術",
        "籌碼",
        "低波"
    ]:

        ranking_df[col] = (
            ranking_df[col]
            .round(1)
        )

    ranking_df["資料完整度"] = (
        ranking_df["資料完整度"]
        * 100
    ).round(0)

    st.dataframe(
        ranking_df,
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # 17. TAB 4 資料檢查
    # ========================================================

    with st.expander(
        "📋 TAB 4 營收資料檢查"
    ):

        tab4_display = df[
            [
                "ticker",
                "name",
                "三率三升",
                "月增率(MoM%)",
                "年增率(YoY%)",
                "累計年增率(%)"
            ]
        ].copy()

        tab4_display.columns = [
            "代號",
            "名稱",
            "三率三升",
            "月增率",
            "年增率",
            "累計年增率"
        ]

        st.dataframe(
            tab4_display,
            use_container_width=True,
            hide_index=True,
            column_config={

                "月增率": st.column_config.NumberColumn(
                    "月增率(MoM%)",
                    format="%.2f%%"
                ),

                "年增率": st.column_config.NumberColumn(
                    "年增率(YoY%)",
                    format="%.2f%%"
                ),

                "累計年增率": st.column_config.NumberColumn(
                    "累計年增率(%)",
                    format="%.2f%%"
                )
            }
        )

    # ========================================================
    # 18. 個股詳細
    # ========================================================

    st.markdown(
        "### 🔎 個股詳細評分"
    )

    ticker_options = (
        df["ticker"]
        .astype(str)
        .tolist()
    )

    selected_ticker = st.selectbox(
        "選擇股票",
        ticker_options,
        format_func=lambda x: (
            f"{x} "
            f"{df.loc[df['ticker'] == x, 'name'].iloc[0]}"
        ),
        key="tab10_selected_ticker"
    )

    row = df[
        df["ticker"]
        == selected_ticker
    ].iloc[0]

    # ========================================================
    # 個股 KPI
    # ========================================================

    c1, c2, c3 = st.columns(3)

    with c1:

        if pd.notna(row["總分"]):

            st.metric(
                "總分",
                f"{row['總分']:.1f} / 100"
            )

        else:

            st.metric(
                "總分",
                "—"
            )

    with c2:

        if pd.notna(row["資料完整度"]):

            st.metric(
                "資料完整度",
                f"{row['資料完整度'] * 100:.0f}%"
            )

        else:

            st.metric(
                "資料完整度",
                "—"
            )

    with c3:

        st.metric(
            "排名",
            (
                f"第 {int(row['排名'])} 名"
                if pd.notna(row["排名"])
                else "—"
            )
        )

    # ========================================================
    # 六大因子圖
    # ========================================================

    factor_labels = [
        "獲利能力",
        "成長性",
        "評價",
        "技術面",
        "籌碼面",
        "低波風險"
    ]

    factor_values = [

        row["獲利能力得分"],
        row["成長性得分"],
        row["評價得分"],
        row["技術面得分"],
        row["籌碼面得分"],
        row["低波風險得分"]
    ]

    factor_values = [
        0 if pd.isna(v) else v
        for v in factor_values
    ]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=factor_labels,
            y=factor_values,
            text=[
                f"{v:.1f}"
                for v in factor_values
            ],
            textposition="auto"
        )
    )

    fig.update_layout(
        title=(
            f"{selected_ticker} "
            f"{row['name']}｜六大因子"
        ),
        yaxis_title="得分",
        height=400
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

    # ========================================================
    # 19. 詳細資料
    # ========================================================

    with st.expander("📈 獲利能力詳細拆解"):

        st.markdown(
            """
            **獲利能力 25 分**

            - ROE：8 分
            - ROA：5 分
            - 營業利益率：6 分
            - EPS：6 分

            每個指標：
            **絕對評分 50% + 相對排名 50%**
            """
        )

        if len(df) > 0:

            detail_rows = []

            # 修正：這裡原本用 row 當迴圈變數，
            # 會把上面選定股票的 row 覆蓋掉，
            # 導致後面成長性/評價/技術面等 expander
            # 顯示成最後一列股票的資料。改用 r。
            for _, r in df.iterrows():

                ticker = r.get(
                    "代號",
                    r.get("ticker", "")
                )

                name = r.get(
                    "名稱",
                    r.get("name", "")
                )

                metrics = [
                    ("ROE", "roe", 8),
                    ("ROA", "roa", 5),
                    ("營業利益率", "operating_margin", 6),
                    ("EPS", "eps", 6),
                ]

                for display_name, key, weight in metrics:

                    actual = r.get(key, np.nan)

                    absolute = r.get(
                        f"_absolute_獲利能力_{key}",
                        np.nan
                    )

                    relative = r.get(
                        f"_relative_獲利能力_{key}",
                        np.nan
                    )

                    combined = r.get(
                        f"_score_獲利能力_{key}",
                        np.nan
                    )

                    if pd.notna(actual):

                        detail_rows.append({
                            "代號": ticker,
                            "名稱": name,
                            "指標": display_name,
                            "實際值": actual,
                            "絕對分數": (
                                absolute * 100
                                if pd.notna(absolute)
                                else np.nan
                            ),
                            "相對排名": (
                                relative * 100
                                if pd.notna(relative)
                                else np.nan
                            ),
                            "綜合分數": (
                                combined * 100
                                if pd.notna(combined)
                                else np.nan
                            ),
                            "權重": weight,
                            "加權得分": (
                                combined * weight
                                if pd.notna(combined)
                                else np.nan
                            ),
                        })

            if detail_rows:

                detail_df = pd.DataFrame(
                    detail_rows
                )

                # 百分比顯示
                detail_display = detail_df.copy()

                for col in [
                    "實際值",
                    "絕對分數",
                    "相對排名",
                    "綜合分數",
                ]:
                    if col == "實際值":
                        detail_display[col] = (
                            detail_display[col] * 100
                        ).round(2).astype(str) + "%"

                    else:
                        detail_display[col] = (
                            detail_display[col]
                            .round(2)
                            .astype(str)
                            + "分"
                        )

                detail_display["權重"] = (
                    detail_display["權重"]
                    .astype(str)
                    + "分"
                )

                detail_display["加權得分"] = (
                    detail_display["加權得分"]
                    .round(2)
                    .astype(str)
                )

                st.dataframe(
                    detail_display,
                    use_container_width=True,
                    hide_index=True
                )

    # ========================================================
    # 成長性
    # ========================================================

    with st.expander(
        "🚀 成長性",
        expanded=True
    ):

        a, b = st.columns(2)

        with a:

            st.write(
                "營收 YoY："
                + (
                    f"{row['revenue_growth'] * 100:.2f}%"
                    if pd.notna(
                        row["revenue_growth"]
                    )
                    else "—"
                )
            )

            st.write(
                "EPS 成長："
                + (
                    f"{row['eps_growth'] * 100:.2f}%"
                    if pd.notna(
                        row["eps_growth"]
                    )
                    else "—"
                )
            )

        with b:

            st.write(
                "三率三升："
                + str(
                    row["三率三升"]
                    if pd.notna(
                        row["三率三升"]
                    )
                    else "—"
                )
            )

            st.write(
                "月增率："
                + (
                    f"{row['月增率(MoM%)']:.2f}%"
                    if pd.notna(
                        row["月增率(MoM%)"]
                    )
                    else "—"
                )
            )

            st.write(
                "累計年增率："
                + (
                    f"{row['累計年增率(%)']:.2f}%"
                    if pd.notna(
                        row["累計年增率(%)"]
                    )
                    else "—"
                )
            )

    # ========================================================
    # 評價
    # ========================================================

    with st.expander(
        "💵 評價",
        expanded=True
    ):

        a, b, c = st.columns(3)

        with a:

            st.metric(
                "PE",
                (
                    f"{row['pe']:.2f}"
                    if pd.notna(row["pe"])
                    else "—"
                )
            )

        with b:

            st.metric(
                "PB",
                (
                    f"{row['pb']:.2f}"
                    if pd.notna(row["pb"])
                    else "—"
                )
            )

        with c:

            st.metric(
                "PEG",
                (
                    f"{row['peg']:.2f}"
                    if pd.notna(row["peg"])
                    else "—"
                )
            )

    # ========================================================
    # 技術面
    # ========================================================

    with st.expander(
        "📈 技術面",
        expanded=True
    ):

        a, b = st.columns(2)

        with a:

            st.write(
                "股價："
                + (
                    f"{row['price']:.2f}"
                    if pd.notna(row["price"])
                    else "—"
                )
            )

            st.write(
                "MA20："
                + (
                    f"{row['ma20']:.2f}"
                    if pd.notna(row["ma20"])
                    else "—"
                )
            )

            st.write(
                "MA60："
                + (
                    f"{row['ma60']:.2f}"
                    if pd.notna(row["ma60"])
                    else "—"
                )
            )

            st.write(
                "MA120："
                + (
                    f"{row['ma120']:.2f}"
                    if pd.notna(row["ma120"])
                    else "—"
                )
            )

        with b:

            def show_condition(value):

                if pd.isna(value):
                    return "—"

                return (
                    "✅"
                    if value
                    else "❌"
                )

            st.write(
                "股價 > MA20："
                + show_condition(
                    row["price_ma20"]
                )
            )

            st.write(
                "MA20 > MA60："
                + show_condition(
                    row["ma20_ma60"]
                )
            )

            st.write(
                "股價 > MA120："
                + show_condition(
                    row["price_ma120"]
                )
            )

            st.write(
                "MA60 > MA120："
                + show_condition(
                    row["ma60_ma120"]
                )
            )

            st.write(
                "20日趨勢："
                + (
                    f"{row['trend20'] * 100:.2f}%"
                    if pd.notna(row["trend20"])
                    else "—"
                )
            )

    # ========================================================
    # 籌碼
    # ========================================================

    with st.expander(
        "🏦 三大法人",
        expanded=True
    ):

        a, b = st.columns(2)

        with a:

            st.write(
                "外資："
                + (
                    f"{row['foreign']:,.0f}"
                    if pd.notna(row["foreign"])
                    else "—"
                )
            )

            st.write(
                "投信："
                + (
                    f"{row['trust']:,.0f}"
                    if pd.notna(row["trust"])
                    else "—"
                )
            )

        with b:

            st.write(
                "自營商："
                + (
                    f"{row['dealer']:,.0f}"
                    if pd.notna(row["dealer"])
                    else "—"
                )
            )

            st.write(
                "三大法人："
                + (
                    f"{row['institutional_total']:,.0f}"
                    if pd.notna(
                        row["institutional_total"]
                    )
                    else "—"
                )
            )

    # ========================================================
    # 低波
    # ========================================================

    with st.expander(
        "🛡️ 低波風險",
        expanded=True
    ):

        a, b = st.columns(2)

        with a:

            st.write(
                "3個月波動率："
                + (
                    f"{row['vol_3m'] * 100:.2f}%"
                    if pd.notna(row["vol_3m"])
                    else "—"
                )
            )

            st.write(
                "6個月波動率："
                + (
                    f"{row['vol_6m'] * 100:.2f}%"
                    if pd.notna(row["vol_6m"])
                    else "—"
                )
            )

        with b:

            st.write(
                "1年波動率："
                + (
                    f"{row['vol_1y'] * 100:.2f}%"
                    if pd.notna(row["vol_1y"])
                    else "—"
                )
            )

            st.write(
                "最大回撤："
                + (
                    f"{row['max_drawdown'] * 100:.2f}%"
                    if pd.notna(
                        row["max_drawdown"]
                    )
                    else "—"
                )
            )

    # ========================================================
    # 20. CSV下載
    # ========================================================

    csv_data = df.to_csv(
        index=False,
        encoding="utf-8-sig"
    )

    st.download_button(
        label="⬇️ 下載 TAB 10 評分 CSV",
        data=csv_data,
        file_name="台股100分多因子評分.csv",
        mime="text/csv",
        key="tab10_download_csv"
    )

    # ========================================================
    # 21. 評分規則
    # ========================================================

    with st.expander(
        "📖 100 分評分規則"
    ):

        st.markdown(
    """
    ### 📊 台股 100 分多因子評分 V4

    | 因子 | 分數 | 評分方式 |
    |---|---:|---|
    | 獲利能力 | 25 | 絕對 50% + 相對 50% |
    | 成長性 | 20 | 相對排名 |
    | 評價 | 15 | 相對排名 |
    | 技術面 | 15 | 條件分數 |
    | 籌碼面 | 15 | 相對排名 |
    | 低波風險 | 10 | 相對排名 |
    | **總分** | **100** | |

    #### 獲利能力 25 分
    - ROE：8
    - ROA：5
    - 營業利益率：6
    - EPS：6

    #### 獲利評分方式
    - 絕對評分：50%
    - 同批股票相對排名：50%
    - 超過合理門檻的優質獲利能力不會因為同批股票很強而被過度壓低
    """
)

    display_cols = [
        "排名",
        "代號",
        "名稱",
        "總分",
        "獲利能力得分",
        "成長性得分",
        "評價得分",
        "技術面得分",
        "籌碼面得分",
        "低波風險得分",
    ]

    show_df = df[
        [c for c in display_cols if c in df.columns]
    ].copy()

    score_cols = [
        "總分",
        "獲利能力得分",
        "成長性得分",
        "評價得分",
        "技術面得分",
        "籌碼面得分",
        "低波風險得分",
    ]

    for col in score_cols:
        if col in show_df.columns:
            show_df[col] = show_df[col].round(2)

    st.dataframe(
        show_df,
        use_container_width=True,
        hide_index=True
    )
