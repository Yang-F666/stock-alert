# -*- coding: utf-8 -*-
import akshare as ak
import requests
import os
import datetime
import time
import pandas as pd

SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY")

# ========== 股票配置 ==========

A_STOCKS = {
    "688331": "荣昌生物",
}

HK_STOCKS = {
    "01810": "小米集团-W",
    "06862": "海底捞",
    "09992": "泡泡玛特",
    "09995": "荣昌生物",
}

COST_MAP = {
    "688331": 102.9694,
    "01810":  22.624,
    "06862":  14.589,
    "09992":  207.94,
    "09995":  33.284,
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


def get_history(code, market, months=7):
    end   = datetime.date.today()
    start = (end - datetime.timedelta(days=months * 31)).strftime("%Y%m%d")
    end   = end.strftime("%Y%m%d")

    for attempt in range(3):
        try:
            if market == "A股":
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start, end_date=end, adjust=""
                )
                if df.empty:
                    return None
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "涨跌幅": "pct_chg"
                })
            else:
                df = ak.stock_hk_hist(
                    symbol=code, period="daily",
                    start_date=start, end_date=end, adjust=""
                )
                if df.empty:
                    return None
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "涨跌幅": "pct_chg"
                })
            df["date"]    = pd.to_datetime(df["date"])
            df["close"]   = df["close"].astype(float)
            df["pct_chg"] = df["pct_chg"].astype(float)
            df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            print(f"  数据获取失败 {code} 第{attempt+1}次尝试: {e}")
            if attempt < 2:
                time.sleep(3)
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
    cost = COST_MAP.get(code)
    close = float(df.iloc[-1]["close"])

    recent_6m = df.tail(126)
    high_6m   = recent_6m["close"].max()

    if cost is not None:
        pnl_pct = (close - cost) / cost * 100
        drop_from_high = (close - high_6m) / high_6m * 100

        if pnl_pct > 0 and drop_from_high <= -15.0:
            alerts.append(
                f"📉 **减仓提醒（30%）**\n"
                f"当前盈利 {pnl_pct:+.2f}%，"
                f"但已从近半年高点（{high_6m:.3f}）下跌 {drop_from_high:.2f}%\n"
                f"建议减少 **30%** 仓位锁定部分利润"
            )

        if pnl_pct <= -15.0:
            alerts.append(
                f"🚨 **止损提醒（50%）**\n"
                f"当前亏损已达 {pnl_pct:.2f}%（成本 {cost}，现价 {close:.3f}）\n"
                f"建议减少 **50%** 仓位控制风险"
            )

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
    df = get_history(code, market)
    if df is None or df.empty:
        print(f"    ❌ 数据获取失败（3次重试均失败）")
        return None, []

    latest_date = df.iloc[-1]["date"].date()
    today = datetime.date.today()
    days_diff = (today - latest_date).days
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

    all_data      = []
    alert_items   = []
    failed_stocks = []

    print("[ A 股 ]")
    for code, name in A_STOCKS.items():
        data, alerts = process_stock(code, name, "A股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "A股", alerts))
        else:
            failed_stocks.append(f"{name}({code})")
        time.sleep(2)

    print("\n[ 港 股 ]")
    for code, name in HK_STOCKS.items():
        data, alerts = process_stock(code, name, "港股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "港股", alerts))
        else:
            failed_stocks.append(f"{name}({code})")
        time.sleep(2)

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
                f"{today_str} 所有股票数据获取失败，请检查网络或数据源。\n失败股票：{'、'.join(failed_stocks)}"
            )
        else:
            send_wechat("股市休市通知", f"{today_str} 今日为非交易日，无行情数据。")

    print("\n✅ 执行完成")


if __name__ == "__main__":
    main()
