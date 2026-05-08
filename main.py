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
    "06160": "荣昌生物",
}

COST_MAP = {
    "688331": 102.9694,
    "01810":  22.662,
    "06862":  14.589,
    "09992":  207.94,
    "06160":  33.284,
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
    """
    计算 MACD 指标
    返回 (dif, dea, macd_bar) 三个 Series
    """
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    return dif, dea, macd_bar


def detect_macd_cross(dif: pd.Series, dea: pd.Series):
    """
    检测最近两根K线是否出现金叉或死叉
    金叉：前一根 dif < dea，最新一根 dif > dea
    死叉：前一根 dif > dea，最新一根 dif < dea
    返回 'golden'（金叉）/ 'dead'（死叉）/ None
    """
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
    """
    获取近 months 个月的日线历史数据
    返回 DataFrame，包含 close 列；失败返回 None
    """
    end   = datetime.date.today()
    # 多取一个月保证MACD有足够的预热数据
    start = (end - datetime.timedelta(days=months * 31)).strftime("%Y%m%d")
    end   = end.strftime("%Y%m%d")

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
        print(f"  历史数据获取失败 {code}: {e}")
        return None


def get_latest(df):
    """从历史DataFrame取最新一行，构建行情dict"""
    row = df.iloc[-1]
    return {
        "close":   float(row["close"]),
        "pct_chg": float(row["pct_chg"]),
        "date":    str(row["date"].date()),
    }


def check_alerts(code, name, market, df):
    """
    执行三条预警规则，返回触发的预警文本列表
    """
    alerts = []
    cost = COST_MAP.get(code)
    close = float(df.iloc[-1]["close"])

    # ── 规则1 & 2：需要近6个月最高价 ──────────────────────────
    # 取最近6个月（约126个交易日）的数据
    recent_6m = df.tail(126)
    high_6m   = recent_6m["close"].max()

    if cost is not None:
        pnl_pct = (close - cost) / cost * 100        # 持仓盈亏比例
        drop_from_high = (close - high_6m) / high_6m * 100  # 距最高点跌幅（负数）

        # 规则1：盈利 且 从半年高点下跌超15%
        if pnl_pct > 0 and drop_from_high <= -15.0:
            alerts.append(
                f"📉 **减仓提醒（30%）**\n"
                f"当前盈利 {pnl_pct:+.2f}%，"
                f"但已从近半年高点（{high_6m:.3f}）下跌 {drop_from_high:.2f}%\n"
                f"建议减少 **30%** 仓位锁定部分利润"
            )

        # 规则2：亏损 且 亏损超15%
        if pnl_pct <= -15.0:
            alerts.append(
                f"🚨 **止损提醒（50%）**\n"
                f"当前亏损已达 {pnl_pct:.2f}%（成本 {cost}，现价 {close:.3f}）\n"
                f"建议减少 **50%** 仓位控制风险"
            )

    # ── 规则3：MACD 金叉 / 死叉 ──────────────────────────────
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

    # 第一行：名称、市场、代码
    line1 = f"**{data['name']}**（{data['market']}）{code}  "

    # 第二行：收盘价与涨跌幅
    arrow = "🔴↑" if data["pct_chg"] > 0 else "🟢↓"
    line2 = f"收盘价：{data['close']:.3f}　{arrow} 今日涨跌：{data['pct_chg']:+.2f}%  "

    # 第三行：持仓盈亏
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
    """
    拉取历史数据，提取最新行情，执行预警检查
    返回 (行情dict, 预警列表) 或 (None, [])
    """
    print(f"  处理 {name}({code})...")
    df = get_history(code, market)
    if df is None or df.empty:
        print(f"    ❌ 数据获取失败")
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

    all_data    = []   # (code, data_dict)
    alert_items = []   # (code, name, market, alerts)

    print("[ A 股 ]")
    for code, name in A_STOCKS.items():
        data, alerts = process_stock(code, name, "A股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "A股", alerts))
        time.sleep(2)

    print("\n[ 港 股 ]")
    for code, name in HK_STOCKS.items():
        data, alerts = process_stock(code, name, "港股")
        if data:
            all_data.append((code, data))
            if alerts:
                alert_items.append((code, name, "港股", alerts))
        time.sleep(2)

    # ── 预警推送（有触发才发）──
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
        report_body += f"\n> 更新时间：{datetime.datetime.now().strftime('%H:%M:%S')}"
        send_wechat(report_title, report_body)
    else:
        send_wechat("股票脚本通知", f"{today_str} 今日无行情数据（可能为非交易日）")

    print("\n✅ 执行完成")


if __name__ == "__main__":
    main()
