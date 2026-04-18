#!/usr/bin/env python3
"""
命令行维基百科词条获取工具
"""

import argparse
import json
import csv
import random
import sys
import time
from lxml import html
from random import choice
from urllib.parse import quote

import requests
from lxml import html

# 常用 User-Agent 列表，用于反爬
USER_AGENTS = [
    # firefoxs
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0",
]

def get_headers():
    """获取随机请求头"""
    return {
        "User-Agent": random.choice(USER_AGENTS)
    }


def get_wiki_page(key_word:str):
    headers = get_headers()
    url = f"https://zh.wikipedia.org/wiki/{key_word}"
    resp = requests.get(url=url,headers=headers)
    resp.raise_for_status()
    page = html.fromstring(resp.text)

    return page.xpath("/html/body/div[3]/div/div[3]/main/div[3]/div[3]/div[1]/p[position() < 2]//text()")

print("\n".join(get_wiki_page("黑洞")))