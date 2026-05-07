# -*- coding: utf-8 -*-
import tushare
import requests
import os
import datetime

# 从GitHub密钥读取
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN")
SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY")

# ========== 你只需要改这两行 ==========
STOCK_CODE = "600036.SH"   # 你的股票代码
# ====================================

def send_wechat(title, content):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    requests.get(url, params={"title": title, "desp": content})

def main():
    tushare.set_token(TUSHARE_TOKEN)
    pro = tushare.pro_api()

    today = datetime.date.today().strftime("%Y%m%d")
    try:
        df = pro.daily(ts_code=STOCK_CODE, start_date=today, end_date=today)
    except Exception as e:
        send_wechat("股票脚本异常", f"获取数据失败：{str(e)}")
        return

    if df.empty:
        send_wechat("股票提醒", "今日非A股交易日，无收盘数据")
        return

    close_price = df.iloc[0]["close"]
    msg = f"股票代码：{STOCK_CODE}\n今日收盘价：{close_price:.2f} 元"
    send_wechat("每日股票收盘通知", msg)

if __name__ == "__main__":
    main()
