#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时时间显示程序
显示本机实时时间，精确到毫秒
"""

import time
from datetime import datetime
import sys
import os

def clear_screen():
    """清屏函数"""
    os.system('clear' if os.name == 'posix' else 'cls')

def display_realtime():
    """显示实时时间，精确到毫秒"""
    try:
        while True:
            current_time = datetime.now()
            
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            clear_screen()
            print("=" * 50)
            print("        本机实时时间显示")
            print("=" * 50)
            print(f"\n当前时间: {formatted_time}")
            print(f"时间戳: {current_time.timestamp():.3f}")
            print(f"星期: {current_time.strftime('%A')}")
            print(f"日期: {current_time.strftime('%Y年%m月%d日')}")
            print("\n按 Ctrl+C 退出程序")
            print("=" * 50)
            
            time.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\n\n程序已退出")
        sys.exit(0)
    except Exception as e:
        print(f"发生错误: {e}")
        sys.exit(1)

def get_current_time_string():
    """获取当前时间字符串（精确到毫秒）"""
    current_time = datetime.now()
    return current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def get_timestamp_milliseconds():
    """获取当前时间戳（毫秒）"""
    return int(datetime.now().timestamp() * 1000)

if __name__ == "__main__":
    print("实时时间显示程序启动...")
    print("显示精确到毫秒的本机时间")
    print("按 Enter 开始显示，或输入 'q' 退出")
    
    user_input = input().strip().lower()
    if user_input == 'q':
        print("程序退出")
        sys.exit(0)
    
    display_realtime()