#!/usr/bin/env python3
"""
IP地理位置查询工具
根据IP地址获取地理位置信息，支持查询指定IP或本机IP
"""

import argparse
import json
import sys
import urllib.request
import urllib.parse


def get_ip_location(ip=None, lang="en", timeout=10):
    """
    获取IP地址的地理位置信息
    
    参数:
        ip: IP地址，为None时查询本机IP
        lang: 返回信息的语言 (en, zh, de等)
        timeout: 请求超时时间(秒)
    
    返回:
        dict: 包含位置信息的字典
    """
    base_url = "http://ip-api.com/json/"
    
    if ip:
        url = base_url + ip
    else:
        url = base_url
    
    # 添加语言参数
    url += f"?lang={lang}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data
    except Exception as e:
        return {"status": "fail", "message": str(e)}


def print_location(data, format_type="text"):
    """
    打印位置信息
    
    参数:
        data: API返回的数据
        format_type: 输出格式 (text, json)
    """
    if format_type == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    
    if data.get("status") != "success":
        print(f"查询失败: {data.get('message', '未知错误')}")
        return
    
    print("=" * 40)
    print("IP 地理位置信息")
    print("=" * 40)
    print(f"IP地址:   {data.get('query', 'N/A')}")
    print(f"国家:     {data.get('country', 'N/A')} ({data.get('countryCode', 'N/A')})")
    print(f"地区:     {data.get('regionName', 'N/A')} ({data.get('region', 'N/A')})")
    print(f"城市:     {data.get('city', 'N/A')}")
    print(f"邮编:     {data.get('zip', 'N/A')}")
    print(f"经纬度:   {data.get('lat', 'N/A')}, {data.get('lon', 'N/A')}")
    print(f"时区:     {data.get('timezone', 'N/A')}")
    print("-" * 40)
    print(f"ISP:      {data.get('isp', 'N/A')}")
    print(f"组织:     {data.get('org', 'N/A')}")
    print(f"ASN:      {data.get('as', 'N/A')}")
    print("=" * 40)


def main():
    parser = argparse.ArgumentParser(
        description="IP地理位置查询工具",
        epilog="示例: ip_location.py 8.8.8.8 --lang zh"
    )
    
    parser.add_argument("ip", nargs="?", default=None,
                        help="要查询的IP地址 (不指定则查询本机IP)")
    parser.add_argument("--lang", "-l", default="zh",
                        help="返回信息的语言 (默认: zh, 可选: en, de等)")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text",
                        help="输出格式 (默认: text)")
    parser.add_argument("--timeout", "-t", type=int, default=10,
                        help="请求超时时间(秒) (默认: 10)")
    
    args = parser.parse_args()
    
    # 获取位置信息
    data = get_ip_location(ip=args.ip, lang=args.lang, timeout=args.timeout)
    
    # 输出结果
    print_location(data, format_type=args.format)


if __name__ == "__main__":
    main()
