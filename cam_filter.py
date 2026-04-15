import cv2
import numpy as np
import threading
import time
import sys
import argparse
import os
import csv
import signal
import subprocess
import socket
from datetime import datetime
from collections import defaultdict, deque
from queue import Queue, Empty, Full
from typing import List, Optional, Tuple

import cv2
import numpy as np
import torch
import pywt
from ultralytics.models.yolo.model import YOLO

cv2.setNumThreads(4)
if torch.cuda.is_available():
    torch.backends.cudnn.benchmark = True
    torch.backends.cudnn.deterministic = False
    dummy_tensor = torch.randn(1, 3, 224, 224).cuda()
    del dummy_tensor
    torch.cuda.empty_cache()

try:
    os.nice(-10)
except Exception:
    pass


class ONVIFServerManager:
    """管理 ONVIF Server 子进程"""
    def __init__(self, script_path="onvif_server.py"):
        self.script_path = os.path.abspath(script_path)
        self.process = None

    def start(self):
        """启动 ONVIF Server"""
        if self.process is not None and self.process.poll() is None:
            print("ONVIF Server 已经在运行")
            return

        print(f"正在启动 ONVIF Server: {self.script_path}")
        try:
            # 使用 sys.executable 确保使用相同的 python 解释器
            self.process = subprocess.Popen(
                [sys.executable, self.script_path],
                cwd=os.path.dirname(self.script_path),
                stdout=subprocess.DEVNULL, # 避免干扰主程序输出，可改为 subprocess.PIPE 并单独线程读取
                stderr=subprocess.DEVNULL
            )
            print(f"ONVIF Server 启动成功, PID: {self.process.pid}")
        except Exception as e:
            print(f"ONVIF Server 启动失败: {e}")

    def stop(self):
        """停止 ONVIF Server"""
        if self.process:
            print("正在停止 ONVIF Server...")
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except Exception as e:
                print(f"停止 ONVIF Server 异常: {e}")
            finally:
                self.process = None
                print("ONVIF Server 已停止")

# 全局管理器实例
onvif_manager = None

def signal_handler_global(sig, frame):
    """处理退出信号，确保子进程被清理"""
    print('收到退出信号，正在清理资源...')
    if onvif_manager:
        onvif_manager.stop()
    sys.exit(0)

# Register global signal handlers immediately
signal.signal(signal.SIGINT, signal_handler_global)
signal.signal(signal.SIGTERM, signal_handler_global)


def discover_onvif_devices(timeout: float = 2.0) -> List[Tuple[str, int]]:
    """
    发现局域网中的ONVIF设备
    
    简易发现：在本地网段的常见地址上尝试连接常见端口。
    
    Args:
        timeout: 端口探测超时时间（秒）
        
    Returns:
        发现的设备列表，每个元素为(IP地址, 端口)的元组
    """
    devices = []
    start = time.time()

    candidates = ["127.0.0.1", "localhost"]

    for host in candidates:
        for port in COMMON_ONVIF_PORTS:
            if _probe_port(host, port):
                devices.append((host, port))
    elapsed = time.time() - start
    print(f"ONVIF 简易发现耗时 {elapsed:.2f}s，候选数 {len(candidates)*len(COMMON_ONVIF_PORTS)}，发现 {len(devices)}")
    return devices


def register_stream_with_onvif_server(rtsp_url: str, device: Optional[Tuple[str, int]] = None) -> None:
    """
    向ONVIF服务器注册RTSP流
    
    占位：将 RTSP URL 注册到 ONVIF 服务端（实际需 SOAP/Device service 接口）。
    在此仅打印日志，后续可替换为真实 ONVIF Device/Media/PTZ 集成。
    
    Args:
        rtsp_url: RTSP流的URL地址
        device: ONVIF设备信息，格式为(IP地址, 端口)的元组，可选
        
    Returns:
        None
    """
    if device:
        host, port = device
        print(f"尝试向 ONVIF 服务器注册流: {rtsp_url} -> {host}:{port}")
    else:
        print(f"未发现 ONVIF 服务器，保留本地监听流: {rtsp_url}")


