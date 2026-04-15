#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多摄像头图像采集程序
从/dev/video0到/dev/video3这4个摄像头各拍摄2张照片
"""

import cv2
import os
import time
from datetime import datetime
import threading

class MultiCameraCapture:
    def __init__(self, camera_ids=[0, 1, 2, 3], images_per_camera=2, output_dir="multi_camera_images", delay=1.0):
        """
        初始化多摄像头采集器
        
        Args:
            camera_ids: 摄像头ID列表，默认为[0,1,2,3]
            images_per_camera: 每个摄像头要采集的图像数量，默认为2
            output_dir: 输出目录
            delay: 每张照片之间的采集间隔（秒）
        """
        self.camera_ids = camera_ids
        self.images_per_camera = images_per_camera
        self.output_dir = output_dir
        self.delay = delay
        self.cameras = {}
        self.results = {}
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        print("多摄像头图像采集程序")
        print("=" * 50)
        print(f"摄像头IDs: {self.camera_ids}")
        print(f"每个摄像头采集数量: {self.images_per_camera}张")
        print(f"采集间隔: {self.delay}秒")
        print(f"输出目录: {self.output_dir}")
        print("=" * 50)
        
    def initialize_cameras(self):
        """初始化所有摄像头"""
        print("\n正在初始化摄像头...")
        
        for camera_id in self.camera_ids:
            try:
                camera = cv2.VideoCapture(camera_id)
                
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 576)
                
                if camera.isOpened():
                    ret, frame = camera.read()
                    if ret and frame is not None:
                        self.cameras[camera_id] = camera
                        print(f"摄像头 /dev/video{camera_id} 初始化成功")
                    else:
                        print(f"摄像头 /dev/video{camera_id} 无法读取帧")
                        camera.release()
                else:
                    print(f"摄像头 /dev/video{camera_id} 无法打开")
                    
            except Exception as e:
                print(f"摄像头 /dev/video{camera_id} 初始化失败: {e}")
        
        print(f"成功初始化 {len(self.cameras)}/{len(self.camera_ids)} 个摄像头")
        return len(self.cameras) > 0
    
    def capture_from_camera(self, camera_id):
        """从指定摄像头采集图像"""
        camera = self.cameras.get(camera_id)
        if not camera:
            print(f"摄像头 {camera_id} 未初始化")
            self.results[camera_id] = []
            return
            
        captured_files = []
        
        print(f"\n开始从摄像头 /dev/video{camera_id} 采集图像...")
        
        for _ in range(5):
            camera.read()
            time.sleep(0.1)
        
        for i in range(self.images_per_camera):
            try:
                ret, frame = camera.read()
                
                if ret and frame is not None:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    
                    filename = f"camera_{camera_id}_image_{i+1}_{timestamp}.jpg"
                    filepath = os.path.join(self.output_dir, filename)
                    cv2.imwrite(filepath, frame)
                    
                    captured_files.append(filepath)
                    print(f"摄像头 {camera_id} 图像 {i+1}/{self.images_per_camera} 采集成功: {filename}")
                else:
                    print(f"摄像头 {camera_id} 图像 {i+1}/{self.images_per_camera} 采集失败")
                    
            except Exception as e:
                print(f"摄像头 {camera_id} 图像 {i+1}/{self.images_per_camera} 采集异常: {e}")
                
            if i < self.images_per_camera - 1:
                time.sleep(self.delay)
        
        self.results[camera_id] = captured_files
    
    def capture_all_cameras(self):
        """并行从所有摄像头采集图像"""
        if not self.cameras:
            print("没有可用的摄像头")
            return {}
            
        threads = []
        
        for camera_id in self.cameras.keys():
            thread = threading.Thread(target=self.capture_from_camera, args=(camera_id,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        return self.results
    
    def cleanup(self):
        """清理资源"""
        print("\n正在清理资源...")
        
        for camera_id, camera in self.cameras.items():
            camera.release()
            print(f"摄像头 /dev/video{camera_id} 已关闭")
        
        print("资源清理完成")
    
    def print_summary(self):
        """打印采集总结"""
        print("\n" + "=" * 50)
        print("采集总结:")
        print("=" * 50)
        
        total_images = 0
        for camera_id, files in self.results.items():
            print(f"摄像头 /dev/video{camera_id}: 采集 {len(files)}/{self.images_per_camera} 张图像")
            total_images += len(files)
            
            if files:
                for filepath in files:
                    filename = os.path.basename(filepath)
                    size_kb = os.path.getsize(filepath) / 1024
                    print(f"  {filename} ({size_kb:.1f} KB)")
        
        print("-" * 50)
        print(f"总采集数量: {total_images}/{len(self.camera_ids) * self.images_per_camera}")
        print(f"图像保存在: {self.output_dir}")

def main():
    """主函数"""
    try:
        capturer = MultiCameraCapture(
            camera_ids=[0, 1, 2, 3],
            images_per_camera=2,
            output_dir="multi_camera_images",
            delay=1.0
        )
        
        if not capturer.initialize_cameras():
            print("没有可用的摄像头，程序退出")
            return 1
        
        capturer.capture_all_cameras()
        
        capturer.cleanup()
        
        capturer.print_summary()
        
        return 0
        
    except Exception as e:
        print(f"程序运行出错: {e}")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())