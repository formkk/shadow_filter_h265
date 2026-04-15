#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多摄像头视频录制程序
从/dev/video0-3摄像头录制5秒视频并保存
"""

import cv2
import os
import time
from datetime import datetime
import threading

class MultiCameraRecorder:
    def __init__(self, camera_indices=None, output_dir="recorded_videos", duration=5):
        """
        初始化多摄像头录制器
        
        Args:
            camera_indices: 摄像头索引列表，默认为 [0,1,2,3]
            output_dir: 输出目录
            duration: 录制时长（秒）
        """
        self.camera_indices = camera_indices or list(range(4))
        self.output_dir = output_dir
        self.duration = duration
        self.cameras = {}
        self.writers = {}
        self.running = False
        self.record_threads = []
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        print("多摄像头视频录制程序")
        print("=" * 50)
        print(f"录制时长: {self.duration}秒")
        
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
                        
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"camera_{i}_{timestamp}.mp4"
                        filepath = os.path.join(self.output_dir, filename)
                        
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        fps = 30
                        frame_size = (frame.shape[1], frame.shape[0])
                        
                        writer = cv2.VideoWriter(filepath, fourcc, fps, frame_size)
                        if writer.isOpened():
                            self.writers[i] = {
                                'writer': writer,
                                'filepath': filepath,
                                'frame_count': 0
                            }
                            print(f"视频写入器创建成功: {filepath}")
                        else:
                            print(f"视频写入器创建失败: {filepath}")
                            cap.release()
                            self.cameras.pop(i, None)
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
    
    def record_from_camera(self, camera_id, cap, writer_info):
        """从单个摄像头录制视频的线程函数"""
        writer = writer_info['writer']
        start_time = time.time()
        frame_count = 0
        
        while self.running:
            elapsed = time.time() - start_time
            if elapsed >= self.duration:
                break
                
            try:
                ret, frame = cap.read()
                
                if ret and frame is not None:
                    writer.write(frame)
                    frame_count += 1
                    
                    if frame_count % 10 == 0:
                        remaining = self.duration - elapsed
                        print(f"摄像头 {camera_id} 已录制 {frame_count} 帧 | 剩余时间: {remaining:.1f}秒")
                else:
                    print(f"摄像头 {camera_id} 读取帧失败")
                    
            except Exception as e:
                print(f"摄像头 {camera_id} 录制异常: {e}")
                
            time.sleep(0.01)
        
        writer_info['frame_count'] = frame_count
    
    def start_recording(self):
        """开始录制视频"""
        if not self.cameras or not self.writers:
            print("没有可用的摄像头或视频写入器")
            return False
            
        print("\n开始录制视频...")
        self.running = True
        start_time = time.time()
        
        for camera_id, cap in self.cameras.items():
            if camera_id in self.writers:
                thread = threading.Thread(
                    target=self.record_from_camera,
                    args=(camera_id, cap, self.writers[camera_id])
                )
                thread.daemon = True
                thread.start()
                self.record_threads.append(thread)
        
        try:
            end_time = start_time + self.duration
            while time.time() < end_time:
                remaining = end_time - time.time()
                print(f"\r总体进度: {(self.duration - remaining) / self.duration * 100:.1f}% | 剩余: {remaining:.1f}秒", end="")
                time.sleep(0.5)
            print("\n录制完成!")
        except KeyboardInterrupt:
            print("\n用户中断，停止录制")
        
        self.running = False
        for thread in self.record_threads:
            thread.join(1.0)
        
        return True
    
    def cleanup(self):
        """清理资源"""
        print("\n正在清理资源...")
        
        for writer_info in self.writers.values():
            if writer_info['writer']:
                writer_info['writer'].release()
        
        for cap in self.cameras.values():
            if cap:
                cap.release()
        
        print("资源清理完成")
    
    def print_summary(self):
        """打印录制总结"""
        print("\n" + "=" * 50)
        print("录制总结:")
        print("=" * 50)
        
        total_frames = 0
        
        for camera_id, writer_info in self.writers.items():
            filepath = writer_info['filepath']
            frame_count = writer_info['frame_count']
            total_frames += frame_count
            
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            
            print(f"摄像头 {camera_id}:")
            print(f"  文件: {os.path.basename(filepath)}")
            print(f"  帧数: {frame_count}")
            print(f"  大小: {size_mb:.2f} MB")
            print(f"  平均帧率: {frame_count / self.duration:.1f} fps")
        
        print(f"\n总录制帧数: {total_frames}")
        print(f"视频保存在: {self.output_dir}")

def main():
    """主函数"""
    try:
        recorder = MultiCameraRecorder(
            camera_indices=[0, 1, 2, 3],
            output_dir="recorded_videos",
            duration=20
        )
        
        if not recorder.initialize_cameras():
            print("摄像头初始化失败")
            return 1
        
        recorder.start_recording()
        
        recorder.cleanup()
        
        recorder.print_summary()
        
        return 0
        
    except Exception as e:
        print(f"程序运行出错: {e}")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())