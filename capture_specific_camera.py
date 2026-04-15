#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指定摄像头图像采集程序
从指定摄像头采集3张图像并保存
"""

import cv2
import os
import time
from datetime import datetime
import argparse

class SpecificCameraCapture:
    def __init__(self, camera_id=0, num_images=3, output_dir="captured_images", delay=1.0):
        """
        初始化指定摄像头采集器
        
        Args:
            camera_id: 摄像头索引，默认为0
            num_images: 要采集的图像数量，默认为3
            output_dir: 输出目录
            delay: 采集间隔（秒）
        """
        self.camera_id = camera_id
        self.num_images = num_images
        self.output_dir = output_dir
        self.delay = delay
        self.camera = None
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        print("指定摄像头图像采集程序")
        print("=" * 50)
        print(f"摄像头ID: {self.camera_id}")
        print(f"采集数量: {self.num_images}张")
        print(f"采集间隔: {self.delay}秒")
        
    def initialize_camera(self):
        """初始化摄像头"""
        try:
            
            self.camera = cv2.VideoCapture(self.camera_id)
            
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 576)
            
            if self.camera.isOpened():
                ret, frame = self.camera.read()
                if ret and frame is not None:
                    print(f"摄像头 /dev/video{self.camera_id} 初始化成功")
                    return True
                else:
                    print(f"摄像头 /dev/video{self.camera_id} 无法读取帧")
                    self.camera.release()
                    self.camera = None
                    return False
            else:
                print(f"摄像头 /dev/video{self.camera_id} 无法打开")
                return False
                
        except Exception as e:
            print(f"摄像头 /dev/video{self.camera_id} 初始化失败: {e}")
            return False
    
    def capture_images(self):
        """采集图像"""
        if not self.camera:
            print("摄像头未初始化")
            return []
            
        captured_files = []
        
        print("\n开始采集图像...")
        
        for _ in range(5):
            self.camera.read()
            time.sleep(0.1)
        
        for i in range(self.num_images):
            try:
                ret, frame = self.camera.read()
                
                if ret and frame is not None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    filename = f"camera_{self.camera_id}_image_{i+1}_{timestamp}.jpg"
                    filepath = os.path.join(self.output_dir, filename)
                    cv2.imwrite(filepath, frame)
                    
                    captured_files.append(filepath)
                    print(f"图像 {i+1}/{self.num_images} 采集成功: {filepath}")
                else:
                    print(f"图像 {i+1}/{self.num_images} 采集失败")
                    
            except Exception as e:
                print(f"图像 {i+1}/{self.num_images} 采集异常: {e}")
                
            if i < self.num_images - 1:
                print(f"等待 {self.delay} 秒...")
                time.sleep(self.delay)
        
        return captured_files
    
    def cleanup(self):
        """清理资源"""
        print("\n正在清理资源...")
        
        if self.camera:
            self.camera.release()
        
        print("资源清理完成")
    
    def print_summary(self, captured_files):
        """打印采集总结"""
        print("\n" + "=" * 50)
        print("采集总结:")
        print("=" * 50)
        
        print(f"总采集数量: {len(captured_files)}/{self.num_images}")
        
        if captured_files:
            print("采集的图像:")
            for filepath in captured_files:
                filename = os.path.basename(filepath)
                size_kb = os.path.getsize(filepath) / 1024
                print(f"  {filename} ({size_kb:.1f} KB)")
        
        print(f"图像保存在: {self.output_dir}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='从指定摄像头采集图像')
    parser.add_argument('-c', '--camera', type=int, default=0, help='摄像头ID (默认: 0)')
    parser.add_argument('-n', '--num', type=int, default=2, help='采集图像数量 (默认: 3)')
    parser.add_argument('-d', '--delay', type=float, default=1.0, help='采集间隔(秒) (默认: 1.0)')
    parser.add_argument('-o', '--output', type=str, default='captured_images', help='输出目录 (默认: captured_images)')
    args = parser.parse_args()
    
    try:
        capturer = SpecificCameraCapture(
            camera_id=args.camera,
            num_images=args.num,
            output_dir=args.output,
            delay=args.delay
        )
        
        if not capturer.initialize_camera():
            print("摄像头初始化失败")
            return 1
        
        captured_files = capturer.capture_images()
        
        capturer.cleanup()
        
        capturer.print_summary(captured_files)
        
        return 0
        
    except Exception as e:
        print(f"程序运行出错: {e}")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())