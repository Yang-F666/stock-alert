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


def fetch_eastmoney_via_curl(symbol, start_date, end_date, adjust="", period="daily"):
    """
    用系统 curl 命令直接调用东财 API，绕过 Python requests 被识别的问题
    适用于 A股 和 港股
    """
    # A股市场代码判断
    if symbol.isdigit() and len(symbol) == 6:
        market_code = 1 if symbol.startswith(("6", "5")) else 0
        secid = f"{market_code}.{symbol}"
    else:
        # 港股：代码格式如 01810，东财用 116.01810
        secid = f"116.{symbol}"

    adjust_dict = {"qfq": "1", "hfq": "2", "": "0"}
    period_dict = {"daily": "101", "weekly": "102", "monthly": "103"}

    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": period_dict.get(period, "101"),
        "fqt": adjust_dict.get(adjust, "0"),
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
        df["open"]    = pd.to_numeric(df["open"], errors="coerce")
        df["high"]    = pd.to_numeric(df["high"], errors="coerce")
        df["low"]     = pd.to_numeric(df["low"], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        print(f"    [curl] 失败: {e}")
        return None


def get_history_a(code, months=7):
    """A股：优先 curl 直调东财，失败切换 BaoStock"""
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=months * 31)
    start_str = start.strftime("%Y%m%d")
    end_str   = end.strftime("%Y%m%d")

    # 优先：curl 直调东财
    print(f"    [curl东财] 尝试获取A股数据...")
    df = fetch_eastmoney_via_curl(code, start_str, end_str)
    if df is not None and not df.empty:
        print(f"    [curl东财] A股数据获取成功")
        return df

    # 备用：BaoStock
    print(f"    [BaoStock] 尝试获取A股数据...")
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
            print(f"    [BaoStock] A股数据获取成功")
            return df
    except Exception as e:
        print(f"    [BaoStock] 失败: {e}")

    return None


def get_history_hk(code, months=7):
    """港股：优先 curl 直调东财，失败切换新浪接口"""
    end   = datetime.date.today()
    start = end - datetime.timedelta(days=months * 31)
    start_str = start.strftime("%Y%m%d")
    end_str   = end.strftime("%Y%m%d")

    # 优先：curl 直调东财港股
    print(f"    [curl东财] 尝试获取港股数据...")
    df = fetch_eastmoney_via_curl(code, start_str, end_str)
    if df is not None and not df.empty:
        print(f"    [curl东财] 港股数据获取成功")
        return df

    # 备用：新浪财经
    print(f"    [新浪财经] 尝试获取港股数据...")
    try:
        symbol = f"hk{code}"
        df = ak.stock_hk_daily(symbol=symbol, adjust="")
        if df is not None and not df.empty:
            df = df.rename(columns={
                "date": "date", "close": "close",
                "open": "open", "high": "high", "low": "low"
            })
            df["date"]    = pd.to_datetime(df["date"])
            df["close"]   = df["close"].astype(float)
            df["pct_chg"] = df["close"].pct_change() * 100
            df["pct_chg"] = df["pct_chg"].fillna(0)
            df = df[df["date"] >= pd.to_datetime(start)]
            df = df.sort_values("date").reset_index(drop=True)
            if not df.empty:
                print(f"    [新浪财经] 港股数据获取成功")
                return df
    except Exception as e:
        print(f"    [新浪财经] 失败: {e}")

    return None


def get_latest(df):
    row = df.iloc[-1]
    return {
        "close":   float(row["close"]),
        "pct_chg": float(row["pct_chg"]),
        "date":    str(row["date"].date()),
    }


def check_alerts(code, name, market, df):
    alerts = []
    cost  = COST_MAP.get(code)
    close = float(df.iloc[-1]["close"])

    recent_6m = df.tail(126)
    high_6m   = recent_6m["close"].max()

    if cost is not None:
        pnl_pct        = (close - cost) / cost * 100
        drop_from_high = (close - high_6m) / high_6m * 100

        # 规则1：盈利 且 从半年高点下跌 ≥ 15%（不超过25%）
        if pnl_pct > 0 and drop_from_high <= -15.0 and drop_from_high > -25.0:
            alerts.append(
                f"📉 **减仓提醒（30%）**\n"
                f"当前盈利 {pnl_pct:+.2f}%，"
                f"但已从近半年高点（{high_6m:.3f}）下跌 {drop_from_high:.2f}%\n"
                f"建议减少 **30%** 仓位锁定部分利润"
            )

        # 规则2：亏损 且 亏损 ≥ 15%
        if pnl_pct <= -15.0:
            alerts.append(
                f"🚨 **止损提醒（50%）**\n"
                f"当前亏损已达 {pnl_pct:.2f}%（成本 {cost}，现价 {close:.3f}）\n"
                f"建议减少 **50%** 仓位控制风险"
            )

        # 规则4：盈利 且 从半年高点下跌 ≥ 25%
        if pnl_pct > 0 and drop_from_high <= -25.0:
            alerts.append(
                f"🔴 **清仓提醒**\n"
                f"当前盈利 {pnl_pct:+.2f}%，"
                f"但已从近半年高点（{high_6m:.3f}）下跌 {drop_from_high:.2f}%\n"
                f"建议 **清仓** 保留利润"
            )

    # 规则3：MACD 金叉 / 死叉
    dif, dea, _ = calc_macd(df["close"])
    cross = detect_macd_cross(dif, dea)
    if cross == "golden":
        alerts.append(
            f"✨ **MACD 金叉**\n"
            f"DIF（{dif.iloc[-1]:.4f}）上穿 DEA（{dea.iloc[-1]:.4f}）\n"
            f"日线出现看多信号，关注后续走势"
        )
    elif cross == "dead":
        alerts.append(
            f"💀 **MACD 死叉**\n"
            f"DIF（{dif.iloc[-1]:.4f}）下穿 DEA（{dea.iloc[-1]:.4f}）\n"
            f"日线出现看空信号，注意控制风险"
        )

    return alerts


