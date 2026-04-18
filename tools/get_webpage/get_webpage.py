#!/usr/bin/env python3
"""
网页正文提取工具
支持简单全文提取和基于 readability-lxml 的智能正文提取
"""

import argparse
import sys
import requests
from readability import Document
from lxml import html


def fetch_html(url, timeout=10, user_agent=None):
    """获取网页 HTML 内容"""
    headers = {
        'User-Agent': user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0"
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        # 自动检测编码
        response.encoding = response.apparent_encoding
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}", file=sys.stderr)
        sys.exit(1)

def readability_extract(html_content) -> str:
    """
    使用 readability-lxml 提取正文
    """
    try:
        doc = Document(html_content)
        title = doc.title()
        content_html = doc.summary()
        # 将 HTML 转为纯文本(保留段落)
        tree = html.fromstring(content_html)
        text = tree.text_content()
        # 可选:输出标题和内容
        output = []
        if title:
            output.append(title)
            output.append("=" * len(title))
            output.append("")
        output.append(text.strip())
        return '\n'.join(output)
    except Exception as e:
        print(f"readability 解析失败: {e}", file=sys.stderr)
        return ""

def main():
    parser = argparse.ArgumentParser(description="提取网页主要文本内容")
    parser.add_argument("url", help="目标网页 URL")
    parser.add_argument("-o", "--output", help="输出文件路径(默认输出到控制台)")
    parser.add_argument("-t", "--timeout", type=int, default=10, help="请求超时时间(秒)")
    parser.add_argument("-u", "--user-agent", help="自定义 User-Agent")

    args = parser.parse_args()

    # 获取 HTML
    html_content = fetch_html(args.url, timeout=args.timeout, user_agent=args.user_agent)

    # 提取正文
    text = readability_extract(html_content)

    # 输出
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(text)
        except IOError as e:
            print(f"写入文件失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(text)

if __name__ == "__main__":
    main()