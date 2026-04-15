#!/usr/bin/env python3
"""
帧插值模块 - 用于提升视频输出帧率
支持线性插值和光流插值两种方法
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional
import time


class FrameInterpolator:
    """帧插值器类 - 用于在现有帧之间生成插值帧"""
    
    def __init__(self, method='linear', target_fps=30, source_fps=22):
        """
        初始化帧插值器
        
        Args:
            method: 插值方法 ('linear' 或 'optical_flow')
            target_fps: 目标帧率
            source_fps: 源帧率
        """
        self.method = method
        self.target_fps = target_fps
        self.source_fps = source_fps
        
        self.interpolation_ratio = target_fps / source_fps
        self.frames_to_insert = int(self.interpolation_ratio) - 1
        self.fractional_part = self.interpolation_ratio - int(self.interpolation_ratio)
        
        self.frame_buffer = []
        self.max_buffer_size = 3
        
        if method == 'optical_flow':
            self.flow_calculator = cv2.FarnebackOpticalFlow_create(
                numLevels=3,
                pyrScale=0.5,
                fastPyramids=False,
                winSize=13,
                numIters=10,
                polyN=5,
                polySigma=1.1,
                flags=0
            )
        
        print(f"帧插值器初始化: {source_fps}FPS -> {target_fps}FPS")
        print(f"插值比例: {self.interpolation_ratio:.2f}")
        print(f"插值方法: {method}")
    
    def add_frame(self, frame: np.ndarray, timestamp: float = None) -> List[Tuple[np.ndarray, float]]:
        """
        添加新帧并生成插值帧
        
        Args:
            frame: 输入帧
            timestamp: 帧时间戳
            
        Returns:
            插值后的帧列表 [(frame, timestamp), ...]
        """
        if timestamp is None:
            timestamp = time.time()
        
        self.frame_buffer.append((frame.copy(), timestamp))
        
        if len(self.frame_buffer) > self.max_buffer_size:
            self.frame_buffer.pop(0)
        
        if len(self.frame_buffer) >= 2:
            return self._generate_interpolated_frames()
        else:
            return [(frame, timestamp)]
    
    def _generate_interpolated_frames(self) -> List[Tuple[np.ndarray, float]]:
        """生成插值帧"""
        if len(self.frame_buffer) < 2:
            return []
        
        prev_frame, prev_timestamp = self.frame_buffer[-2]
        curr_frame, curr_timestamp = self.frame_buffer[-1]
        
        result_frames = []
        
        if len(self.frame_buffer) == 2:
            result_frames.append((prev_frame, prev_timestamp))
        
        interpolated_frames = self._interpolate_between_frames(
            prev_frame, curr_frame, prev_timestamp, curr_timestamp
        )
        result_frames.extend(interpolated_frames)
        
        result_frames.append((curr_frame, curr_timestamp))
        
        return result_frames
    
    def _interpolate_between_frames(self, frame1: np.ndarray, frame2: np.ndarray, 
                                  timestamp1: float, timestamp2: float) -> List[Tuple[np.ndarray, float]]:
        """在两帧之间生成插值帧"""
        interpolated_frames = []
        
        time_diff = timestamp2 - timestamp1
        target_interval = 1.0 / self.target_fps
        
        if time_diff < target_interval * 0.8:
            return interpolated_frames
        
        expected_total_frames = time_diff / target_interval
        num_interpolated = max(0, int(round(expected_total_frames)) - 1)
        
        num_interpolated = min(num_interpolated, 8)
        
        if num_interpolated == 0:
            return interpolated_frames
        
        for i in range(1, num_interpolated + 1):
            alpha = i / (num_interpolated + 1)
            interpolated_timestamp = timestamp1 + alpha * time_diff
            
            if self.method == 'linear':
                interpolated_frame = self._linear_interpolation(frame1, frame2, alpha)
            elif self.method == 'optical_flow':
                interpolated_frame = self._optical_flow_interpolation(frame1, frame2, alpha)
            else:
                interpolated_frame = self._linear_interpolation(frame1, frame2, alpha)
            
            interpolated_frames.append((interpolated_frame, interpolated_timestamp))
        
        return interpolated_frames
    
    def _linear_interpolation(self, frame1: np.ndarray, frame2: np.ndarray, alpha: float) -> np.ndarray:
        """线性插值"""
        interpolated = cv2.addWeighted(frame1, 1 - alpha, frame2, alpha, 0)
        return interpolated
    
    def _optical_flow_interpolation(self, frame1: np.ndarray, frame2: np.ndarray, alpha: float) -> np.ndarray:
        """基于光流的插值"""
        try:
            gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
            
            flow = cv2.calcOpticalFlowPyrLK(gray1, gray2, None, None)[0]
            
            if flow is not None:
                h, w = frame1.shape[:2]
                
                y, x = np.mgrid[0:h, 0:w].astype(np.float32)
                
                x_new = x + flow[..., 0] * alpha
                y_new = y + flow[..., 1] * alpha
                
                interpolated = cv2.remap(frame1, x_new, y_new, cv2.INTER_LINEAR)
                
                linear_interp = self._linear_interpolation(frame1, frame2, alpha)
                interpolated = cv2.addWeighted(interpolated, 0.7, linear_interp, 0.3, 0)
                
                return interpolated
            else:
                return self._linear_interpolation(frame1, frame2, alpha)
                
        except Exception as e:
            print(f"光流插值失败，回退到线性插值: {e}")
            return self._linear_interpolation(frame1, frame2, alpha)
    
    def reset(self):
        """重置插值器状态"""
        self.frame_buffer.clear()
    
    def get_stats(self) -> dict:
        """获取插值器统计信息"""
        return {
            'method': self.method,
            'source_fps': self.source_fps,
            'target_fps': self.target_fps,
            'interpolation_ratio': self.interpolation_ratio,
            'buffer_size': len(self.frame_buffer)
        }


class AdaptiveFrameInterpolator(FrameInterpolator):
    """自适应帧插值器 - 根据实际帧率动态调整插值策略"""
    
    def __init__(self, target_fps=30, window_size=10):
        """
        初始化自适应帧插值器
        
        Args:
            target_fps: 目标帧率
            window_size: 用于计算实际帧率的窗口大小
        """
        super().__init__('linear', target_fps, 22)
        
        self.target_fps = target_fps
        self.window_size = window_size
        
        self.frame_timestamps = []
        self.actual_fps = 22.0
        self.fps_update_counter = 0
        
        print(f"自适应帧插值器初始化，目标帧率: {target_fps}FPS")
    
    def add_frame(self, frame: np.ndarray, timestamp: float = None) -> List[Tuple[np.ndarray, float]]:
        """添加帧并动态调整插值策略"""
        if timestamp is None:
            timestamp = time.time()
        
        self._update_fps_monitoring(timestamp)
        
        if self.fps_update_counter % 10 == 0:
            self._update_interpolation_params()
        
        self.fps_update_counter += 1
        
        return super().add_frame(frame, timestamp)
    
    def _update_fps_monitoring(self, timestamp: float):
        """更新帧率监控"""
        self.frame_timestamps.append(timestamp)
        
        if len(self.frame_timestamps) > self.window_size:
            self.frame_timestamps.pop(0)
        
        if len(self.frame_timestamps) >= 2:
            time_span = self.frame_timestamps[-1] - self.frame_timestamps[0]
            if time_span > 0:
                self.actual_fps = (len(self.frame_timestamps) - 1) / time_span
    
    def _update_interpolation_params(self):
        """更新插值参数"""
        if abs(self.actual_fps - self.source_fps) > 1.0:
            self.source_fps = self.actual_fps
            self.interpolation_ratio = self.target_fps / self.source_fps
            
            print(f"更新插值参数: 实际帧率 {self.actual_fps:.1f}FPS -> 目标帧率 {self.target_fps}FPS")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        stats = super().get_stats()
        stats.update({
            'actual_fps': self.actual_fps,
            'fps_samples': len(self.frame_timestamps)
        })
        return stats