def format_stock_line(data, code):
    cost = COST_MAP.get(code)

    line1 = f"**{data['name']}**（{data['market']}）{code}  "
    arrow = "🔴↑" if data["pct_chg"] > 0 else "🟢↓"
    line2 = f"收盘价：{data['close']:.3f}　{arrow} 今日涨跌：{data['pct_chg']:+.2f}%  "

    if cost is not None:
        diff = data["close"] - cost
        pct  = (diff / cost) * 100
        pl_emoji = "📈" if diff >= 0 else "📉"
        line3 = f"{pl_emoji} 持仓盈亏：{diff:+.3f}　累计盈亏：{pct:+.2f}%"
    else:
        line3 = ""

    lines = [line1, line2]
    if line3:
        lines.append(line3)
    return "\n".join(lines) + "\n\n"


def process_stock(code, name, market):
    print(f"  处理 {name}({code})...")

    if market == "A股":
        df = get_history_a(code)
    else:
        df = get_history_hk(code)

    if df is None or df.empty:
        print(f"    ❌ 数据获取失败（所有数据源均失败）")
        return None, []

    latest_date = df.iloc[-1]["date"].date()
    today       = datetime.date.today()
    days_diff   = (today - latest_date).days
    if days_diff > 5:
        print(f"    ⚠️ 数据过旧（最新日期：{latest_date}），跳过")
        return None, []

    latest = get_latest(df)
    latest["name"]   = name
    latest["market"] = market

    alerts = check_alerts(code, name, market, df)
    print(f"    ✅ 收盘={latest['close']:.3f}  涨跌={latest['pct_chg']:+.2f}%  预警={len(alerts)}条")
    return latest, alerts


def main():
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"运行时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    print("BaoStock 登录...")
    lg = bs.login()
    if lg.error_code != "0":
        print(f"BaoStock 登录失败: {lg.error_msg}")
    else:
        print("BaoStock 登录成功")

    all_data      = []
    alert_items   = []
    failed_stocks = []

    print("\n[ A 股 ]")
    for code, name in A_STOCKS.items():
        data, alerts = process_stock(code, name, "A股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "A股", alerts))
        else:
            failed_stocks.append(f"{name}({code})")
        time.sleep(3)

    print("\n[ 港 股 ]")
    for code, name in HK_STOCKS.items():
        data, alerts = process_stock(code, name, "港股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "港股", alerts))
        else:
            failed_stocks.append(f"{name}({code})")
        time.sleep(3)

    bs.logout()

    # ── 预警推送 ──
    if alert_items:
        alert_title = f"🚨 操作提醒（{len(alert_items)} 只）{today_str}"
        alert_body  = ""
        for code, name, market, alerts in alert_items:
            alert_body += f"### {name}（{market}）{code}\n\n"
            for a in alerts:
                alert_body += a + "\n\n"
            alert_body += "---\n\n"
        send_wechat(alert_title, alert_body)
    else:
        print("今日无预警触发")

    # ── 每日行情汇总 ──
    if all_data:
        report_title = f"📈 每日行情 {today_str}"
        report_body  = ""
        for code, data in all_data:
            report_body += format_stock_line(data, code)
        if failed_stocks:
            report_body += f"\n⚠️ 以下股票数据获取失败：{'、'.join(failed_stocks)}\n"
        report_body += f"\n> 更新时间：{datetime.datetime.now().strftime('%H:%M:%S')}"
        send_wechat(report_title, report_body)
    else:
        if failed_stocks:
            send_wechat(
                "⚠️ 数据获取异常",
                f"{today_str} 所有股票数据获取失败。\n失败股票：{'、'.join(failed_stocks)}"
            )
        else:
            send_wechat("股市休市通知", f"{today_str} 今日为非交易日，无行情数据。")

    print("\n✅ 执行完成")


if __name__ == "__main__":
    main()
