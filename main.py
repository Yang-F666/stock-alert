# -*- coding: utf-8 -*-
import akshare as ak
import requests
import os
import datetime
import time

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

# 成本价及预警规则
ALERT_RULES = {
    # A 股
    "688331": [
        {"name": "🔴 跌破成本价(102.97)", "condition": lambda row: row["close"] < 102.9694},
        {"name": "🚀 涨幅超5%",           "condition": lambda row: row["pct_chg"] >= 5.0},
        {"name": "⚠️ 跌幅超5%",           "condition": lambda row: row["pct_chg"] <= -5.0},
    ],
    # 港股
    "01810": [
        {"name": "🔴 跌破成本价(22.66)",  "condition": lambda row: row["close"] < 22.662},
        {"name": "🚀 涨幅超5%",           "condition": lambda row: row["pct_chg"] >= 5.0},
        {"name": "⚠️ 跌幅超5%",           "condition": lambda row: row["pct_chg"] <= -5.0},
    ],
    "06862": [
        {"name": "🔴 跌破成本价(14.59)",  "condition": lambda row: row["close"] < 14.589},
        {"name": "🚀 涨幅超5%",           "condition": lambda row: row["pct_chg"] >= 5.0},
        {"name": "⚠️ 跌幅超5%",           "condition": lambda row: row["pct_chg"] <= -5.0},
    ],
    "09992": [
        {"name": "🔴 跌破成本价(207.94)", "condition": lambda row: row["close"] < 207.94},
        {"name": "🚀 涨幅超5%",           "condition": lambda row: row["pct_chg"] >= 5.0},
        {"name": "⚠️ 跌幅超5%",           "condition": lambda row: row["pct_chg"] <= -5.0},
    ],
    "06160": [
        {"name": "🔴 跌破成本价(33.28)",  "condition": lambda row: row["close"] < 33.284},
        {"name": "🚀 涨幅超5%",           "condition": lambda row: row["pct_chg"] >= 5.0},
        {"name": "⚠️ 跌幅超5%",           "condition": lambda row: row["pct_chg"] <= -5.0},
    ],
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


def get_a_stock(code, name):
    try:
        today = datetime.date.today().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=today, end_date=today, adjust=""
        )
        if df.empty:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date="20250101", end_date=today, adjust=""
            )
            if df.empty:
                return None
        row = df.iloc[-1]
        return {
            "name": name, "code": code, "market": "A股",
            "date":    str(row["日期"]),
            "close":   float(row["收盘"]),
            "pct_chg": float(row["涨跌幅"]),
            "high":    float(row["最高"]),
            "low":     float(row["最低"]),
            "open":    float(row["开盘"]),
        }
    except Exception as e:
        print(f"[A股] {name}({code}) 获取失败：{e}")
        return None


def get_hk_stock(code, name):
    try:
        today = datetime.date.today().strftime("%Y%m%d")
        df = ak.stock_hk_hist(
            symbol=code, period="daily",
            start_date=today, end_date=today, adjust=""
        )
        if df.empty:
            df = ak.stock_hk_hist(
                symbol=code, period="daily",
                start_date="20250101", end_date=today, adjust=""
            )
            if df.empty:
                return None
        row = df.iloc[-1]
        return {
            "name": name, "code": code, "market": "港股",
            "date":    str(row["日期"]),
            "close":   float(row["收盘"]),
            "pct_chg": float(row["涨跌幅"]),
            "high":    float(row["最高"]),
            "low":     float(row["最低"]),
            "open":    float(row["开盘"]),
        }
    except Exception as e:
        print(f"[港股] {name}({code}) 获取失败：{e}")
        return None


def check_alerts(data):
    rules = ALERT_RULES.get(data["code"], [])
    triggered = []
    for rule in rules:
        try:
            if rule["condition"](data):
                triggered.append(rule["name"])
        except Exception as e:
            print(f"规则执行异常：{e}")
    return triggered



def format_stock_line(data):
    cost_map = {
        "688331": 102.9694,
        "01810":  22.662,
        "06862":  14.589,
        "09992":  207.94,
        "06160":  33.284,
    }
    cost = cost_map.get(data["code"])

    # 第一行：名称、市场、代码（行尾加两个空格强制换行）
    line1 = f"**{data['name']}**（{data['market']}）{data['code']}  "

    # 第二行：收盘价与涨跌幅
    arrow = "🔴↑" if data["pct_chg"] > 0 else "🟢↓"
    line2 = f"收盘价：{data['close']:.3f}　{arrow} 今日涨跌：{data['pct_chg']:+.2f}%  "

    # 第三行：持仓盈亏与累计盈亏比例
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

    # 用 \n 连接各行，每股之间空一行
    return "\n".join(lines) + "\n\n"


def main():
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*50}")
    print(f"运行时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    all_data = []
    alert_items = []

    print("[ A 股 ]")
    for code, name in A_STOCKS.items():
        data = get_a_stock(code, name)
        if data:
            all_data.append(data)
            triggered = check_alerts(data)
            if triggered:
                alert_items.append((data, triggered))
            print(f"  ✅ {name}({code}) 收盘={data['close']:.2f} 涨跌={data['pct_chg']:+.2f}%")
        else:
            print(f"  ❌ {name}({code}) 获取失败")
        time.sleep(1)

    print("\n[ 港 股 ]")
    for code, name in HK_STOCKS.items():
        data = get_hk_stock(code, name)
        if data:
            all_data.append(data)
            triggered = check_alerts(data)
            if triggered:
                alert_items.append((data, triggered))
            print(f"  ✅ {name}({code}) 收盘={data['close']:.3f} 涨跌={data['pct_chg']:+.2f}%")
        else:
            print(f"  ❌ {name}({code}) 获取失败")
        time.sleep(1)

    # 预警推送
    if alert_items:
        alert_title = f"🚨 股票预警（{len(alert_items)} 条）{today_str}"
        alert_body = ""
        for data, rules in alert_items:
            alert_body += format_stock_line(data)
            alert_body += f"触发规则：{'、'.join(rules)}\n\n---\n\n"
        send_wechat(alert_title, alert_body)

    # 每日行情汇总
    if all_data:
        report_title = f"📈 每日行情 {today_str}"
        report_body = ""
        for data in all_data:
            report_body += format_stock_line(data) + "\n"
        report_body += f"\n> 更新时间：{datetime.datetime.now().strftime('%H:%M:%S')}"
        send_wechat(report_title, report_body)
    else:
        send_wechat("股票脚本通知", f"{today_str} 今日无行情数据（可能为非交易日）")

    print("\n✅ 执行完成")


if __name__ == "__main__":
    main()