class RTSPStreamServer:
    """
    RTSP流服务器类
    
    负责管理RTSP流的推送，支持FFmpeg后端进行视频编码和流传输。
    支持帧插值、NVENC硬件编码等高级功能。
    
    Attributes:
        port: RTSP服务端口
        stream_name: 流名称
        enable_interpolation: 是否启用帧插值
        target_fps: 目标帧率
        use_nvenc: 是否使用NVENC硬件编码
    """
    
    def __init__(self, port=8554, target_fps=24,
                 publish_user: Optional[str] = None, publish_pass: Optional[str] = None,
                 read_user: Optional[str] = None, read_pass: Optional[str] = None):
        self.port = port
        # optional auth for publish/play
        self.publish_user = publish_user
        self.publish_pass = publish_pass
        self.read_user = read_user
        self.read_pass = read_pass
        self.running = False
        
        self.start_time = time.time()
        
        self.target_fps = target_fps
        
        # We now support both H264 and H265 simultaneously
        self.codecs = ['h264', 'h265']
        
        # Processes for dual encoding
        self.monitor_ffmpeg_processes = {} # {'h264': proc, 'h265': proc}
        self.filter_ffmpeg_processes = {}  # {'h264': proc, 'h265': proc}
        
        self.monitor_rtsp_urls = {
            'h264': self._format_rtsp_url("monitor_h264", for_publish=True),
            'h265': self._format_rtsp_url("monitor_h265", for_publish=True)
        }
        self.filter_rtsp_urls = {
            'h264': self._format_rtsp_url("filter_h264", for_publish=True),
            'h265': self._format_rtsp_url("filter_h265", for_publish=True)
        }

        self.monitor_restart_count = 0
        self.monitor_last_restart_time = 0
        self.monitor_max_restarts = 5
        self.monitor_restart_cooldown = 5
        self.monitor_fps_samples = deque(maxlen=120)
        self.monitor_fps_value = 0.0
        
        self.filter_restart_count = 0
        self.filter_last_restart_time = 0
        self.filter_max_restarts = 5
        self.filter_restart_cooldown = 5

    def _format_rtsp_url(self, path: str, for_publish: bool = True) -> str:
        """Build RTSP URL with optional credentials. Use publish creds for FFmpeg push."""
        user = self.publish_user if for_publish else self.read_user
        pwd = self.publish_pass if for_publish else self.read_pass
        if user and pwd:
            return f"rtsp://{user}:{pwd}@127.0.0.1:{self.port}/{path}"
        return f"rtsp://127.0.0.1:{self.port}/{path}"
        
    def get_status(self) -> dict:
        """返回当前RTSP推流的状态信息，用于心跳与监控打印"""
        try:
            monitor_alive = any(p is not None and p.poll() is None for p in self.monitor_ffmpeg_processes.values())
        except Exception:
            monitor_alive = False
        try:
            filter_alive = any(p is not None and p.poll() is None for p in self.filter_ffmpeg_processes.values())
        except Exception:
            filter_alive = False
        try:
            uptime = (time.time() - self.start_time) if hasattr(self, 'start_time') else 0.0
        except Exception:
            uptime = 0.0
        status = {
            'running': getattr(self, 'running', False),
            'monitor_alive': monitor_alive,
            'filter_alive': filter_alive,
            'uptime_sec': uptime,
            'monitor_restarts': self.monitor_restart_count,
            'filter_restarts': self.filter_restart_count,
        }
        return status
    
    def stop_stream(self):
        """停止RTSP推流"""
        self.running = False
        
        if hasattr(self, 'start_time'):
            uptime = time.time() - self.start_time
            print(f"[RTSP停止] 总运行时间: {uptime:.1f}s")

        for codec, process in self.monitor_ffmpeg_processes.items():
            if process:
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    print(f"监控流FFmpeg进程({codec})已停止")
                except Exception as e:
                    print(f"停止监控流FFmpeg进程({codec})异常: {e}")
        self.monitor_ffmpeg_processes.clear()
        
        for codec, process in self.filter_ffmpeg_processes.items():
            if process:
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    print(f"筛选流FFmpeg进程({codec})已停止")
                except Exception as e:
                    print(f"停止筛选流FFmpeg进程({codec})异常: {e}")
        self.filter_ffmpeg_processes.clear()

    def create_monitor_frame(self, camera_frames: List[np.ndarray], filtered_frame: Optional[np.ndarray] = None, 
                           frame_metadata: Optional[dict] = None, camera_metadata: Optional[List[dict]] = None) -> np.ndarray:
        """
        创建监控帧，包含上部4个摄像头画面和下部筛选帧，以及延迟信息和时间戳
        
        Args:
            camera_frames: 4个摄像头的原始帧列表
            filtered_frame: 筛选后的帧（可选）
            frame_metadata: 帧元数据，包含延迟信息
            camera_metadata: 摄像头元数据列表，包含时间戳信息
            
        Returns:
            合成的监控帧 (720x720)
        """
        monitor_frame = np.zeros((720, 720, 3), dtype=np.uint8)
        
        for i, frame in enumerate(camera_frames[:4]):
            if frame is not None:
                resized_frame = cv2.resize(frame, (180, 144))
                x_offset = i * 180
                monitor_frame[0:144, x_offset:x_offset+180] = resized_frame
            else:
                x_offset = i * 180
                monitor_frame[0:144, x_offset:x_offset+180] = 0
        
        if filtered_frame is not None:
            if filtered_frame.shape[:2] != (576, 720):
                filtered_frame = cv2.resize(filtered_frame, (720, 576))
            monitor_frame[144:720, 0:720] = filtered_frame
        else:
            monitor_frame[144:720, 0:720] = 0
        
        if frame_metadata:
            ai_ms = None
            proc_time = frame_metadata.get('processing_time')
            if proc_time is not None:
                ai_ms = max(0.0, proc_time * 1000.0)
            
            latency_ms = None
            pre_ms = frame_metadata.get('pipeline_latency_ms')
            if pre_ms is not None and 0 <= pre_ms <= 2000:
                latency_ms = pre_ms
            
            lines = []
            if ai_ms is not None:
                ai_color = (0, 255, 0) if ai_ms < 30 else ((0, 255, 255) if ai_ms < 60 else (0, 0, 255))
                lines.append((f"AI Latency: {ai_ms:6.1f}ms", ai_color))
            
            if latency_ms is not None:
                latency_color = (0, 255, 0) if latency_ms < 50 else ((0, 255, 255) if latency_ms < 100 else (0, 0, 255))
                lines.append((f"Pipeline Latency: {latency_ms:6.1f}ms", latency_color))
            
            if lines:
                max_w = 0
                total_h = 0
                text_sizes = []
                for text, _ in lines:
                    size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                    text_sizes.append(size)
                    max_w = max(max_w, size[0])
                    total_h += size[1] + 10
                
                base_y = monitor_frame.shape[0] - total_h - 10
                
                cv2.rectangle(monitor_frame, (10, base_y), (10 + max_w + 14, base_y + total_h + 6), (0, 0, 0), -1)
                
                y = base_y + 20
                for i, (text, color) in enumerate(lines):
                    text_x = 10 + max_w - text_sizes[i][0] + 7
                    cv2.putText(monitor_frame, text, (text_x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    y += 22
        
            
        return monitor_frame

    def start_filter_stream(self, fps: int = 24) -> bool:
        """启动筛选流推送 (ONVIF兼容) - 双编码"""
        try:
            try:
                from mediamtx_manager import MediaMTXManager
                mtx = MediaMTXManager(listen_addr="0.0.0.0", rtsp_port=self.port)
                mtx.ensure_running(wait_seconds=2.0)
            except Exception as e:
                print(f"启动/检测 MediaMTX 异常: {e}")
            
            success = False
            for codec in self.codecs:
                if codec in self.filter_ffmpeg_processes and self.filter_ffmpeg_processes[codec].poll() is None:
                    continue
                
                rtsp_url = self.filter_rtsp_urls[codec]
                
                if codec == 'h264':
                    ffmpeg_cmd_filter = [
                        'ffmpeg',
                        '-y',
                        '-f', 'rawvideo',
                        '-vcodec', 'rawvideo',
                        '-pix_fmt', 'bgr24',
                        '-s', '720x576',
                        '-r', str(fps),
                        '-i', '-',
                        '-c:v', 'libx264',
                        '-preset', 'ultrafast',
                        '-tune', 'zerolatency',
                        '-crf', '23',
                        '-x264-params', f'keyint={fps}:min-keyint={fps}:scenecut=0:bframes=0:no-mbtree=1',
                        '-maxrate', '2M',
                        '-bufsize', '4M',
                        '-g', str(fps),
                        '-pix_fmt', 'yuv420p',
                        '-bf', '0',
                        '-force_key_frames', 'expr:gte(t,n_forced*1)',
                        '-rtsp_transport', 'tcp',
                        '-rtsp_flags', 'prefer_tcp',
                        '-fflags', 'nobuffer+flush_packets+genpts',
                        '-flags', 'low_delay',
                        '-vsync', 'cfr',
                        '-f', 'rtsp',
                        rtsp_url
                    ]
                else:
                    ffmpeg_cmd_filter = [
                        'ffmpeg',
                        '-y',
                        '-f', 'rawvideo',
                        '-vcodec', 'rawvideo',
                        '-pix_fmt', 'bgr24',
                        '-s', '720x576',
                        '-r', str(fps),
                        '-i', '-',
                        '-c:v', 'libx265',
                        '-preset', 'ultrafast',
                        '-tune', 'zerolatency',
                        '-crf', '28',
                        '-x265-params', f'keyint={fps}:min-keyint={fps}:bframes=0:no-info=1',
                        '-maxrate', '2M',
                        '-bufsize', '4M',
                        '-g', str(fps),
                        '-pix_fmt', 'yuv420p',
                        '-bf', '0',
                        '-force_key_frames', 'expr:gte(t,n_forced*1)',
                        '-rtsp_transport', 'tcp',
                        '-rtsp_flags', 'prefer_tcp',
                        '-fflags', 'nobuffer+flush_packets+genpts',
                        '-flags', 'low_delay',
                        '-vsync', 'cfr',
                        '-f', 'rtsp',
                        rtsp_url
                    ]
                
                print(f"启动筛选流FFmpeg推送({codec}): {rtsp_url}")
                process = subprocess.Popen(
                    ffmpeg_cmd_filter,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=0
                )
                
                try:
                    os.set_blocking(process.stdin.fileno(), False)
                except Exception:
                    pass
                
                self.filter_ffmpeg_processes[codec] = process
                success = True
            
            time.sleep(1.0)
            
            if success:
                # We do not register with ONVIF server here anymore, as ONVIF servers are managed centrally
                self.running = True
                return True
            else:
                print("筛选流FFmpeg进程启动失败(所有codec)")
                return False
                
        except Exception as e:
            print(f"启动筛选流异常: {e}")
            return False

    def start_monitor_stream(self, fps: int = 24) -> bool:
        """启动监控流推送 - 双编码"""
        try:
            try:
                from mediamtx_manager import MediaMTXManager
                mtx = MediaMTXManager(listen_addr="0.0.0.0", rtsp_port=self.port)
                mtx.ensure_running(wait_seconds=2.0)
            except Exception as e:
                print(f"启动/检测 MediaMTX 异常: {e}")
            
            success = False
            for codec in self.codecs:
                if codec in self.monitor_ffmpeg_processes and self.monitor_ffmpeg_processes[codec].poll() is None:
                    continue
                    
                rtsp_url = self.monitor_rtsp_urls[codec]
                
                # Monitor stream is 720x720 (2x2 grid of 360x288? No, 180x144*4=720x144? Wait.)
                # create_monitor_frame makes 720x720. 
                # We should use 720x720 to avoid distortion.
                
                if codec == 'h264':
                    ffmpeg_cmd_monitor = [
                        'ffmpeg',
                        '-y',
                        '-f', 'rawvideo',
                        '-vcodec', 'rawvideo',
                        '-pix_fmt', 'bgr24',
                        '-s', '720x720',
                        '-r', str(fps),
                        '-i', '-',
                        '-c:v', 'libx264',
                        '-preset', 'ultrafast',
                        '-tune', 'zerolatency',
                        '-crf', '23',
                        '-x264-params', f'keyint={fps}:min-keyint={fps}:scenecut=0:bframes=0:no-mbtree=1',
                        '-maxrate', '2M',
                        '-bufsize', '4M',
                        '-g', str(fps),
                        '-pix_fmt', 'yuv420p',
                        '-bf', '0',
                        '-force_key_frames', 'expr:gte(t,n_forced*1)',
                        '-rtsp_transport', 'tcp',
                        '-rtsp_flags', 'prefer_tcp',
                        '-fflags', 'nobuffer+flush_packets+genpts',
                        '-flags', 'low_delay',
                        '-vsync', 'cfr',
                        '-f', 'rtsp',
                        rtsp_url
                    ]
                else:
                    ffmpeg_cmd_monitor = [
                        'ffmpeg',
                        '-y',
                        '-f', 'rawvideo',
                        '-vcodec', 'rawvideo',
                        '-pix_fmt', 'bgr24',
                        '-s', '720x720',
                        '-r', str(fps),
                        '-i', '-',
                        '-c:v', 'libx265',
                        '-preset', 'ultrafast',
                        '-tune', 'zerolatency',
                        '-crf', '28',
                        '-x265-params', f'keyint={fps}:min-keyint={fps}:bframes=0:no-info=1',
                        '-maxrate', '2M',
                        '-bufsize', '4M',
                        '-g', str(fps),
                        '-pix_fmt', 'yuv420p',
                        '-bf', '0',
                        '-force_key_frames', 'expr:gte(t,n_forced*1)',
                        '-rtsp_transport', 'tcp',
                        '-rtsp_flags', 'prefer_tcp',
                        '-fflags', 'nobuffer+flush_packets+genpts',
                        '-flags', 'low_delay',
                        '-vsync', 'cfr',
                        '-f', 'rtsp',
                        rtsp_url
                    ]
                
                print(f"启动监控流推送到({codec}): {rtsp_url}")
                # print(f"监控流FFmpeg命令: {' '.join(ffmpeg_cmd_monitor)}")
                
                process = subprocess.Popen(
                    ffmpeg_cmd_monitor,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    bufsize=0
                )
                
                try:
                    os.set_blocking(process.stdin.fileno(), False)
                except Exception:
                    pass
                
                self.monitor_ffmpeg_processes[codec] = process
                success = True
            
            time.sleep(0.5)
            
            if success:
                print("监控流启动成功(双编码)")
                self.running = True
                return True
            else:
                print("监控流FFmpeg 启动失败(所有codec)")
                return False
            
        except Exception as e:
            print(f"启动监控流失败: {e}")
            return False

    def write_filter_frame(self, filtered_frame: np.ndarray) -> bool:
        """写入筛选帧到filter流（包含自动恢复） - 多编码广播"""
        # Check restart logic only once per call, simplistic approach
        try:
            any_alive = any(p is not None and p.poll() is None for p in self.filter_ffmpeg_processes.values())
            if not any_alive:
                 now = time.monotonic()
                 if now - self.filter_last_restart_time >= self.filter_restart_cooldown and self.filter_restart_count < self.filter_max_restarts:
                     print("检测到筛选流FFmpeg未运行，尝试重启...")
                     self.filter_last_restart_time = now
                     self.filter_restart_count += 1
                     self.start_filter_stream(fps=self.target_fps)
        except Exception:
             pass

        try:
            if filtered_frame.shape[:2] != (576, 720):
                filtered_frame = cv2.resize(filtered_frame, (720, 576))
            
            frame_with_timestamp = filtered_frame.copy()
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            color = (255, 255, 255)
            thickness = 1
            
            text_size = cv2.getTextSize(current_time, font, font_scale, thickness)[0]
            
            margin = 10
            text_x = margin
            text_y = text_size[1] + margin
            
            cv2.putText(frame_with_timestamp, current_time, (text_x, text_y), font, font_scale, color, thickness)
            
            data = frame_with_timestamp.tobytes()
            mv = memoryview(data)
            total = len(mv)
            
            # Broadcast to all active encoders
            success_any = False
            for codec, process in self.filter_ffmpeg_processes.items():
                if not process or process.poll() is not None:
                    continue
                    
                sent = 0
                start_ts = time.monotonic()
                max_spin_ms = 12.0
                chunk_size = 32768
                try:
                    while sent < total:
                        try:
                            end = min(sent + chunk_size, total)
                            n = process.stdin.write(mv[sent:end])
                            if not n:
                                if (time.monotonic() - start_ts) * 1000 >= max_spin_ms:
                                    raise BlockingIOError("write timeout budget exceeded")
                                time.sleep(0.0005)
                                continue
                            sent += n
                        except BlockingIOError:
                            if (time.monotonic() - start_ts) * 1000 >= max_spin_ms:
                                raise
                            time.sleep(0.0005)
                            continue
                    success_any = True
                except (BlockingIOError, BrokenPipeError, IOError):
                     # Silent fail for individual stream to avoid spam
                     pass
                except Exception:
                     pass
            
            return success_any

        except Exception as e:
            # print(f"写入筛选帧失败: {e}")
            return False
    
    def write_monitor_frame(self, monitor_frame: np.ndarray) -> bool:
        """写入监控帧到RTSP流（包含自动恢复） - 多编码广播"""
        try:
            # Check if any codec is dead or missing
            missing_or_dead = False
            for codec in self.codecs:
                proc = self.monitor_ffmpeg_processes.get(codec)
                if proc is None or proc.poll() is not None:
                    missing_or_dead = True
                    break

            if missing_or_dead:
                now = time.monotonic()
                if now - self.monitor_last_restart_time >= self.monitor_restart_cooldown and self.monitor_restart_count < self.monitor_max_restarts:
                    print("检测到监控流部分FFmpeg未运行，尝试重启缺失的进程...")
                    self.monitor_last_restart_time = now
                    self.monitor_restart_count += 1
                    self.start_monitor_stream(fps=self.target_fps)
        except Exception:
            pass
        
        try:
            # Ensure 720x720 for monitor stream
            if monitor_frame.shape[:2] != (720, 720):
                monitor_frame = cv2.resize(monitor_frame, (720, 720))

            try:
                now_m = time.monotonic()
                self.monitor_fps_samples.append(now_m)
                if len(self.monitor_fps_samples) >= 2:
                    dt = self.monitor_fps_samples[-1] - self.monitor_fps_samples[0]
                    if dt > 0:
                        self.monitor_fps_value = (len(self.monitor_fps_samples) - 1) / dt
            except Exception:
                pass

            ts_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            fps_str = f"ENC FPS: {self.monitor_fps_value:4.1f}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            margin = 10
            color = (255, 255, 255)
            ts_size = cv2.getTextSize(ts_str, font, font_scale, thickness)[0]
            fps_size = cv2.getTextSize(fps_str, font, font_scale, thickness)[0]
            max_w = max(ts_size[0], fps_size[0])
            total_h = ts_size[1] + fps_size[1] + 10
            base_x = monitor_frame.shape[1] - max_w - margin
            base_y = monitor_frame.shape[0] - margin
            cv2.rectangle(
                monitor_frame,
                (base_x - 5, base_y - total_h - 5),
                (base_x + max_w + 5, base_y + 5),
                (0, 0, 0),
                -1
            )
            y_fps = base_y - ts_size[1] - 5
            cv2.putText(monitor_frame, fps_str, (base_x, y_fps), font, font_scale, color, thickness)
            cv2.putText(monitor_frame, ts_str, (base_x, base_y), font, font_scale, color, thickness)
            
            data = monitor_frame.tobytes()
            mv = memoryview(data)
            total = len(mv)
            
            success_any = False
            for codec, process in self.monitor_ffmpeg_processes.items():
                if not process or process.poll() is not None:
                    continue
                
                try:
                    sent = 0
                    while sent < total:
                        n = process.stdin.write(mv[sent:])
                        if not n or n <= 0:
                            time.sleep(0.0005)
                            continue
                        sent += n
                    try:
                        process.stdin.flush()
                    except Exception:
                        pass
                    success_any = True
                except (BrokenPipeError, IOError):
                    pass
                except Exception:
                    pass
            
            return success_any
            
        except Exception as e:
            # print(f"写入监控帧失败: {e}")
            return False


class OptimizedMemoryFrameProcessor:
    """优化的内存帧处理器 - 支持内存池和批处理"""
    
    __slots__ = ['model', 'imgsz', '_tile_pool', '_pool_size', '_pool_index',
                 '_predictor_initialized', 'confidence_threshold', '_batch_size']
    
    def __init__(self, model_path='./best.pt', imgsz=224, confidence_threshold=0.7, batch_size=16):
        """初始化优化的内存帧处理器
        
        Args:
            model_path (str): YOLO模型文件路径，默认为'./best.pt'
            imgsz (int): 输入图像尺寸，默认为224
            confidence_threshold (float): 置信度阈值，默认为0.5
            batch_size (int): 批处理大小，默认为16
        """
        self.imgsz = imgsz
        self.model = None
        self._predictor_initialized = False
        self.confidence_threshold = confidence_threshold
        self._batch_size = batch_size
        
        self._pool_size = 50
        self._tile_pool = []
        self._pool_index = 0
        
        for _ in range(self._pool_size):
            self._tile_pool.append(np.zeros((imgsz, imgsz, 3), dtype=np.uint8))
        
        self._load_model(model_path)
        
    def _load_model(self, model_path):
        """加载YOLO模型并初始化预测器
        
        Args:
            model_path (str): YOLO模型文件路径
        """
        if os.path.exists(model_path):
            try:
                self.model = YOLO(model_path)
                self._initialize_predictor()
            except Exception as e:
                print(f"加载模型失败: {e}")
                self.model = None
        else:
            print(f"模型文件不存在: {model_path}")
            self.model = None
    
    def _initialize_predictor(self):
        """预初始化YOLO预测器"""
        if self.model and not self._predictor_initialized:
            try:
                test_image = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
                _ = self.model.predict(test_image, verbose=False, save=False)
                self._predictor_initialized = True
                print("预测器初始化成功")
            except Exception as e:
                print(f"预测器初始化失败: {e}")
                pass
    
    def _extract_tiles_zero_copy(self, image_array):
        """零拷贝图像分割 - 使用内存池
        
        Args:
            image_array (np.ndarray): 输入图像数组
            
        Returns:
            list: 分割后的图像块列表
        """
        try:
            if image_array is None:
                print("错误: 图像数组为None")
                return []
            
            if isinstance(image_array, str):
                print(f"错误: 接收到字符串而不是图像数组: {image_array}")
                return []
            
            if not isinstance(image_array, np.ndarray):
                print(f"错误: 图像数组类型不正确: {type(image_array)}")
                return []
            
            if len(image_array.shape) != 3:
                print(f"错误: 图像数组维度不正确: {image_array.shape}")
                return []
            
            h, w, _ = image_array.shape
            nh = int(np.ceil(h / self.imgsz) * self.imgsz)
            nw = int(np.ceil(w / self.imgsz) * self.imgsz)
            
            resized_image = cv2.resize(image_array, (nw, nh))
            
            gh = nh // self.imgsz
            gw = nw // self.imgsz
            
            tiles = []
            for i in range(gh):
                for j in range(gw):
                    tile_buffer = self._tile_pool[self._pool_index % self._pool_size]
                    self._pool_index += 1
                    
                    tile_buffer[:] = resized_image[i*self.imgsz:(i+1)*self.imgsz, 
                                                 j*self.imgsz:(j+1)*self.imgsz]
                    tiles.append(tile_buffer)
            
            return tiles
        except Exception as e:
            print(f"Tile提取失败: {e}")
            return []
    
    def _batch_predict_optimized(self, tiles):
        """优化的批量预测 - 动态批处理大小"""
        if not tiles:
            return []
        
        if not self.model.predictor:
            self.model.predictor = self.model._smart_load("predictor")(
                overrides={"conf": 0.25, "batch": 1, "save": False, "imgsz": self.imgsz},
                _callbacks=self.model.callbacks
            )
            self.model.predictor.setup_model(model=self.model.model, verbose=False)
        
        batch_size = min(len(tiles), self._batch_size)
        
        results = []
        for i in range(0, len(tiles), batch_size):
            batch = tiles[i:i+batch_size]
            
            try:
                batch_results = self.model.predictor(source=batch, stream=False)
                results.extend(batch_results)
            except Exception as e:
                print(f"批量预测时出错: {e}")
                for tile in batch:
                    try:
                        result = self.model.predictor(source=[tile], stream=False)
                        if result is not None:
                            results.extend(result)
                    except Exception as tile_error:
                        print(f"单个图像块预测失败: {tile_error}")
                        continue
        
        return results

    def process_single_frame_array(self, image_array: np.ndarray) -> Tuple[str, float]:
        """处理单个图像帧数组 - 优化版本"""
        if self.model is None:
            print("模型未加载，无法进行预测")
            return False, []
        
        try:
            tiles = self._extract_tiles_zero_copy(image_array)
            
            results = self._batch_predict_optimized(tiles)
            
            pred_labels = []
            pred_confidences = []
            
            if results is not None:
                for result in results:
                    if hasattr(result, 'probs') and result.probs is not None:
                        top1_class = result.probs.top1
                        top1_confidence = result.probs.top1conf.item()
                        
                        if top1_confidence >= self.confidence_threshold:
                            pred_labels.append(top1_class)
                            pred_confidences.append(top1_confidence)
            
            if not pred_labels:
                pred_labels = [0]
                pred_confidences = [0.0]
            
            flag = False if 0 in pred_labels else True
            return flag, pred_labels
                
        except Exception as e:
            print(f"处理图像时出错: {e}")
            return False, []
    
    def cross_camera_batch_processing(self, all_frames):
        """跨摄像头批量处理 - 提高GPU利用率"""
        all_tiles = []
        frame_tile_mapping = {}
        
        for device_id, frame in all_frames.items():
            tiles = self._extract_tiles_zero_copy(frame)
            start_idx = len(all_tiles)
            all_tiles.extend(tiles)
            frame_tile_mapping[device_id] = (start_idx, len(tiles))
        
        all_results = self._batch_predict_optimized(all_tiles)
        
        processed_results = {}
        for device_id, (start_idx, tile_count) in frame_tile_mapping.items():
            device_results = all_results[start_idx:start_idx+tile_count]
            processed_results[device_id] = self._analyze_results(device_results)
        
        return processed_results
    
    def _analyze_results(self, results):
        """分析预测结果（与原版一致的判定规则）"""
        pred_labels = []
        pred_confidences = []
        
        if results is not None:
            for result in results:
                if hasattr(result, 'probs') and result.probs is not None:
                    top1_class = result.probs.top1
                    top1_confidence = result.probs.top1conf.item()
                    
                    if top1_confidence >= self.confidence_threshold:
                        pred_labels.append(top1_class)
                        pred_confidences.append(top1_confidence)
        
        if not pred_labels:
            pred_labels = [0]
            pred_confidences = [0.0]
        
        flag = False if 0 in pred_labels else True
        return flag, pred_labels


class AsyncCameraCapture:
    """异步摄像头捕获类 - 支持多线程并行处理"""
    
    def __init__(self, device_id, frame_queue, stats_dict, buffer_size=10):
        self.device_id = device_id
        self.frame_queue = frame_queue
        self.stats_dict = stats_dict
        self.buffer_size = buffer_size
        
        self.frame_buffer = Queue(maxsize=buffer_size)
        self.latest_frame = None
        self.latest_timestamp = 0
        self.latest_wall_clock = 0
        self.frame_lock = threading.Lock()
        
        self.cap = None
        self.capture_thread = None
        self.running = False
        
        self.capture_count = 0
        self.last_capture_time = time.monotonic()

    def start(self):
        """启动摄像头捕获"""
        try:
            try:
                self.cap = cv2.VideoCapture(self.device_id, cv2.CAP_V4L2)
            except Exception:
                self.cap = cv2.VideoCapture(self.device_id)
            if not self.cap or not self.cap.isOpened():
                print(f"无法打开摄像头 {self.device_id}")
                return False
            
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            try:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 576)
                self.cap.set(cv2.CAP_PROP_FPS, 24)
            except Exception:
                pass
            
            warm_ok = False
            for _ in range(10):
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    warm_ok = True
                    break
                time.sleep(0.05)
            if not warm_ok:
                print(f"摄像头 {self.device_id} 预读失败，未获得有效帧")
                try:
                    self.cap.release()
                except Exception:
                    pass
                return False
            
            self.running = True
            self.capture_thread = threading.Thread(target=self._async_capture_loop, daemon=True)
            self.capture_thread.start()
            print(f"摄像头 {self.device_id} 启动成功")
            return True
        except Exception as e:
            print(f"启动摄像头 {self.device_id} 失败: {e}")
            return False

    def _async_capture_loop(self):
        """异步捕获循环 - 高性能版本"""
        while self.running:
            try:
                ret, frame = self.cap.read()
                if ret:
                    current_time = time.monotonic()
                    
                    self.capture_count += 1
                    if current_time - self.last_capture_time >= 1.0:
                        capture_rate = self.capture_count / (current_time - self.last_capture_time)
                        try:
                            self.stats_dict[self.device_id]['capture_rate'] = capture_rate
                        except Exception:
                            pass
                        self.last_capture_time = current_time
                        self.capture_count = 0
                    
                    with self.frame_lock:
                        self.latest_frame = frame.copy()
                        self.latest_timestamp = current_time
                        self.latest_wall_clock = time.time()
                    
                    try:
                        self.frame_buffer.put_nowait((self.device_id, frame, current_time))
                    except Exception:
                        pass
                else:
                    try:
                        self.stats_dict[self.device_id]['failed_reads'] = self.stats_dict[self.device_id].get('failed_reads', 0) + 1
                    except Exception:
                        pass
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.005)

    def get_latest_frame(self):
        """获取最新帧，返回 dict 包含 frame 与 capture_timestamp"""
        with self.frame_lock:
            if self.latest_frame is not None:
                return {
                    'frame': self.latest_frame.copy(),
                    'capture_timestamp': self.latest_timestamp,
                    'capture_wall_clock': self.latest_wall_clock,
                }
        return None

    def stop(self):
        """停止摄像头采集，释放资源"""
        self.running = False
        try:
            if self.capture_thread:
                self.capture_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass

class AsyncVideoWriter:
    def __init__(self, filename, fourcc, fps, frame_size, buffer_size=200):
        self.filename = filename
        self.fourcc = fourcc
        self.fps = fps
        self.frame_size = frame_size
        self.buffer_size = buffer_size
        self.queue = deque(maxlen=buffer_size)
        self.writer = None
        self.running = False
        self.thread = None
        self.frames_written = 0
        self.frames_dropped = 0
        self._lock = threading.Lock()

    def start(self):
        try:
            self.writer = cv2.VideoWriter(self.filename, self.fourcc, self.fps, self.frame_size)
            if not self.writer or not self.writer.isOpened():
                return False
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return True
        except Exception:
            return False

    def _run(self):
        while self.running:
            frame = None
            with self._lock:
                if self.queue:
                    frame = self.queue.popleft()
            if frame is not None:
                try:
                    self.writer.write(frame)
                    self.frames_written += 1
                except Exception:
                    self.frames_dropped += 1
            else:
                time.sleep(0.002)

    def write_frame_async(self, frame):
        with self._lock:
            if len(self.queue) >= self.buffer_size:
                self.frames_dropped += 1
                return False
            self.queue.append(frame)
            return True

    def get_stats(self):
        with self._lock:
            return {
                'frames_written': self.frames_written,
                'frames_dropped': self.frames_dropped,
                'queue_size': len(self.queue)
            }

    def stop(self):
        self.running = False
        try:
            if self.thread:
                self.thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.writer:
                self.writer.release()
        except Exception:
            pass


