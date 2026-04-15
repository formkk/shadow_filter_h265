#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持续拍照程序
从/dev/video0-3摄像头持续拍照30秒
"""

import cv2
import os
import time
from datetime import datetime
import threading
import argparse

class ContinuousCameraCapture:
    def __init__(self, camera_indices=None, output_dir="continuous_photos", duration=30, interval=0.02):
        """
        初始化持续拍照器
        
        Args:
            camera_indices: 摄像头索引列表，默认为 [0,1,2,3]
            output_dir: 输出目录
            duration: 持续拍照时间（秒）
            interval: 拍照间隔（秒）
        """
        self.camera_indices = camera_indices or list(range(4))
        self.output_dir = output_dir
        self.duration = duration
        self.interval = interval
        self.cameras = {}
        self.running = False
        self.capture_threads = []
        self.start_time = None
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        print("持续拍照程序")
        print("=" * 50)
        print(f"持续时间: {self.duration}秒")
        print(f"拍照间隔: {self.interval}秒")
        
    def initialize_cameras(self):
        """初始化摄像头"""
        successful_cameras = []
        
        for i in self.camera_indices:
            try:
                cap = cv2.VideoCapture(i)
                
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 576)
                print(f"目标分辨率: 720x576 | 实际: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
                
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        self.cameras[i] = cap
                        successful_cameras.append(i)
                        print(f"摄像头 /dev/video{i} 初始化成功")
                    else:
                        print(f"摄像头 /dev/video{i} 无法读取帧")
                        cap.release()
                else:
                    print(f"摄像头 /dev/video{i} 无法打开")
                    cap.release()
                    
            except Exception as e:
                print(f"摄像头 /dev/video{i} 初始化失败: {e}")
                
        if successful_cameras:
            print(f"成功初始化 {len(successful_cameras)} 个摄像头: {successful_cameras}")
            return True
        else:
            print("没有可用的摄像头")
            return False
    
    def capture_from_camera(self, camera_id, cap):
        """从单个摄像头持续拍照的线程函数"""
        photo_count = 0
        
        while self.running:
            elapsed = time.time() - self.start_time
            if elapsed >= self.duration:
                break
                
            try:
                ret, frame = cap.read()
                
                if ret and frame is not None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                    
                    filename = f"camera_{camera_id}_{timestamp}.jpg"
                    filepath = os.path.join(self.output_dir, filename)
                    cv2.imwrite(filepath, frame)
                    
                    photo_count += 1
                    remaining = self.duration - elapsed
                    print(f"摄像头 {camera_id} 拍照 {photo_count} | 剩余时间: {remaining:.1f}秒")
                else:
                    print(f"摄像头 {camera_id} 拍照失败")
                    
            except Exception as e:
                print(f"摄像头 {camera_id} 拍照异常: {e}")
                
            time.sleep(self.interval)
    
    def start_capture(self):
        """开始持续拍照"""
        if not self.cameras:
            print("没有可用的摄像头")
            return False
            
        print("\n开始持续拍照...")
        self.running = True
        self.start_time = time.time()
        
        for camera_id, cap in self.cameras.items():
            thread = threading.Thread(
                target=self.capture_from_camera,
                args=(camera_id, cap)
            )
            thread.daemon = True
            thread.start()
            self.capture_threads.append(thread)
        
        try:
            end_time = self.start_time + self.duration
            while time.time() < end_time:
                remaining = end_time - time.time()
                print(f"\r总体进度: {(self.duration - remaining) / self.duration * 100:.1f}% | 剩余: {remaining:.1f}秒", end="")
                time.sleep(0.5)
            print("\n拍照完成!")
        except KeyboardInterrupt:
            print("\n用户中断，停止拍照")
        
        self.running = False
        for thread in self.capture_threads:
            thread.join(1.0)
        
        return True
    
    def cleanup(self):
        """清理资源"""
        print("\n正在清理资源...")
        
        for cap in self.cameras.values():
            if cap:
                cap.release()
        
        print("资源清理完成")
    
    def print_summary(self):
        """打印拍照总结"""
        print("\n" + "=" * 50)
        print("拍照总结:")
        print("=" * 50)
        
        camera_counts = {}
        total_photos = 0
        
        for filename in os.listdir(self.output_dir):
            if filename.startswith("camera_") and filename.endswith(".jpg"):
                try:
                    camera_id = int(filename.split("_")[1])
                    if camera_id not in camera_counts:
                        camera_counts[camera_id] = 0
                    camera_counts[camera_id] += 1
                    total_photos += 1
                except:
                    pass
        
        print(f"总拍照数量: {total_photos}")
        
        for camera_id, count in sorted(camera_counts.items()):
            print(f"摄像头 {camera_id}: {count} 张照片")
        
        print(f"照片保存在: {self.output_dir}")
        
        if self.duration > 0:
            avg_rate = total_photos / self.duration
            print(f"平均拍照频率: {avg_rate:.2f} 张/秒")

def main():
    """主函数"""
    try:
        parser = argparse.ArgumentParser(description="持续拍照采集")
        parser.add_argument("--camera_indices", type=str, default="0,1,2,3", help="摄像头索引，逗号分隔，如 0,1,2,3")
        parser.add_argument("--output_dir", type=str, default="continuous_photos", help="输出目录")
        parser.add_argument("--duration", type=float, default=30.0, help="持续拍照时间（秒）")
        parser.add_argument("--interval", type=float, default=0.01, help="拍照间隔（秒）")
        args = parser.parse_args()

        try:
            camera_indices = [int(x.strip()) for x in args.camera_indices.split(',') if x.strip() != '']
        except Exception:
            print("摄像头索引解析失败，使用默认 0-3")
            camera_indices = [0, 1, 2, 3]
        
        capturer = ContinuousCameraCapture(
            camera_indices=camera_indices,
            output_dir=args.output_dir,
            duration=args.duration,
            interval=args.interval
        )
        
        if not capturer.initialize_cameras():
            print("摄像头初始化失败")
            return 1
        
        capturer.start_capture()
        
        capturer.cleanup()
        
        capturer.print_summary()
        
        return 0
        
    except Exception as e:
        print(f"程序运行出错: {e}")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())