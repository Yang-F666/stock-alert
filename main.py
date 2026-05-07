# -*- coding: utf-8 -*-
import requests
import os

SERVERCHAN_KEY = os.getenv("SERVERCHAN_KEY")

def send_wechat(title, content):
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    requests.get(url, params={"title": title, "desp": content})

if __name__ == "__main__":
    send_wechat("GitHub测试", "脚本已运行，Server酱连接正常")
