# -*- coding: utf-8 -*-
import tushare
import requests
import os
import datetime

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN")
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY")

# ================== 你的股票列表（A股+港股） ==================
STOCKS = [
    ["600036.SH", 32.0],   # 招商银行
    ["0700.HK", 380.0],    # 腾讯控股
]
# ============================================================

def send_wechat(title, content):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    try:
        requests.get(url, params={"title": title, "desp": content}, timeout=10)
    except:
        pass

def main():
    tushare.set_token(TUSHARE_TOKEN)
    pro = tushare.pro_api()
    today = datetime.date.today().strftime("%Y%m%d")

    msg = "【每日持仓收盘播报】\n"
    msg += f"日期：{today}\n"

    for code, cost in STOCKS:
        try:
            df = pro.daily(ts_code=code, start_date=today, end_date=today)
            if df.empty:
                msg += f"\n{code}：今日无交易数据（非交易日或接口限制）\n"
                continue

            close = df.iloc[0]["close"]
            profit = (close - cost) / cost * 100
            msg += f"\n{code}：现价 {close:.2f}，成本 {cost:.2f}，盈亏 {profit:+.2f}%\n"

        except Exception as e:
            msg += f"\n{code}：获取数据失败（{str(e)[:30]}...）\n"

    # 强制发送汇总消息
    send_wechat("每日持仓播报", msg)

if __name__ == "__main__":
    main()
