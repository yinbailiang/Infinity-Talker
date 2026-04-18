#!/usr/bin/env python3
"""
命令行网络搜索工具
支持 Bing、DuckDuckGo 和 Google，返回结构化的搜索结果
"""

import argparse
import json
import csv
import sys
import time
import random

import requests
from lxml import html

# User-Agent 池
USER_AGENTS = [
    # Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


def get_headers():
    """获取随机请求头"""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def web_search(query, engine="bing", num_results=10, lang="zh-CN", timeout=15, retries=3):
    """
    执行网络搜索，返回结构化的搜索结果列表
    """
    if engine == "bing":
        return _search_bing(query, num_results, lang, timeout, retries)
    elif engine == "duckduckgo":
        return _search_duckduckgo(query, num_results, lang, timeout, retries)
    elif engine == "google":
        return _search_google(query, num_results, lang, timeout, retries)
    else:
        print(f"不支持的搜索引擎: {engine}", file=sys.stderr)
        return []


def _search_bing(query, num_results, lang, timeout, retries):
    """Bing 搜索实现"""
    url = "https://www.bing.com/search"
    params = {
        "q": query,
        "count": num_results * 2,  # 多请求一些，因为可能有重复
        "setlang": lang.split("-")[0] if "-" in lang else lang,
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=get_headers(), params=params, timeout=timeout)
            response.raise_for_status()
            tree = html.fromstring(response.text)

            results = []
            
            # 方法1: 标准Bing结果
            for result in tree.xpath('//li[@class="b_algo"]'):
                title_elem = result.xpath('.//h2/a')
                if not title_elem:
                    continue
                title = title_elem[0].text_content().strip()
                link = title_elem[0].get("href")
                snippet_elem = result.xpath('.//div[@class="b_caption"]//p') + result.xpath('.//p')
                snippet = snippet_elem[0].text_content().strip() if snippet_elem else ""
                if link and link.startswith("http"):
                    results.append({"title": title, "link": link, "snippet": snippet})

            # 方法2: 备用XPath
            if not results:
                for li in tree.xpath('//ol[@id="b_results"]/li'):
                    title_elem = li.xpath('.//h2/a')
                    if not title_elem:
                        continue
                    title = title_elem[0].text_content().strip()
                    link = title_elem[0].get("href")
                    if link and link.startswith("http"):
                        snippet_elem = li.xpath('.//p') + li.xpath('.//div[@class="b_caption"]//span')
                        snippet = snippet_elem[0].text_content().strip() if snippet_elem else ""
                        results.append({"title": title, "link": link, "snippet": snippet})

            # 去重并限制数量
            seen = set()
            unique_results = []
            for r in results:
                if r["link"] not in seen:
                    seen.add(r["link"])
                    unique_results.append(r)
            
            return unique_results[:num_results]

        except Exception as e:
            print(f"Bing 请求失败 (尝试 {attempt+1}/{retries}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2)
    return []


def _search_duckduckgo(query, num_results, lang, timeout, retries):
    """DuckDuckGo 搜索实现"""
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    
    for attempt in range(retries):
        try:
            response = requests.post(url, data=params, headers=get_headers(), timeout=timeout)
            response.raise_for_status()
            tree = html.fromstring(response.text)

            results = []
            for result in tree.xpath('//div[@class="result"]'):
                title_elem = result.xpath('.//a[@class="result__a"]')
                if not title_elem:
                    continue
                title = title_elem[0].text_content().strip()
                link = title_elem[0].get("href")
                # DuckDuckGo的链接可能是重定向链接
                if link and link.startswith("/"):
                    link = "https://duckduckgo.com" + link
                snippet_elem = result.xpath('.//a[@class="result__snippet"]')
                if not snippet_elem:
                    snippet_elem = result.xpath('.//td[@class="result__snippet"]')
                snippet = snippet_elem[0].text_content().strip() if snippet_elem else ""
                if link:
                    results.append({"title": title, "link": link, "snippet": snippet})

            return results[:num_results]

        except Exception as e:
            print(f"DuckDuckGo 请求失败 (尝试 {attempt+1}/{retries}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2)
    return []


def _search_google(query, num_results, lang, timeout, retries):
    """Google 搜索实现 (HTML抓取)"""
    url = "https://www.google.com/search"
    params = {
        "q": query,
        "num": num_results * 2,
        "hl": lang.split("-")[0] if "-" in lang else lang,
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=get_headers(), params=params, timeout=timeout)
            response.raise_for_status()
            tree = html.fromstring(response.text)

            results = []
            for result in tree.xpath('//div[@class="g"]'):
                title_elem = result.xpath('.//h3')
                link_elem = result.xpath('.//a[@href][1]')
                if not title_elem or not link_elem:
                    continue
                title = title_elem[0].text_content().strip()
                link = link_elem[0].get("href")
                if link and link.startswith("http"):
                    snippet_elem = result.xpath('.//div[@data-sncf]') + result.xpath('.//span[@class="aCOpRe"]')
                    snippet = snippet_elem[0].text_content().strip() if snippet_elem else ""
                    results.append({"title": title, "link": link, "snippet": snippet})

            # 备用XPath
            if not results:
                for a in tree.xpath('//a[href^="http"]'):
                    href = a.get("href")
                    title_elem = a.xpath('.//h3')
                    if title_elem and href:
                        title = title_elem[0].text_content().strip()
                        results.append({"title": title, "link": href, "snippet": ""})

            return results[:num_results]

        except Exception as e:
            print(f"Google 请求失败 (尝试 {attempt+1}/{retries}): {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(2)
    return []


def output_results(results, output_format, output_file):
    """根据指定格式输出结果"""
    f = open(output_file, "w", encoding="utf-8") if output_file else sys.stdout

    try:
        if output_format == "json":
            json.dump(results, f, ensure_ascii=False, indent=2)
        elif output_format == "csv":
            writer = csv.DictWriter(f, fieldnames=["title", "link", "snippet"])
            writer.writeheader()
            writer.writerows(results)
        else:
            if not results:
                print("未找到任何结果。", file=f)
            else:
                for i, r in enumerate(results, 1):
                    print(f"{i}. {r['title']}", file=f)
                    print(f"   链接: {r['link']}", file=f)
                    if r['snippet']:
                        print(f"   摘要: {r['snippet']}", file=f)
                    print(file=f)
    finally:
        if output_file:
            f.close()


def main():
    parser = argparse.ArgumentParser(description="命令行网络搜索工具")
    parser.add_argument("query", help="搜索关键词")
    parser.add_argument("--engine", "-e", default="bing", choices=["bing", "duckduckgo", "google"],
                        help="搜索引擎 (默认: bing)")
    parser.add_argument("--num-results", "-n", type=int, default=10,
                        help="期望返回的结果数量 (默认: 10)")
    parser.add_argument("--lang", "-l", default="zh-CN",
                        help="语言代码 (默认: zh-CN)")
    parser.add_argument("--timeout", "-t", type=int, default=15,
                        help="请求超时时间(秒) (默认: 15)")
    parser.add_argument("--retries", "-r", type=int, default=3,
                        help="重试次数 (默认: 3)")
    parser.add_argument("--output", "-o", help="输出文件路径")
    parser.add_argument("--format", "-f", default="text", choices=["text", "json", "csv"],
                        help="输出格式 (默认: text)")

    args = parser.parse_args()

    results = web_search(
        query=args.query,
        engine=args.engine,
        num_results=args.num_results,
        lang=args.lang,
        timeout=args.timeout,
        retries=args.retries
    )

    output_results(results, args.format, args.output)


if __name__ == "__main__":
    main()