class SyncFrameProcessor:
    """同步帧处理器 - 支持多摄像头实时处理
    
    该类负责协调多个摄像头的帧采集、AI推理处理、结果保存和RTSP流推送。
    支持异步处理、批量推理、帧插值和实时监控等高级功能。
    
    Attributes:
        camera_devices (list): 摄像头设备路径列表
        model_path (str): YOLO模型文件路径
        output_dir (str): 输出目录路径
        confidence_threshold (float): AI推理置信度阈值
        enable_rtsp (bool): 是否启用RTSP流推送
        rtsp_server (RTSPStreamServer): RTSP服务器实例
    """
    def __init__(self, model_path='./best.pt', output_dir='combined_videos',
                 confidence_threshold=0.7, enable_rtsp=False, rtsp_port=8554,
                 target_fps=24,
                 max_workers=4, batch_size=16, stream_protocol="onvif",
                 gb28181_ip="127.0.0.1", gb28181_port=None,
                 rtsp_listen_addr="127.0.0.1", enable_overlay=True,
                 overlay_detail_mode="full", enable_save=False, enable_denoise=True, denoise_method="median",
                 enable_temporal_brightness=True, temporal_target=85.0, temporal_alpha=0.01,
                 public_ip=None, public_rtsp_port=None, public_onvif_monitor_port=None, public_onvif_filter_port=None):
        self.camera_devices = ['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3']
        self.model_path = model_path
        self.output_dir = output_dir
        self.confidence_threshold = confidence_threshold
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.enable_overlay = enable_overlay
        self.overlay_detail_mode = overlay_detail_mode
        self.enable_denoise = enable_denoise
        self.denoise_method = denoise_method
        
        # Temporal brightness stabilization
        self.enable_temporal_brightness = enable_temporal_brightness
        self.temporal_target = temporal_target
        self.temporal_alpha = temporal_alpha
        self.brightness_gain_tracker = 1.0

        # Public Access Configuration (NAT/FRP)
        self.public_ip = public_ip
        self.public_rtsp_port = public_rtsp_port
        self.public_onvif_monitor_port = public_onvif_monitor_port
        self.public_onvif_filter_port = public_onvif_filter_port

        self.enable_rtsp = enable_rtsp
        self.rtsp_server = None
        if enable_rtsp or enable_save:
            # 传递默认推流账号与读取账号，避免服务器拒绝（与 mediamtx.yml 保持一致）
            self.rtsp_server = RTSPStreamServer(
                rtsp_port,
                target_fps,
                publish_user=os.environ.get('RTSP_PUBLISH_USER', 'shadow'),
                publish_pass=os.environ.get('RTSP_PUBLISH_PASS', 'password147'),
                read_user=os.environ.get('RTSP_READ_USER', 'shadow'),
                read_pass=os.environ.get('RTSP_READ_PASS', 'password147')
            )

        os.makedirs(output_dir, exist_ok=True)

        self.logs_dir = os.path.join(os.getcwd(), 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

        self.latency_log_path = os.path.join(self.logs_dir, 'pipeline_latency_log.csv')
        if not os.path.exists(self.latency_log_path):
            try:
                with open(self.latency_log_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['timestamp', 'cycle', 'mean_ms', 'p95_ms', 'max_ms', 'avg_ai_ms'])
            except Exception:
                pass

        self.frame_processor = OptimizedMemoryFrameProcessor(
            model_path,
            confidence_threshold=confidence_threshold,
            batch_size=batch_size
        )

        self.async_cameras = {}
        self.async_video_writers = {}
        self.enable_save = enable_save

        self.stats = defaultdict(lambda: {
            'captured_frames': 0,
            'processed_frames': 0,
            'selected_frames': 0,
            'dropped_frames': 0,
            'saved_frames': 0,
            'streamed_frames': 0,
        })

        self.global_stats = {
            'total_captured': 0,
            'total_processed': 0,
            'total_selected': 0,
            'total_saved': 0,
            'total_streamed': 0,
            'total_cycles': 0,
            'start_time': 0,
            'running_time': 0,
        }

        self.running = False
        self.start_time = None
        self.process_thread = None

        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')
        self.fps = 24
        self.frame_size = (720, 576)

        self.cycle_count = 0

        self.max_stream_latency_ms = 500

        self.pipeline_latency_window = 1000

        self.performance_monitor = {
            'frame_processing_times': [],
            'total_cycle_times': [],
            'pipeline_latency_samples': deque(maxlen=self.pipeline_latency_window),
            'e2e_capture_to_display_samples': [],
            'e2e_send_to_display_samples': []
        }

        self.last_stream_capture_ts = {}

        self.rtsp_send_ts_queue = deque(maxlen=2000)
        self.last_e2e_latency_ms = None
        self.rtsp_monitor_thread = None
        self._rtsp_monitor_running = False
        
        self.last_filtered_frame = None
        self.last_filtered_metadata = None

    def _initialize_async_cameras(self):
        success_count = 0
        for device in self.camera_devices:
            camera = AsyncCameraCapture(device, None, self.stats, buffer_size=20)
            if camera.start():
                self.async_cameras[device] = camera
                success_count += 1
                print(f"异步摄像头 {device} 初始化成功")
            else:
                print(f"异步摄像头 {device} 初始化失败")
        if success_count == 0:
            print("错误：没有摄像头初始化成功")
            return False
        print(f"成功初始化 {success_count}/{len(self.camera_devices)} 个异步摄像头")
        return True

    def _initialize_async_video_writers(self):
        if not self.enable_save:
            self.async_video_writers = {}
            return False
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        writers_started = 0

        # Monitor stream writer (720x720)
        monitor_filename = os.path.join(self.output_dir, f'monitor_{timestamp}.avi')
        monitor_writer = AsyncVideoWriter(monitor_filename, self.fourcc, self.fps, (720, 720), buffer_size=200)
        if monitor_writer.start():
            self.async_video_writers['monitor'] = monitor_writer
            print(f"Monitor 视频写入器启动: {monitor_filename}")
            writers_started += 1
        else:
            print(f"Monitor 视频写入器启动失败: {monitor_filename}")

        # Filter stream writer (720x576)
        filter_filename = os.path.join(self.output_dir, f'filter_{timestamp}.avi')
        filter_writer = AsyncVideoWriter(filter_filename, self.fourcc, self.fps, (720, 576), buffer_size=200)
        if filter_writer.start():
            self.async_video_writers['filter'] = filter_writer
            print(f"Filter 视频写入器启动: {filter_filename}")
            writers_started += 1
        else:
            print(f"Filter 视频写入器启动失败: {filter_filename}")

        return writers_started > 0

    def start_processing(self):
        """启动多摄像头处理系统
        
        初始化异步摄像头、视频写入器和RTSP服务器，然后开始主处理循环。
        
        Returns:
            bool: 启动成功返回True，失败返回False
        """
        if self.running:
            print("处理系统已在运行")
            return True
        print("启动优化的多摄像头处理系统...")

        if self.enable_rtsp and self.rtsp_server:
            self.rtsp_server.start_monitor_stream(self.fps)
            self.rtsp_server.start_filter_stream(self.fps)
            try:
                from onvif_server import OnvifHttpServer, WsDiscoveryResponder, get_local_ip
                ip = get_local_ip()
                device_path = "/onvif/device_service"
                media_path = "/onvif/media_service"
                # Use public IP for ONVIF advertisement, and ensure credentials are correct
                read_user = getattr(self.rtsp_server, 'read_user', 'shadow') or 'shadow'
                read_pass = getattr(self.rtsp_server, 'read_pass', 'password147') or 'password147'
                
                # Ensure we use the correct IP address that is accessible from ODM
                if ip.startswith("127."):
                   try:
                       s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                       s.connect(('8.8.8.8', 80))
                       ip = s.getsockname()[0]
                       s.close()
                   except:
                       pass

                # Determine Advertise Configuration
                advertise_ip = self.public_ip if self.public_ip else ip
                advertise_rtsp_port = self.public_rtsp_port if self.public_rtsp_port else 8554
                advertise_monitor_port = self.public_onvif_monitor_port if self.public_onvif_monitor_port else 18000
                advertise_filter_port = self.public_onvif_filter_port if self.public_onvif_filter_port else 18001

                # Since reading now requires credentials, we include them in the URL
                monitor_h264_url = f"rtsp://{read_user}:{read_pass}@{advertise_ip}:{advertise_rtsp_port}/monitor_h264"
                filter_h264_url = f"rtsp://{read_user}:{read_pass}@{advertise_ip}:{advertise_rtsp_port}/filter_h264"
                monitor_h265_url = f"rtsp://{read_user}:{read_pass}@{advertise_ip}:{advertise_rtsp_port}/monitor_h265"
                filter_h265_url = f"rtsp://{read_user}:{read_pass}@{advertise_ip}:{advertise_rtsp_port}/filter_h265"
                
                def get_snapshot():
                    try:
                        if self.last_filtered_frame is not None:
                            _, jpg = cv2.imencode('.jpg', self.last_filtered_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                            return jpg.tobytes()
                    except Exception:
                        pass
                    return None

                # --- H264 Services ---
                # H264 Main: Filter (18000)
                self._onvif_h264_filter = OnvifHttpServer(
                    '0.0.0.0', 18000, 
                    advertise_ip, 18000, 
                    device_path, media_path, 
                    monitor_h264_url, filter_h264_url, 
                    snapshot_callback=get_snapshot,
                    visible_profiles=['filter'], # Only expose filter as Main
                    admin_user=read_user,
                    admin_pass=read_pass,
                    codec='H264'
                )
                self._onvif_h264_filter.start()
                
                device_service_url_h264_filter = f"http://{advertise_ip}:18000{device_path}"
                self._wsdd_h264_filter = WsDiscoveryResponder(device_service_url_h264_filter, uuid_str="12345678-1234-5678-1234-567812340001")
                self._wsdd_h264_filter.start()
                print(f"ONVIF H264 Main(Filter) 服务已启动: {device_service_url_h264_filter}")

                # H264 Sub: Monitor (18001)
                self._onvif_h264_monitor = OnvifHttpServer(
                    '0.0.0.0', 18001, 
                    advertise_ip, 18001, 
                    device_path, media_path, 
                    monitor_h264_url, filter_h264_url, 
                    snapshot_callback=get_snapshot,
                    visible_profiles=['monitor'], # Only expose monitor as Sub (conceptually)
                    admin_user=read_user,
                    admin_pass=read_pass,
                    codec='H264'
                )
                self._onvif_h264_monitor.start()
                
                device_service_url_h264_monitor = f"http://{advertise_ip}:18001{device_path}"
                self._wsdd_h264_monitor = WsDiscoveryResponder(device_service_url_h264_monitor, uuid_str="12345678-1234-5678-1234-567812340002")
                self._wsdd_h264_monitor.start()
                print(f"ONVIF H264 Sub(Monitor) 服务已启动: {device_service_url_h264_monitor}")

                # --- H265 Services ---
                # H265 Main: Filter (19000)
                self._onvif_h265_filter = OnvifHttpServer(
                    '0.0.0.0', 19000, 
                    advertise_ip, 19000, 
                    device_path, media_path, 
                    monitor_h265_url, filter_h265_url, 
                    snapshot_callback=get_snapshot,
                    visible_profiles=['filter'],
                    admin_user=read_user,
                    admin_pass=read_pass,
                    codec='H265'
                )
                self._onvif_h265_filter.start()
                
                device_service_url_h265_filter = f"http://{advertise_ip}:19000{device_path}"
                self._wsdd_h265_filter = WsDiscoveryResponder(device_service_url_h265_filter, uuid_str="12345678-1234-5678-1234-567812340003")
                self._wsdd_h265_filter.start()
                print(f"ONVIF H265 Main(Filter) 服务已启动: {device_service_url_h265_filter}")

                # H265 Sub: Monitor (19001)
                self._onvif_h265_monitor = OnvifHttpServer(
                    '0.0.0.0', 19001, 
                    advertise_ip, 19001, 
                    device_path, media_path, 
                    monitor_h265_url, filter_h265_url, 
                    snapshot_callback=get_snapshot,
                    visible_profiles=['monitor'],
                    admin_user=read_user,
                    admin_pass=read_pass,
                    codec='H265'
                )
                self._onvif_h265_monitor.start()
                
                device_service_url_h265_monitor = f"http://{advertise_ip}:19001{device_path}"
                self._wsdd_h265_monitor = WsDiscoveryResponder(device_service_url_h265_monitor, uuid_str="12345678-1234-5678-1234-567812340004")
                self._wsdd_h265_monitor.start()
                print(f"ONVIF H265 Sub(Monitor) 服务已启动: {device_service_url_h265_monitor}")

            except Exception as e:
                print(f"ONVIF 服务启动失败: {e}")

        if not self._initialize_async_cameras():
            print("错误：异步摄像头初始化失败")
            return False
        if not self._initialize_async_video_writers():
            if self.enable_save:
                print("警告：视频写入器初始化失败")
        
        self.running = True
        self.start_time = time.monotonic()
        self.global_stats['start_time'] = self.start_time
        self.process_thread = threading.Thread(target=self._optimized_process_loop, daemon=True)
        self.process_thread.start()
        print("优化的处理系统启动完成")
        return True

    def _optimized_process_loop(self):
        """优化的处理循环主方法"""
        try:
            print("开始优化的处理循环...")
        except BrokenPipeError:
            pass
        except Exception:
            pass
        while self.running:
            cycle_start_time = time.monotonic()
            try:
                all_frames, frame_metadata_dict = self._collect_frames_from_cameras()
                if not all_frames:
                    time.sleep(0.01)
                    continue

                processing_start = time.monotonic()
                batch_results = self.frame_processor.cross_camera_batch_processing(all_frames)
                processing_time = time.monotonic() - processing_start

                self._process_inference_results(batch_results, all_frames, frame_metadata_dict, processing_time)

                self._update_cycle_statistics(cycle_start_time, processing_time)

                self._control_processing_frequency(cycle_start_time)
            except Exception as e:
                import traceback
                error_msg = f"处理循环异常: {type(e).__name__}: {e}"
                try:
                    print(error_msg)
                    print(f"异常详情: {traceback.format_exc()}")
                except Exception:
                    pass
                
                try:
                    error_log_path = os.path.join(self.logs_dir, 'error_log.txt')
                    with open(error_log_path, 'a', encoding='utf-8') as f:
                        f.write(f"{datetime.now().isoformat()} - {error_msg}\n")
                        f.write(f"详细堆栈: {traceback.format_exc()}\n")
                        f.write("-" * 50 + "\n")
                except Exception:
                    pass
                
                time.sleep(0.01)

    def _collect_frames_from_cameras(self):
        """从所有摄像头收集帧数据"""
        all_frames = {}
        frame_metadata_dict = {}
        
        for device, camera in self.async_cameras.items():
            frame_data = camera.get_latest_frame()
            if frame_data is not None:
                if isinstance(frame_data, dict):
                    all_frames[device] = frame_data.get('frame')
                    frame_metadata_dict[device] = frame_data
                else:
                    all_frames[device] = frame_data
                    frame_metadata_dict[device] = {}
                self.stats[device]['captured_frames'] += 1
                self.global_stats['total_captured'] += 1
        
        return all_frames, frame_metadata_dict

    def _process_inference_results(self, batch_results, all_frames, frame_metadata_dict, processing_time):
        """处理AI推理结果"""
        camera_frames = []
        filtered_frame = None
        monitor_frame_metadata = None
        camera_metadata_list = []
        has_new_filtered_frame = False
        
        for device, (flag, pred_labels) in batch_results.items():
            frame = all_frames[device]
            frame_metadata = frame_metadata_dict.get(device, {})
            self.stats[device]['processed_frames'] += 1
            self.global_stats['total_processed'] += 1
            resized_frame = cv2.resize(frame, self.frame_size)

            if monitor_frame_metadata is None and frame_metadata:
                current_time = time.monotonic()
                capture_time = frame_metadata.get('capture_timestamp')
                if capture_time is not None:
                    pipeline_latency_ms = (current_time - capture_time) * 1000.0
                    if 0 <= pipeline_latency_ms <= 2000:
                        monitor_frame_metadata = frame_metadata.copy()
                        monitor_frame_metadata['processing_time'] = processing_time
                        monitor_frame_metadata['pipeline_latency_ms'] = pipeline_latency_ms
                        self.performance_monitor['pipeline_latency_samples'].append(pipeline_latency_ms)

            if flag:
                self.stats[device]['selected_frames'] += 1
                self.global_stats['total_selected'] += 1
                if filtered_frame is None:
                    filtered_frame = resized_frame.copy()
                    
                    # Apply Temporal Brightness Stabilization (First Step)
                    # Processing brightness BEFORE denoising preserves details better and allows denoiser to work on balanced image
                    if self.enable_temporal_brightness:
                        try:
                            # Use YCrCb color space for better linearity and less detail loss than LAB
                            ycrcb = cv2.cvtColor(filtered_frame, cv2.COLOR_BGR2YCrCb)
                            y, cr, cb = cv2.split(ycrcb)
                            
                            # Calculate current brightness mean (Y channel)
                            current_mean = np.mean(y)
                            if current_mean < 5:
                                current_mean = 5.0  # Avoid division by zero
                            
                            # Calculate target gain
                            target_gain = self.temporal_target / current_mean
                            
                            # Clamp gain to avoid extreme washouts (0.5x to 3.0x)
                            target_gain = np.clip(target_gain, 0.5, 3.0)
                            
                            # Smooth gain over time (Exponential Moving Average)
                            self.brightness_gain_tracker = (1.0 - self.temporal_alpha) * self.brightness_gain_tracker + \
                                                           self.temporal_alpha * target_gain
                            
                            # Apply smoothed gain to Y channel
                            # use convertScaleAbs for safe saturation handling (Y * gain + 0)
                            y = cv2.convertScaleAbs(y, alpha=self.brightness_gain_tracker, beta=0)
                            
                            # Merge back
                            ycrcb = cv2.merge((y, cr, cb))
                            filtered_frame = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
                        except Exception as e:
                            print(f"时域亮度稳定处理异常: {e}")
                            pass

                    # Apply denoising if enabled (Second Step)
                    if self.enable_denoise:
                        try:
                            if self.denoise_method == 'gaussian':
                                # Gaussian Blur: effective against Gaussian noise
                                filtered_frame = cv2.GaussianBlur(filtered_frame, (5, 5), 0)
                            elif self.denoise_method == 'nlm':
                                # Non-Local Means: preserves edges, removes noise, computationally expensive
                                # h=10 for luminance, hColor=10 for color components
                                filtered_frame = cv2.fastNlMeansDenoisingColored(filtered_frame, None, 10, 10, 7, 21)
                            elif self.denoise_method == 'gaussian_nlm':
                                # Combined: Gaussian Blur first, then NLM
                                filtered_frame = cv2.GaussianBlur(filtered_frame, (5, 5), 0)
                                filtered_frame = cv2.fastNlMeansDenoisingColored(filtered_frame, None, 10, 10, 7, 21)
                            elif self.denoise_method == 'wavelet':
                                # Wavelet Denoising (Haar wavelet, 2 levels, soft thresholding)
                                try:
                                    img_float = filtered_frame.astype(float)
                                    channels = cv2.split(img_float)
                                    result_channels = []
                                    for channel in channels:
                                        coeffs = pywt.wavedec2(channel, 'haar', level=2)
                                        threshold = 20.0
                                        new_coeffs = list(coeffs)
                                        new_coeffs[1:] = [tuple(pywt.threshold(c, threshold, mode='soft') for c in detail) for detail in coeffs[1:]]
                                        rec = pywt.waverec2(new_coeffs, 'haar')
                                        rec = np.clip(rec, 0, 255)
                                        result_channels.append(rec)
                                    merged = cv2.merge(result_channels)
                                    if merged.shape != filtered_frame.shape:
                                        merged = cv2.resize(merged, (filtered_frame.shape[1], filtered_frame.shape[0]))
                                    filtered_frame = merged.astype(np.uint8)
                                except Exception as we:
                                    print(f"小波降噪失败: {we}")
                            else:
                                # Default to Median Blur (good for salt-and-pepper noise)
                                filtered_frame = cv2.medianBlur(filtered_frame, 3)
                        except Exception as e:
                            print(f"降噪处理异常: {e}")
                            pass
                    
                    if monitor_frame_metadata is None:
                        monitor_frame_metadata = frame_metadata.copy()
                        monitor_frame_metadata['processing_time'] = processing_time
                
                self.last_filtered_frame = filtered_frame.copy()
                self.last_filtered_metadata = frame_metadata.copy()
                self.last_filtered_metadata['processing_time'] = processing_time
                self.last_filtered_metadata['is_filtered'] = True
                has_new_filtered_frame = True
        
        for i, device in enumerate(['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3']):
            if device in all_frames:
                camera_frames.append(all_frames[device])
                camera_metadata_list.append(frame_metadata_dict.get(device, {}))
            else:
                camera_frames.append(None)
                camera_metadata_list.append({})
        
        monitor_frame = None
        filter_stream_frame = None

        if (self.enable_rtsp or self.enable_save) and self.rtsp_server:
            monitor_frame = self.rtsp_server.create_monitor_frame(
                camera_frames, 
                filtered_frame, 
                monitor_frame_metadata,
                camera_metadata_list
            )
            
            if filtered_frame is not None:
                filter_stream_frame = filtered_frame
            elif getattr(self, 'last_filtered_frame', None) is not None:
                filter_stream_frame = self.last_filtered_frame.copy()
            else:
                # Ensure stream is active even if no detections yet
                filter_stream_frame = np.zeros((576, 720, 3), dtype=np.uint8)

            if self.enable_rtsp:
                try:
                    if self.rtsp_server.write_monitor_frame(monitor_frame):
                        self.global_stats['total_streamed'] += 1
                        for device in all_frames:
                            self.stats[device]['streamed_frames'] += 1
                except Exception:
                    pass
                
                if filter_stream_frame is not None:
                    try:
                        if self.rtsp_server.write_filter_frame(filter_stream_frame):
                            self.global_stats['total_streamed'] += 1
                    except Exception:
                        pass
        
        # Save Monitor and Filter frames if saving is enabled
        if self.enable_save:
            self._save_monitor_and_filter_frames(monitor_frame, filter_stream_frame)

    def _save_monitor_and_filter_frames(self, monitor_frame, filter_frame):
        """保存 Monitor 和 Filter 帧"""
        if 'monitor' in self.async_video_writers and monitor_frame is not None:
            if self.async_video_writers['monitor'].write_frame_async(monitor_frame):
                self.global_stats['total_saved'] += 1

        if 'filter' in self.async_video_writers and filter_frame is not None:
            if self.async_video_writers['filter'].write_frame_async(filter_frame):
                self.global_stats['total_saved'] += 1

    def _update_cycle_statistics(self, cycle_start_time, processing_time):
        """更新周期统计信息（使用单调时钟）"""
        self.cycle_count += 1
        self.global_stats['total_cycles'] = self.cycle_count
        cycle_time = time.monotonic() - cycle_start_time
        self.performance_monitor['total_cycle_times'].append(cycle_time)
        self.performance_monitor['frame_processing_times'].append(processing_time)
        try:
            self.global_stats['running_time'] = time.monotonic() - self.start_time if self.start_time else 0
        except Exception:
            self.global_stats['running_time'] = 0
        
        if self.cycle_count % 20 == 0:
            self._print_optimized_stats()
            self._log_latency_stats()

    def _control_processing_frequency(self, cycle_start_time):
        """控制处理频率 - 基于单调时钟的无漂移调度，目标24fps"""
        now = time.monotonic()
        target_cycle_time = 1.0 / 24.0  # 24 cycles per second

        if not hasattr(self, '_sched_next'):
            self._sched_next = cycle_start_time + target_cycle_time
            self.recent_cycle_times = deque(maxlen=20)
            self.last_fps_report = now
            self._missed_deadlines = 0

        if now < self._sched_next:
            sleep_time = self._sched_next - now
            time.sleep(sleep_time)
            self._sched_next += target_cycle_time
            actual_cycle_time = time.monotonic() - cycle_start_time
        else:
            late = now - self._sched_next
            skipped = int(late // target_cycle_time) + 1
            self._missed_deadlines += skipped
            self._sched_next += skipped * target_cycle_time
            actual_cycle_time = time.monotonic() - cycle_start_time

        self.recent_cycle_times.append(actual_cycle_time)

        if time.monotonic() - self.last_fps_report > 5.0:
            avg_cycle_time = sum(self.recent_cycle_times) / len(self.recent_cycle_times)
            actual_fps = 1.0 / avg_cycle_time if avg_cycle_time > 0 else 0
            try:
                print(f"[周期控制] 目标: 24.0fps, 实际: {actual_fps:.1f}fps, 平均周期: {avg_cycle_time*1000:.1f}ms, 跳过周期: {self._missed_deadlines}")
            except BrokenPipeError:
                pass
            except Exception:
                pass
            self.last_fps_report = time.monotonic()

    def _add_info_overlay(self, frame, device, pred_labels, frame_metadata=None):
        info_frame = frame.copy()
        if self.overlay_detail_mode == "full":
            device_text = f"Camera: {device.replace('/dev/video', '')}"
            cv2.putText(info_frame, device_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            if pred_labels:
                pred_text = f"Predictions: {pred_labels[:3]}"
                cv2.putText(info_frame, pred_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        ai_ms = None
        latency_ms = None
        if frame_metadata:
            proc_time = frame_metadata.get('processing_time')
            if proc_time is not None:
                ai_ms = max(0.0, proc_time * 1000.0)
            pre_ms = frame_metadata.get('pipeline_latency_ms')
            if pre_ms is not None:
                latency_ms = pre_ms
            if latency_ms is not None and (latency_ms < 0 or latency_ms > 2000):
                latency_ms = None
        ai_text = f"AI: {ai_ms:.1f}ms" if ai_ms is not None else None
        latency_text = None
        if latency_ms is not None:
            latency_text = f"Pipe: {latency_ms:.1f}ms" if self.overlay_detail_mode == "values" else f"Pipeline Latency: {latency_ms:.1f}ms"
        latency_color = (255, 255, 255)
        if latency_ms is not None:
            latency_color = (0, 255, 0) if latency_ms < 50 else ((0, 255, 255) if latency_ms < 100 else (0, 0, 255))
        ai_color = (255, 255, 255)
        if ai_ms is not None:
            ai_color = (0, 255, 0) if ai_ms < 30 else ((0, 255, 255) if ai_ms < 60 else (0, 0, 255))
        lines = []
        if ai_text:
            lines.append((ai_text, ai_color))
        if latency_text:
            lines.append((latency_text, latency_color))
        if lines:
            base_y = 85 if self.overlay_detail_mode == "full" else 30
            max_w = 0
            total_h = 0
            for text, _ in lines:
                size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                max_w = max(max_w, size[0])
                total_h += size[1] + 10
            cv2.rectangle(info_frame, (10, base_y), (10 + max_w + 14, base_y + total_h + 6), (0, 0, 0), -1)
            y = base_y + 20
            for text, color in lines:
                cv2.putText(info_frame, text, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                y += 22
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        capture_text = None
        try:
            if frame_metadata is not None:
                wc_ts = frame_metadata.get('capture_wall_clock')
                if wc_ts is not None:
                    capture_text = datetime.fromtimestamp(wc_ts).strftime("%H:%M:%S.%f")[:-3]
                else:
                    capture_text = None
        except Exception:
            capture_text = None
        bottom_y = info_frame.shape[0] - 10
        if capture_text is not None:
            cv2.putText(info_frame, capture_text, (10, bottom_y - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(info_frame, timestamp, (10, bottom_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return info_frame

    def _print_optimized_stats(self):
        try:
            print(f"\n=== 优化处理系统统计 (周期 {self.cycle_count}) ===")
            print(f"运行时间: {self.global_stats['running_time']:.2f}秒")
            print(f"总捕获帧数: {self.global_stats['total_captured']}")
            print(f"总处理帧数: {self.global_stats['total_processed']}")
            print(f"总筛选通过帧数: {self.global_stats['total_selected']}")
            print(f"总保存帧数: {self.global_stats['total_saved']}")
            print(f"总推流帧数: {self.global_stats['total_streamed']}")
            print(f"总处理周期数: {self.global_stats['total_cycles']}")
            if self.performance_monitor['frame_processing_times']:
                avg_processing_time = np.mean(self.performance_monitor['frame_processing_times'][-100:])
                print(f"平均AI处理时间: {avg_processing_time*1000:.2f}ms")
            if self.performance_monitor['total_cycle_times']:
                avg_cycle_time = np.mean(self.performance_monitor['total_cycle_times'][-100:])
                print(f"平均周期时间: {avg_cycle_time*1000:.2f}ms")
            for device, writer in self.async_video_writers.items():
                stats = writer.get_stats()
                print(f"设备 {device}: 写入={stats['frames_written']}, 丢弃={stats['frames_dropped']}, 队列={stats['queue_size']}")
            try:
                if self.enable_rtsp and self.rtsp_server:
                    st = self.rtsp_server.get_status() if hasattr(self.rtsp_server, 'get_status') else {}
                    if st:
                        print(f"RTSP心跳: 运行={st.get('running')}, 编码器={st.get('encoder')}, 帧={st.get('frames')}, 错误={st.get('errors')}, 重启={st.get('restarts')}, 连续错误={st.get('consecutive_errors')}, 队列={st.get('queue_size')}, 丢弃={st.get('queue_dropped')}, 监控重启={st.get('monitor_restarts')}, 筛选重启={st.get('filter_restarts')}, 运行秒={st.get('uptime_sec'):.1f}")
            except Exception:
                pass
            print("=" * 50)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                print(f"统计打印异常: {e}")
            except Exception:
                pass

    def _log_latency_stats(self):
        try:
            samples_deque = self.performance_monitor.get('pipeline_latency_samples', [])
            samples = list(samples_deque) if samples_deque else []
            if not samples:
                return
            mean_ms = float(np.mean(samples))
            p95_ms = float(np.percentile(samples, 95))
            max_ms = float(np.max(samples))
            avg_ai_ms = 0.0
            if self.performance_monitor.get('frame_processing_times'):
                avg_ai_ms = float(np.mean(self.performance_monitor['frame_processing_times'][-100:]) * 1000)
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            row = [ts, self.cycle_count, f"{mean_ms:.2f}", f"{p95_ms:.2f}", f"{max_ms:.2f}", f"{avg_ai_ms:.2f}"]
            with open(self.latency_log_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            print(f"写入管道时延统计失败: {e}")

    def stop_processing(self) -> None:
        if not self.running:
            return
        try:
            print("停止优化的处理系统...")
        except Exception:
            pass
        self.running = False
        if self.process_thread:
            self.process_thread.join(timeout=5.0)
        for camera in self.async_cameras.values():
            camera.stop()
        for writer in self.async_video_writers.values():
            try:
                writer.stop()
            except Exception:
                pass
        if self.enable_rtsp and self.rtsp_server:
            self.rtsp_server.stop_stream()
        try:
            if hasattr(self, '_wsdd_h264_filter') and self._wsdd_h264_filter:
                self._wsdd_h264_filter.stop()
            if hasattr(self, '_onvif_h264_filter') and self._onvif_h264_filter:
                self._onvif_h264_filter.stop()
            if hasattr(self, '_wsdd_h264_monitor') and self._wsdd_h264_monitor:
                self._wsdd_h264_monitor.stop()
            if hasattr(self, '_onvif_h264_monitor') and self._onvif_h264_monitor:
                self._onvif_h264_monitor.stop()
            if hasattr(self, '_wsdd_h265_filter') and self._wsdd_h265_filter:
                self._wsdd_h265_filter.stop()
            if hasattr(self, '_onvif_h265_filter') and self._onvif_h265_filter:
                self._onvif_h265_filter.stop()
            if hasattr(self, '_wsdd_h265_monitor') and self._wsdd_h265_monitor:
                self._wsdd_h265_monitor.stop()
            if hasattr(self, '_onvif_h265_monitor') and self._onvif_h265_monitor:
                self._onvif_h265_monitor.stop()
        except Exception:
            pass
        try:
            self._print_stats()
        except Exception:
            pass
        try:
            print("实时视频处理系统已停止")
        except Exception:
            pass

    def _print_stats(self):
        try:
            print("\n===== 处理统计信息 =====")
            for device_id, stats in self.stats.items():
                print(f"摄像头 {device_id}:")
                print(f"  - 捕获帧数: {stats['captured_frames']}")
                print(f"  - 处理帧数: {stats['processed_frames']}")
                print(f"  - 筛选通过帧数: {stats['selected_frames']}")
                print(f"  - 保存帧数: {stats['saved_frames']}")
                print(f"  - 推流帧数: {stats['streamed_frames']}")
                print(f"  - 丢弃帧数: {stats['dropped_frames']}")

            print("\n总计:")
            print(f"  - 总捕获帧数: {self.global_stats['total_captured']}")
            print(f"  - 总处理帧数: {self.global_stats['total_processed']}")
            print(f"  - 总筛选通过帧数: {self.global_stats['total_selected']}")
            print(f"  - 总保存帧数: {self.global_stats['total_saved']}")
            print(f"  - 总推流帧数: {self.global_stats['total_streamed']}")
            print(f"  - 总处理周期数: {self.cycle_count}")
            duration = time.monotonic() - self.start_time if self.start_time else 0
            print(f"\n运行时间: {duration:.2f} 秒")
            if duration > 0:
                print(f"平均处理速率: {self.global_stats['total_processed'] / duration:.2f} 帧/秒")
                print(f"平均保存速率: {self.global_stats['total_saved'] / duration:.2f} 帧/秒")
                print(f"平均推流速率: {self.global_stats['total_streamed'] / duration:.2f} 帧/秒")
                print(f"平均处理周期速率: {self.cycle_count / duration:.2f} 周期/秒")
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                print(f"统计打印异常: {e}")
            except Exception:
                pass


class ONVIFServerManager:
    """管理 ONVIF Server 子进程"""
    def __init__(self, script_path="onvif_server.py"):
        self.script_path = os.path.abspath(script_path)
        self.process = None

    def start(self):
        """启动 ONVIF Server"""
        if self.process is not None and self.process.poll() is None:
            print("ONVIF Server 已经在运行")
            return

        print(f"正在启动 ONVIF Server: {self.script_path}")
        try:
            # 使用 sys.executable 确保使用相同的 python 解释器
            self.process = subprocess.Popen(
                [sys.executable, self.script_path],
                cwd=os.path.dirname(self.script_path),
                stdout=subprocess.DEVNULL, # 避免干扰主程序输出
                stderr=subprocess.DEVNULL
            )
            print(f"ONVIF Server 启动成功, PID: {self.process.pid}")
        except Exception as e:
            print(f"ONVIF Server 启动失败: {e}")

    def stop(self):
        """停止 ONVIF Server"""
        if self.process:
            print("正在停止 ONVIF Server...")
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except Exception as e:
                print(f"停止 ONVIF Server 异常: {e}")
            finally:
                self.process = None
                print("ONVIF Server 已停止")


def main() -> None:
    """优化的主程序入口
    
    创建并启动多摄像头AI处理系统，配置信号处理器以支持优雅关闭。
    系统支持实时AI推理、RTSP流推送、帧插值等高级功能。
    """
    parser = argparse.ArgumentParser(description="多摄像头AI处理系统")
    parser.add_argument("--save", action="store_true", help="启用视频录制 (录制筛选后的流)")
    parser.add_argument("--output", type=str, default="optimized_videos", help="视频保存目录")
    parser.add_argument("--conf", type=float, default=0.7, help="置信度阈值")
    parser.add_argument("--no-rtsp", action="store_true", help="禁用RTSP推流")
    parser.add_argument("--model", type=str, default="./best.pt", help="模型路径")
    parser.add_argument("--no-denoise", action="store_true", help="禁用降噪处理 (默认开启中值降噪)")
    parser.add_argument("--denoise-method", type=str, default="median", choices=['median', 'gaussian', 'nlm', 'gaussian_nlm', 'wavelet'], 
                      help="降噪算法: median(中值,去雪花点), gaussian(高斯), nlm(非局部均值), gaussian_nlm(高斯+NLM), wavelet(小波)")
    parser.add_argument("--no-temporal", action="store_true", help="禁用时域亮度稳定控制 (默认已开启)")
    parser.add_argument("--temporal-target", type=float, default=85.0, help="时域稳定目标亮度均值 (0-255, 默认: 85.0)")
    parser.add_argument("--temporal-alpha", type=float, default=0.01, help="时域平滑系数 (0.01-1.0, 越小越平滑, 默认: 0.01)")
    
    # Public Access Arguments
    parser.add_argument("--public-ip", type=str, default="117.72.39.181", help="公网IP地址 (用于ONVIF/RTSP宣告, 如 117.72.39.181)")
    parser.add_argument("--public-rtsp-port", type=int, default=8554, help="公网RTSP端口 (默认: 8554)")
    parser.add_argument("--public-onvif-monitor-port", type=int, default=18000, help="公网ONVIF Monitor端口 (默认: 18000)")
    parser.add_argument("--public-onvif-filter-port", type=int, default=18001, help="公网ONVIF Filter端口 (默认: 18001)")
    parser.add_argument("--batch-size", type=int, default=32, help="AI推理批处理大小 (默认: 32)")

    args = parser.parse_args()

    print("启动优化的多摄像头AI处理系统...")
    print(f"配置: 录制={args.save}, 输出目录={args.output}, 置信度={args.conf}, RTSP={not args.no_rtsp}, 降噪={not args.no_denoise}, 算法={args.denoise_method}, 时域稳定={not args.no_temporal}, 批处理={args.batch_size}")
    if args.public_ip:
        print(f"公网模式: IP={args.public_ip}, RTSP端口={args.public_rtsp_port or 8554}")

    processor = SyncFrameProcessor(
        model_path=args.model,
        output_dir=args.output,
        confidence_threshold=args.conf,
        enable_rtsp=not args.no_rtsp,
        rtsp_port=8554,
        target_fps=24,
        max_workers=6,
        batch_size=args.batch_size,
        enable_save=args.save,
        enable_denoise=not args.no_denoise,
        denoise_method=args.denoise_method,
        enable_temporal_brightness=not args.no_temporal,
        temporal_target=args.temporal_target,
        temporal_alpha=args.temporal_alpha,
        public_ip=args.public_ip,
        public_rtsp_port=args.public_rtsp_port,
        public_onvif_monitor_port=args.public_onvif_monitor_port,
        public_onvif_filter_port=args.public_onvif_filter_port
    )

    def signal_handler(signum, frame):
        print(f"接收到信号 {signum}，正在停止系统...")
        processor.stop_processing()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if processor.start_processing():
            try:
                # Print all available ONVIF service addresses
                print("\n" + "="*50)
                print("ONVIF 服务地址列表:")
                print(f"  - H264 Filter (Main): http://{args.public_ip or 'localhost'}:18000/onvif/device_service")
                print(f"  - H264 Monitor (Sub): http://{args.public_ip or 'localhost'}:18001/onvif/device_service")
                print(f"  - H265 Filter (Main): http://{args.public_ip or 'localhost'}:19000/onvif/device_service")
                print(f"  - H265 Monitor (Sub): http://{args.public_ip or 'localhost'}:19001/onvif/device_service")
                print("="*50 + "\n")
            except Exception:
                pass
            while True:
                time.sleep(1)
        else:
            print("系统启动失败")
    except KeyboardInterrupt:
        print("\n用户中断，正在停止系统...")
    except Exception as e:
        import traceback
        error_msg = f"系统异常: {type(e).__name__}: {e}"
        print(error_msg)
        print(f"异常详情: {traceback.format_exc()}")
        
        try:
            logs_dir = os.path.join(os.getcwd(), 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            error_log_path = os.path.join(logs_dir, 'system_error_log.txt')
            with open(error_log_path, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {error_msg}\n")
                f.write(f"详细堆栈: {traceback.format_exc()}\n")
                f.write("-" * 50 + "\n")
        except Exception:
            pass
    finally:
        try:
            processor.stop_processing()
        except Exception as e:
            print(f"停止系统时发生异常: {e}")
        
        if 'onvif_manager' in locals() and onvif_manager:
            try:
                onvif_manager.stop()
            except Exception as e:
                print(f"停止 ONVIF Server 时发生异常: {e}")


if __name__ == "__main__":
    main()