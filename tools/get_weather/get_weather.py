#!/usr/bin/env python3
"""
命令行天气查询工具
基于 wttr.in 服务，支持当前天气、多日预报、多种输出格式
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request

def get_weather(city, format_type="pretty", units="m", forecast_days=1, lang="en"):
    """
    获取天气信息

    参数:
        city (str): 城市名称
        format_type (str): 输出格式，可选 "pretty"(终端友好)、"json"、"text"
        units (str): 单位制，"m"(公制)、"u"(英制)
        forecast_days (int): 预报天数，1 表示仅当前天气
        lang (str): 语言代码(如 "zh"、"en")

    返回:
        str 或 dict: 根据 format_type 返回相应格式的数据
    """
    # 构建 wttr.in URL
    encoded_city = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded_city}"

    # 添加参数
    params = []
    if format_type == "json":
        params.append("format=j1")
    elif format_type == "text":
        params.append("format=%l:+%c+%t+%h+%w")  # 位置、天气、温度、湿度、风速
    else:  # pretty 默认
        # 终端友好格式，无需额外参数
        pass

    if units == "u":
        params.append("u")  # 英制单位
    # m 是默认单位，无需添加

    if forecast_days > 0:
        params.append(f"{forecast_days}")  # 预报天数

    if lang != "en":
        params.append(f"lang={lang}")

    if params:
        url += "?" + "&".join(params)

    try:
        # 发送请求
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read().decode('utf-8')

        if format_type == "json":
            return json.loads(data)
        else:
            return data.strip()
    except json.JSONDecodeError as e:
        return f"JSON 解析错误: {e}"
    except Exception as e:
        return f"获取天气失败: {e}"

def print_weather_json(data):
    """打印 JSON 格式的天气数据(友好展示)"""
    try:
        current = data['current_condition'][0]
        print(f"城市: {data['nearest_area'][0]['areaName'][0]['value']}")
        print(f"温度: {current['temp_C']}°C")
        print(f"体感温度: {current['FeelsLikeC']}°C")
        print(f"天气状况: {current['weatherDesc'][0]['value']}")
        print(f"湿度: {current['humidity']}%")
        print(f"风速: {current['windspeedKmph']} km/h")
        print(f"气压: {current['pressure']} mb")
        print(f"能见度: {current['visibility']} km")

        # 打印未来天气预报
        if 'weather' in data and len(data['weather']) > 1:
            print("\n未来天气预报:")
            for day in data['weather'][1:4]:  # 最多显示3天预报
                print(f"  {day['date']}: {day['hourly'][0]['weatherDesc'][0]['value']}, "
                      f"{day['mintempC']}°C ~ {day['maxtempC']}°C")
    except (KeyError, IndexError) as e:
        print(f"数据解析失败: {e}")
        print("原始 JSON 数据:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

def main():
    parser = argparse.ArgumentParser(
        description="命令行天气查询工具",
        epilog="示例: weather.py 上海 -f pretty -d 2 -l zh"
    )

    parser.add_argument("city", help="城市名称(支持中文，如:上海、Beijing)")
    parser.add_argument("-f", "--format", choices=["pretty", "text", "json"],
                        default="pretty", help="输出格式 (默认: pretty)")
    parser.add_argument("-u", "--units", choices=["m", "u"],
                        default="m", help="单位制: m=公制(°C,km/h), u=英制(°F,mph) (默认: m)")
    parser.add_argument("-d", "--days", type=int, default=1,
                        help="预报天数 (1=仅当前, 2-3=未来预报)")
    parser.add_argument("-l", "--lang", default="zh",
                        help="语言代码 (默认: zh, 可选: en, zh, fr, de 等)")
    parser.add_argument("--raw", action="store_true",
                        help="输出原始 JSON(仅在 format=json 时生效)")

    args = parser.parse_args()

    # 获取天气数据
    result = get_weather(
        city=args.city,
        format_type=args.format,
        units=args.units,
        forecast_days=args.days,
        lang=args.lang
    )

    # 根据格式输出
    if args.format == "json" and not args.raw and isinstance(result, dict):
        print_weather_json(result)
    elif isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()