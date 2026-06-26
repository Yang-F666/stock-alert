# -*- coding: utf-8 -*-
import baostock as bs
import akshare as ak
import requests
import subprocess
import json
from urllib.parse import urlencode
import os
import datetime
import time
import pandas as pd

SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY")

# ========== 股票配置 ==========

A_STOCKS = {
    "688331": "荣昌生物",
    "000021": "深科技",
    "300759": "康龙化成",
}

HK_STOCKS = {
    "01810": "小米集团-W",
    "09992": "泡泡玛特",
}

COST_MAP = {
    "688331": 115.5149,
    "000021": 40.608,
    "300759": 25.3617,
    "01810":  23.279,
    "09992":  206.038,
}

# ==============================


def send_wechat(title, content):
    if not SERVERCHAN_KEY:
        print(f"[预览推送]\n标题：{title}\n内容：{content}")
        return
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    try:
        resp = requests.get(url, params={"title": title, "desp": content}, timeout=10)
        print(f"推送结果：{resp.json()}")
    except Exception as e:
        print(f"推送失败：{e}")


def calc_macd(close_series, fast=12, slow=26, signal=9):
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    return dif, dea, macd_bar


def detect_macd_cross(dif: pd.Series, dea: pd.Series):
    if len(dif) < 2:
        return None
    prev_dif, curr_dif = dif.iloc[-2], dif.iloc[-1]
    prev_dea, curr_dea = dea.iloc[-2], dea.iloc[-1]
    if prev_dif < prev_dea and curr_dif > curr_dea:
        return "golden"
    if prev_dif > prev_dea and curr_dif < curr_dea:
        return "dead"
    return None


def gen_a_secid(code: str) -> str:
    """生成A股东方财富专用 secid"""
    if code.startswith(("6", "5")):
        return f"1.{code}"   # 沪市
    else:
        return f"0.{code}"   # 深市（000、002、300、688等）


def fetch_a_via_curl(code, start_date, end_date):
    """用 curl 直调东财获取A股历史数据"""
    secid = gen_a_secid(code)
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": secid,
        "beg": start_date,
        "end": end_date,
    }
    base_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    full_url = f"{base_url}?{urlencode(params)}"
    cmd = [
        "curl", "-s", "--compressed",
        "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-H", "Referer: https://finance.eastmoney.com/",
        "-H", "Accept-Language: zh-CN,zh;q=0.9",
        "--max-time", "30",
        full_url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data_json = json.loads(result.stdout)
        if not (data_json.get("data") and data_json["data"].get("klines")):
            return None
        rows = [item.split(",") for item in data_json["data"]["klines"]]
        df = pd.DataFrame(rows, columns=[
            "date", "open", "close", "high", "low",
            "volume", "amount", "amplitude", "pct_chg", "change", "turnover"
        ])
        df["date"]    = pd.to_datetime(df["date"])
        df["close"]   = pd.to_numeric(df["close"], errors="coerce")
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"    [curl东财] 失败: {e}")
        return None


def get_history_a(code, months=7):
    """A股：curl东财优先，失败切BaoStock"""
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=months * 31)
    start_str = start.strftime("%Y%m%d")
    end_str   = end.strftime("%Y%m%d")

    print(f"    [curl东财] 尝试A股 {code}...")
    df = fetch_a_via_curl(code, start_str, end_str)
    if df is not None and not df.empty:
        print(f"    [curl东财] A股成功")
        return df

    print(f"    [BaoStock] 切换备用...")
    prefix  = "sh" if code.startswith(("6", "5")) else "sz"
    bs_code = f"{prefix}.{code}"
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,pctChg",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="3"
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "pct_chg"])
            df = df[df["close"] != ""]
            df["date"]    = pd.to_datetime(df["date"])
            df["close"]   = df["close"].astype(float)
            df["pct_chg"] = df["pct_chg"].astype(float)
            df = df.sort_values("date").reset_index(drop=True)
            print(f"    [BaoStock] A股成功")
            return df
    except Exception as e:
        print(f"    [BaoStock] 失败: {e}")
    return None


def get_history_hk(code, months=7):
    """
    港股：三个数据源依次尝试
    1. AkShare stock_hk_hist（东财港股接口）
    2. AkShare stock_hk_daily（新浪港股接口）
    3. BaoStock 港股（部分支持）
    """
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=months * 31)

    # ── 方案1：AkShare 东财港股接口 ──
    for attempt in range(3):
        try:
            df = ak.stock_hk_hist(
                symbol=code, period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust=""
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "收盘": "close", "涨跌幅": "pct_chg",
                    "开盘": "open", "最高": "high", "最低": "low"
                })
                df["date"]    = pd.to_datetime(df["date"])
                df["close"]   = df["close"].astype(float)
                df["pct_chg"] = df["pct_chg"].astype(float)
                df = df.sort_values("date").reset_index(drop=True)
                print(f"    [AkShare东财] 港股成功")
                return df
        except Exception as e:
            print(f"    [AkShare东财] 第{attempt+1}次失败: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))

    # ── 方案2：AkShare 新浪港股接口 ──
    print(f"    [新浪] 尝试港股 {code}...")
    try:
        df = ak.stock_hk_daily(symbol=f"hk{code}", adjust="")
        if df is not None and not df.empty:
            df["date"]    = pd.to_datetime(df["date"])
            df["close"]   = df["close"].astype(float)
            df["pct_chg"] = df["close"].pct_change() * 100
            df["pct_chg"] = df["pct_chg"].fillna(0).round(2)
            df = df[df["date"] >= pd.to_datetime(start)]
            df = df.sort_values("date").reset_index(drop=True)
            if not df.empty:
                print(f"    [新浪] 港股成功")
                return df
    except Exception as e:
        print(f"    [新浪] 失败: {e}")

    # ── 方案3：BaoStock 港股（格式 hk.01810）──
    print(f"    [BaoStock] 尝试港股 {code}...")
    try:
        # BaoStock港股代码去掉前导0，如 01810 → hk.1810
        bs_code = f"hk.{int(code)}"
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,pctChg",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            frequency="d"
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        if rows:
            df =
