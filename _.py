import cv2
import numpy as np
import threading
import time
import sys
import os
import csv
import signal
from datetime import datetime
from collections import defaultdict, deque
from ultralytics.models.yolo.model import YOLO
from cam_tensor import RTSPStreamServer
from onvif_discovery import discover_onvif_devices
from cam_tensor_optimized import OptimizedMemoryFrameProcessor, AsyncCameraCapture

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
    """同步帧处理器 - 支持多摄像头实时处理"""
    def __init__(self, model_path='./best.pt', output_dir='combined_videos', confidence_threshold=0.7,
                 enable_rtsp=False, rtsp_port=8554, stream_name="live", enable_interpolation=False,
                 target_fps=24, max_workers=4, batch_size=16, stream_protocol="onvif",
                 gb28181_ip="127.0.0.1", gb28181_port=None, rtsp_listen_addr="127.0.0.1",
                 enable_overlay=True, overlay_detail_mode="full"):
        self.camera_devices = ['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3']
        self.model_path = model_path
        self.output_dir = output_dir
        self.confidence_threshold = confidence_threshold
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.enable_overlay = enable_overlay
        self.overlay_detail_mode = overlay_detail_mode

        self.enable_rtsp = enable_rtsp
        self.rtsp_server = None
        if enable_rtsp:
            self.rtsp_server = RTSPStreamServer(rtsp_port, stream_name, enable_interpolation, target_fps)

        os.makedirs(output_dir, exist_ok=True)

        self.latency_log_path = os.path.join(self.output_dir, 'pipeline_latency_log.csv')
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
        self.fps = 25
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for device in self.async_cameras.keys():
            filename = os.path.join(self.output_dir, f'camera_{device.replace("/dev/video", "")}_{timestamp}.avi')
            writer = AsyncVideoWriter(filename, self.fourcc, self.fps, self.frame_size, buffer_size=200)
            if writer.start():
                self.async_video_writers[device] = writer
                print(f"异步视频写入器启动: {filename}")
            else:
                print(f"异步视频写入器启动失败: {filename}")
        return len(self.async_video_writers) > 0

    def start_processing(self):
        if self.running:
            print("处理系统已在运行")
            return True
        print("启动优化的多摄像头处理系统...")
        if not self._initialize_async_cameras():
            print("错误：异步摄像头初始化失败")
            return False
        if not self._initialize_async_video_writers():
            print("警告：视频写入器初始化失败")
        if self.enable_rtsp and self.rtsp_server:
            self.rtsp_server.start_stream(self.frame_size[0], self.frame_size[1], self.fps)
            try:
                devices = discover_onvif_devices(timeout=2.0)
                if devices:
                    print(f"发现 {len(devices)} 个 ONVIF 设备")
                else:
                    print("未发现 ONVIF 设备")
            except Exception as e:
                print(f"ONVIF 发现/集成异常: {e}")
        self.running = True
        self.start_time = time.time()
        self.global_stats['start_time'] = self.start_time
        self.process_thread = threading.Thread(target=self._optimized_process_loop, daemon=True)
        self.process_thread.start()
        print("优化的处理系统启动完成")
        return True

    def _optimized_process_loop(self):
        print("开始优化的处理循环...")
        while self.running:
            cycle_start_time = time.time()
            try:
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
                if not all_frames:
                    time.sleep(0.001)
                    continue

                processing_start = time.time()
                batch_results = self.frame_processor.cross_camera_batch_processing(all_frames)
                processing_time = time.time() - processing_start

                for device, (flag, pred_labels) in batch_results.items():
                    frame = all_frames[device]
                    frame_metadata = frame_metadata_dict.get(device, {})
                    self.stats[device]['processed_frames'] += 1
                    self.global_stats['total_processed'] += 1
                    resized_frame = cv2.resize(frame, self.frame_size)

                    if flag:
                        self.stats[device]['selected_frames'] += 1
                        self.global_stats['total_selected'] += 1

                    if flag and device in self.async_video_writers:
                        if self.async_video_writers[device].write_frame_async(resized_frame):
                            self.stats[device]['saved_frames'] += 1
                            self.global_stats['total_saved'] += 1

                    if self.enable_rtsp and self.rtsp_server and flag:
                        ffmpeg_send_timestamp = time.time()
                        frame_metadata['ffmpeg_send_timestamp'] = ffmpeg_send_timestamp
                        frame_metadata['processing_time'] = processing_time
                        capture_time = frame_metadata.get('capture_timestamp')
                        if capture_time is not None:
                            pipeline_latency_ms = (ffmpeg_send_timestamp - capture_time) * 1000.0
                            if 0 <= pipeline_latency_ms <= 2000:
                                self.performance_monitor['pipeline_latency_samples'].append(pipeline_latency_ms)
                                frame_metadata['pipeline_latency_ms'] = pipeline_latency_ms
                            else:
                                frame_metadata['pipeline_latency_ms'] = None
                        info_frame = self._add_info_overlay(resized_frame, device, pred_labels, frame_metadata) if self.enable_overlay else resized_frame
                        success = self.rtsp_server.write_frame(info_frame)
                        if success:
                            self.stats[device]['streamed_frames'] += 1
                            self.global_stats['total_streamed'] += 1
                        else:
                            self.stats[device]['dropped_frames'] += 1

                self.cycle_count += 1
                self.global_stats['total_cycles'] = self.cycle_count
                cycle_time = time.time() - cycle_start_time
                self.performance_monitor['total_cycle_times'].append(cycle_time)
                self.performance_monitor['frame_processing_times'].append(processing_time)
                if self.cycle_count % 20 == 0:
                    self._print_optimized_stats()
                    self._log_latency_stats()

                target_cycle_time = 1.0 / 100
                if cycle_time < target_cycle_time:
                    time.sleep(target_cycle_time - cycle_time)
            except Exception as e:
                print(f"处理循环异常: {e}")
                time.sleep(0.01)

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
                cap_ts = frame_metadata.get('capture_timestamp')
                if cap_ts is not None:
                    capture_text = datetime.fromtimestamp(cap_ts).strftime("%H:%M:%S.%f")[:-3]
        except Exception:
            capture_text = None
        bottom_y = info_frame.shape[0] - 10
        if capture_text is not None:
            cv2.putText(info_frame, capture_text, (10, bottom_y - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(info_frame, timestamp, (10, bottom_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return info_frame

    def _print_optimized_stats(self):
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
        print("=" * 50)

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

    def stop_processing(self):
        if not self.running:
            return
        print("停止优化的处理系统...")
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
        self._print_stats()
        print("实时视频处理系统已停止")

    def _print_stats(self):
        print("\n===== 处理统计信息 =====")
        total_captured = 0
        total_processed = 0
        total_selected = 0
        total_saved = 0
        total_streamed = 0
        for device_id, stats in self.stats.items():
            print(f"摄像头 {device_id}:")
            print(f"  - 捕获帧数: {stats['captured_frames']}")
            print(f"  - 处理帧数: {stats['processed_frames']}")
            print(f"  - 筛选通过帧数: {stats['selected_frames']}")
            print(f"  - 保存帧数: {stats['saved_frames']}")
            print(f"  - 推流帧数: {stats['streamed_frames']}")
            print(f"  - 丢弃帧数: {stats['dropped_frames']}")
            total_captured += stats['captured_frames']
            total_processed += stats['processed_frames']
            total_selected += stats['selected_frames']
            total_saved += stats['saved_frames']
            total_streamed += stats['streamed_frames']
        print("\n总计:")
        print(f"  - 总捕获帧数: {total_captured}")
        print(f"  - 总处理帧数: {total_processed}")
        print(f"  - 总筛选通过帧数: {total_selected}")
        print(f"  - 总保存帧数: {total_saved}")
        print(f"  - 总推流帧数: {total_streamed}")
        print(f"  - 总处理周期数: {self.cycle_count}")
        duration = time.time() - self.start_time if self.start_time else 0
        print(f"\n运行时间: {duration:.2f} 秒")
        if duration > 0:
            print(f"平均处理速率: {total_processed / duration:.2f} 帧/秒")
            print(f"平均保存速率: {total_saved / duration:.2f} 帧/秒")
            print(f"平均推流速率: {total_streamed / duration:.2f} 帧/秒")
            print(f"平均处理周期速率: {self.cycle_count / duration:.2f} 周期/秒")


def main():
    """优化的主程序入口"""
    print("启动优化的多摄像头AI处理系统...")
    processor = SyncFrameProcessor(
        model_path='./best.pt',
        output_dir='optimized_videos',
        confidence_threshold=0.5,
        enable_rtsp=True,
        rtsp_port=8554,
        stream_name="live",
        enable_interpolation=True,
        target_fps=24,
        max_workers=6,
        batch_size=32
    )

    def signal_handler(signum, frame):
        print(f"接收到信号 {signum}，正在停止系统...")
        processor.stop_processing()
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if processor.start_processing():
            print("优化系统已启动，按 Ctrl+C 停止...")
            try:
                rtsp_url = getattr(processor.rtsp_server, 'rtsp_url', 'rtsp://localhost:8554/live')
            except Exception:
                rtsp_url = 'rtsp://localhost:8554/live'
            print(f"RTSP流地址: {rtsp_url}")
            while True:
                time.sleep(1)
        else:
            print("系统启动失败")
    except KeyboardInterrupt:
        print("\n用户中断，正在停止系统...")
    except Exception as e:
        print(f"系统异常: {e}")
    finally:
        processor.stop_processing()
        print("优化系统已完全停止")


if __name__ == "__main__":
    main()