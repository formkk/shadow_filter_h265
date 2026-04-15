#!/usr/bin/env python3
"""
简单验证管道时延信息显示
"""

import cv2
import numpy as np

def simple_verify(image_path):
    """简单验证图像中的覆盖层信息"""
    
    img = cv2.imread(image_path)
    if img is None:
        print(f"无法读取图像: {image_path}")
        return False
    
    print(f"图像尺寸: {img.shape}")
    
    top_region = img[:150, :400]
    
    non_black_mask = cv2.inRange(top_region, (1, 1, 1), (255, 255, 255))
    non_black_pixels = cv2.countNonZero(non_black_mask)
    
    print(f"顶部区域非黑色像素数量: {non_black_pixels}")
    
    latency_region = img[80:125, 10:350]
    
    black_mask = cv2.inRange(latency_region, (0, 0, 0), (30, 30, 30))
    black_pixels = cv2.countNonZero(black_mask)
    
    color_mask = cv2.inRange(latency_region, (50, 50, 50), (255, 255, 255))
    color_pixels = cv2.countNonZero(color_mask)
    
    print(f"时延区域黑色像素: {black_pixels}")
    print(f"时延区域彩色像素: {color_pixels}")
    
    cv2.imwrite('simple_top_region.png', top_region)
    cv2.imwrite('simple_latency_region.png', latency_region)
    
    bottom_region = img[-50:, :300]
    bottom_non_black = cv2.countNonZero(cv2.inRange(bottom_region, (1, 1, 1), (255, 255, 255)))
    print(f"底部区域非黑色像素: {bottom_non_black}")
    
    cv2.imwrite('simple_bottom_region.png', bottom_region)
    
    has_overlay = non_black_pixels > 1000
    has_latency_info = black_pixels > 500 and color_pixels > 200
    has_timestamp = bottom_non_black > 100
    
    print(f"\n检测结果:")
    print(f"包含覆盖层信息: {has_overlay}")
    print(f"包含时延信息: {has_latency_info}")
    print(f"包含时间戳: {has_timestamp}")
    
    return has_overlay and has_latency_info

if __name__ == "__main__":
    image_path = "test_frame.png"
    
    print("=== 简单验证管道时延信息显示 ===")
    result = simple_verify(image_path)
    
    if result:
        print("\n✅ 成功: 检测到管道时延信息显示功能正常工作!")
    else:
        print("\n⚠️  需要检查: 可能存在显示问题")
    
    print("\n生成的检查文件:")
    print("- simple_top_region.png: 顶部覆盖层区域")
    print("- simple_latency_region.png: 时延显示区域")
    print("- simple_bottom_region.png: 底部时间戳区域")