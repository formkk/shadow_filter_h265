#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多摄像头实时监控程序
从/dev/video0到/dev/video3捕获图像，并在屏幕上显示2x2网格的监控窗口
"""

import cv2
import time
import threading
import sys
import numpy as np

class MultiCameraMonitor:
    def __init__(self, camera_ids=[0, 1, 2, 3]):
        """
        初始化多摄像头监控器
        
        Args:
            camera_ids: 摄像头ID列表，默认为[0,1,2,3]
        """
        self.camera_ids = camera_ids
        self.cameras = {}
        self.frames = {}
        self.running = False
        self.threads = []
        
        self.window_name = "多摄像头监控 (2x2网格)"
        
        self.title = "多摄像头监控系统"
    
    def initialize_cameras(self):
        """初始化所有摄像头"""
        print("正在初始化摄像头...")
        
        for camera_id in self.camera_ids:
            try:
                camera = cv2.VideoCapture(camera_id)
                
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 576)
                
                if camera.isOpened():
                    ret, frame = camera.read()
                    if ret and frame is not None:
                        self.cameras[camera_id] = camera
                        self.frames[camera_id] = frame
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
        """从指定摄像头捕获图像的线程函数"""
        camera = self.cameras.get(camera_id)
        if not camera:
            print(f"摄像头 {camera_id} 未初始化")
            return
        
        while self.running:
            try:
                ret, frame = camera.read()
                if ret and frame is not None:
                    cv2.putText(frame, f"/dev/video{camera_id}", 
                               (10, 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 
                               1, 
                               (0, 255, 0), 
                               2)
                    self.frames[camera_id] = frame
                else:
                    error_frame = self.frames.get(camera_id, None)
                    if error_frame is not None:
                        error_frame = error_frame.copy()
                        cv2.putText(error_frame, "无法获取图像", 
                                   (10, error_frame.shape[0] - 10), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 
                                   0.7, 
                                   (0, 0, 255), 
                                   2)
                        self.frames[camera_id] = error_frame
                    time.sleep(0.1)
            except Exception as e:
                print(f"摄像头 {camera_id} 捕获异常: {e}")
                time.sleep(0.1)
    
    def create_combined_frame(self):
        """创建2x2的组合帧"""
        rows = 2
        cols = 2
        
        active_cameras = list(self.cameras.keys())
        
        if active_cameras:
            first_camera_id = active_cameras[0]
            h, w, _ = self.frames[first_camera_id].shape
        else:
            h, w = 480, 640
            
        combined_h = h * rows
        combined_w = w * cols
        combined_frame = np.zeros((combined_h, combined_w, 3), dtype="uint8")
        
        for i in range(rows):
            for j in range(cols):
                index = i * cols + j
                if index < len(active_cameras):
                    camera_id = active_cameras[index]
                    frame = self.frames[camera_id]
                    frame_resized = cv2.resize(frame, (w, h))
                    combined_frame[i*h:(i+1)*h, j*w:(j+1)*w] = frame_resized
                else:
                    placeholder = cv2.putText(
                        np.zeros((h, w, 3), dtype="uint8"),
                        "无摄像头", (w//4, h//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2
                    )
                    combined_frame[i*h:(i+1)*h, j*w:(j+1)*w] = placeholder
        
        cv2.putText(combined_frame, self.title, 
                   (combined_w//4, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 
                   1, 
                   (0, 0, 255), 
                   2)
        
        return combined_frame
    
    def start_monitoring(self):
        """开始监控"""
        if not self.initialize_cameras():
            print("没有可用的摄像头，程序退出")
            return False
        
        self.running = True
        
        for camera_id in self.cameras.keys():
            thread = threading.Thread(target=self.capture_from_camera, args=(camera_id,))
            self.threads.append(thread)
            thread.daemon = True
            thread.start()
        
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 1280, 960)
        
        print("多摄像头监控已启动")
        print("按 'q' 键退出监控")
        
        try:
            while self.running:
                combined_frame = self.create_combined_frame()
                
                cv2.imshow(self.window_name, combined_frame)
                
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    self.running = False
                    break
                
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.running = False
        
        return True
    
    def cleanup(self):
        """清理资源"""
        self.running = False
        
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        
        for camera_id, camera in self.cameras.items():
            camera.release()
            print(f"摄像头 /dev/video{camera_id} 已关闭")
        
        cv2.destroyAllWindows()
        print("资源清理完成，程序退出")


if __name__ == "__main__":
    try:
        monitor = MultiCameraMonitor(camera_ids=[0, 1, 2, 3])
        
        monitor.start_monitoring()
        
        monitor.cleanup()
    except Exception as e:
        print(f"程序运行出错: {e}")
        sys.exit(1)
    
    sys.exit(0)