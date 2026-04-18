#!/usr/bin/env python3
"""
命令行网络搜索工具
支持 维基百科搜索，输入关键词后返回相关的搜索结果
"""

import argparse
import json
import csv
import sys
import time
from random import choice
from urllib.parse import quote

import requests
from lxml import html

# 常用 User-Agent 列表，用于反爬
USER_AGENTS = [
    # firefoxs
    "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:34.0) Gecko/20100101 Firefox/34.0",
]

def search_wikipedia(query, lang='en', limit=10):
    """
    在维基百科上搜索关键词，返回结果列表。
    每个结果包含 title, url, summary。
    """
    # 构造搜索页面 URL
    base_url = f"https://{lang}.wikipedia.org/w/index.php"
    url = f"{base_url}?search={quote(query)}&title=Special%3ASearch&profile=advanced&fulltext=1&ns0=1"
    
    headers = {
        'User-Agent': choice(USER_AGENTS),
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}", file=sys.stderr)
        return []
    
    # 解析 HTML
    tree = html.fromstring(response.content)
    
    # 查找搜索结果列表
    # 维基百科搜索页面结果通常位于 <ul class="mw-search-results"> 下的 <li class="mw-search-result">
    results = []
    result_items = tree.xpath('//ul[@class="mw-search-results"]/li[contains(@class, "mw-search-result")]')
    
    for item in result_items[:limit]:
        # 标题和链接
        title_elem = item.xpath('.//div[@class="mw-search-result-heading"]/a')
        if not title_elem:
            continue
        title = title_elem[0].text_content().strip()
        href = title_elem[0].get('href')
        url = f"https://{lang}.wikipedia.org{href}" if href.startswith('/') else href
        
        # 摘要
        summary_elem = item.xpath('.//div[@class="searchresult"]')
        summary = summary_elem[0].text_content().strip() if summary_elem else ""
        
        results.append({
            'title': title,
            'url': url,
            'summary': summary
        })
    
    return results

def output_results(results, output_file, format):
    """
    根据指定格式输出结果到文件或标准输出。
    """
    if output_file:
        f = open(output_file, 'w', encoding='utf-8')
    else:
        f = sys.stdout
    
    try:
        if format == 'json':
            json.dump(results, f, ensure_ascii=False, indent=2)
        else:  # text
            if not results:
                print("未找到相关结果。", file=f)
            else:
                for idx, res in enumerate(results, 1):
                    print(f"{idx}. {res['title']}", file=f)
                    print(f"   URL: {res['url']}", file=f)
                    print(f"   摘要: {res['summary']}", file=f)
                    print(file=f)
    finally:
        if output_file:
            f.close()

def main():
    parser = argparse.ArgumentParser(description="维基百科命令行搜索工具")
    parser.add_argument('query', help='搜索关键词')
    parser.add_argument('-l', '--lang', default='zh', help='维基百科语言版本(如 en, zh, de)')
    parser.add_argument('-n', '--limit', type=int, default=10, help='返回结果数量(默认10)')
    parser.add_argument('-o', '--output', help='输出文件路径，不指定则输出到标准输出')
    parser.add_argument('-f', '--format', choices=['text', 'json', 'csv'], default='text',
                        help='输出格式(text/json/csv)，默认 text')
    
    args = parser.parse_args()
    
    # 搜索
    results = search_wikipedia(args.query, lang=args.lang, limit=args.limit)
    
    # 输出
    output_results(results, args.output, args.format)

if __name__ == "__main__":
    main()