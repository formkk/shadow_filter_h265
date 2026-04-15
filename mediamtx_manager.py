#!/usr/bin/env python3
"""
MediaMTX 管理器
- 负责解压 rtsp_server/mediamtx.tar.gz
- 启动本地 RTSP 服务器（默认监听 0.0.0.0:8554）
- 提供 ensure_running()/stop() 接口供上层调用

备注：MediaMTX 默认即可提供 RTSP 服务，ONVIF 设备端可通过 RTSP URL 进行播放；
如需完整 ONVIF Device/Media 服务，可后续替换为带 ONVIF 插件的配置或服务集成。
"""
import os
import tarfile
import subprocess
import time
import socket
import shutil
import signal
from typing import Optional


class MediaMTXManager:
    def __init__(self, archive_path: Optional[str] = None, base_dir: Optional[str] = None,
                 listen_addr: str = "0.0.0.0", rtsp_port: int = 8554):
        self.base_dir = base_dir or os.path.join(os.path.dirname(__file__), "rtsp_server")
        self.archive_path = archive_path or os.path.join(self.base_dir, "mediamtx.tar.gz")
        self.extract_dir = os.path.join(self.base_dir, "mediamtx_extracted")
        self.run_dir = os.path.join(self.base_dir, "mediamtx_run")
        self.listen_addr = listen_addr
        self.rtsp_port = rtsp_port
        self.process: Optional[subprocess.Popen] = None
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.extract_dir, exist_ok=True)
        os.makedirs(self.run_dir, exist_ok=True)
        self.logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.log_path = os.path.join(self.logs_dir, "mediamtx.log")

    def _ensure_extracted(self) -> Optional[str]:
        """确保 mediamtx 已解压，返回可执行文件路径"""
        binary_path = os.path.join(self.extract_dir, "mediamtx")
        if os.path.exists(binary_path):
            return binary_path
        if not os.path.exists(self.archive_path):
            return None
        try:
            with tarfile.open(self.archive_path, "r:gz") as tar:
                tar.extractall(self.extract_dir)
        except Exception as e:
            print(f"解压失败: {e}")
            return None
        for root, dirs, files in os.walk(self.extract_dir):
            if "mediamtx" in files:
                return os.path.join(root, "mediamtx")
        return None

    def _is_listening(self, addr: str, port: int) -> bool:
        """探测监听，0.0.0.0/:: 时改用 127.0.0.1"""
        probe_addr = addr
        if addr in ("0.0.0.0", "::"):
            probe_addr = "127.0.0.1"
        try:
            with socket.create_connection((probe_addr, port), timeout=0.3):
                return True
        except Exception:
            return False

    def _write_minimal_config(self) -> str:
        cfg_path = os.path.join(self.run_dir, "mediamtx.yml")
        
        # Get credentials from environment or defaults
        pub_user = os.environ.get('RTSP_PUBLISH_USER', 'shadow')
        pub_pass = os.environ.get('RTSP_PUBLISH_PASS', 'password147')
        read_user = os.environ.get('RTSP_READ_USER', 'shadow')
        read_pass = os.environ.get('RTSP_READ_PASS', 'password147')
        
        # Construct users config
        users_config = ""
        if pub_user == read_user:
            # Single user scenario
            # If passwords differ, warn or prefer publish pass (since publisher needs to connect)
            # For simplicity, we use publish pass for the user
            final_pass = pub_pass
            if pub_pass != read_pass:
                print(f"Warning: RTSP_PUBLISH_PASS and RTSP_READ_PASS differ for same user '{pub_user}'. Using RTSP_PUBLISH_PASS for authentication.")
            
            users_config = (
                f"- user: {pub_user}\n"
                f"  pass: {final_pass}\n"
                "  permissions:\n"
                "  - action: publish\n"
                "  - action: read\n"
            )
        else:
            # Dual user scenario
            users_config = (
                f"- user: {pub_user}\n"
                f"  pass: {pub_pass}\n"
                "  permissions:\n"
                "  - action: publish\n"
                "  - action: read\n" # Publisher can also read usually
                f"- user: {read_user}\n"
                f"  pass: {read_pass}\n"
                "  permissions:\n"
                "  - action: read\n"
            )

        try:
            with open(cfg_path, "w") as f:
                f.write(
                    "# 主RTSP服务器配置\n"
                    "rtsp: yes\n"
                    "rtspAddress: :8554\n"
                    "rtspTransports: [udp, tcp]\n"
                    "rtspAuthMethods: [basic, digest]\n"
                    "rtmp: no\n"
                    "hls: no\n"
                    "webrtc: no\n"
                    "srt: no\n"
                    "\n"
                    "authInternalUsers:\n"
                    "- user: any\n"
                    "  pass: \n"
                    "  permissions:\n"
                    "  - action: read\n"
                    f"{users_config}"
                    "\n"
                    "paths:\n"
                    "  monitor:\n"
                    "    source: publisher\n"
                    "    overridePublisher: yes\n"
                    "  filter:\n"
                    "    source: publisher\n"
                    "    overridePublisher: yes\n"
                    "  monitor_h264:\n"
                    "    source: publisher\n"
                    "    overridePublisher: yes\n"
                    "  filter_h264:\n"
                    "    source: publisher\n"
                    "    overridePublisher: yes\n"
                    "  optimized_live:\n"
                    "    source: rtsp://shadow:password147@127.0.0.1:8554/filter_h264\n"
                    "    sourceOnDemand: yes\n"
                    "  Streaming/Channels/101:\n"
                    "    source: rtsp://shadow:password147@127.0.0.1:8554/monitor_h264\n"
                    "    sourceOnDemand: yes\n"
                    "  Streaming/Channels/102:\n"
                    "    source: rtsp://shadow:password147@127.0.0.1:8554/filter_h264\n"
                    "    sourceOnDemand: yes\n"
                )
        except Exception as e:
            print(f"写入 MediaMTX 配置失败: {e}")
        return cfg_path

    def _terminate_existing_mtx(self):
        """终止系统中已有的 mediamtx 进程（非本管理器启动的也尝试终止）"""
        try:
            out = subprocess.check_output(["ps", "-eo", "pid,comm,cmd"], text=True)
        except Exception:
            return
        pids = []
        for line in out.splitlines():
            try:
                parts = line.strip().split(None, 2)
                if len(parts) < 2:
                    continue
                pid_str, comm = parts[0], parts[1]
                if comm == "mediamtx" and pid_str.isdigit():
                    pids.append(int(pid_str))
            except Exception:
                continue
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        deadline = time.time() + 1.0
        while time.time() < deadline and self._is_listening(self.listen_addr, self.rtsp_port):
            time.sleep(0.1)

    def ensure_running(self, wait_seconds: float = 2.0) -> bool:
        """确保 RTSP 服务器正在运行；如已存在配置，优先使用现有配置"""
        cfg_path = os.path.join(self.run_dir, "mediamtx.yml")
        if not os.path.exists(cfg_path):
            cfg_path = self._write_minimal_config()
        else:
            try:
                with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                need_update = ('monitor_h264:' not in content) or ('filter_h264:' not in content)
                if 'rtspTransports:' in content and '[udp, tcp]' not in content:
                    need_update = True
                if 'rtspAuthMethods:' not in content:
                    need_update = True
                if need_update:
                    updated = content
                    if 'rtspTransports: [tcp]' in updated:
                        updated = updated.replace('rtspTransports: [tcp]', 'rtspTransports: [udp, tcp]')
                    if 'rtspAuthMethods:' not in updated and 'rtspTransports:' in updated:
                        lines = updated.splitlines(True)
                        out = []
                        inserted = False
                        for line in lines:
                            out.append(line)
                            if (not inserted) and line.strip().startswith('rtspTransports:'):
                                out.append('rtspAuthMethods: [basic, digest]\n')
                                inserted = True
                        updated = ''.join(out)

                    append = ""
                    if 'paths:' in content:
                        if 'monitor_h264:' not in content:
                            append += "\n  monitor_h264:\n    source: publisher\n    overridePublisher: yes\n"
                        if 'filter_h264:' not in content:
                            append += "\n  filter_h264:\n    source: publisher\n    overridePublisher: yes\n"
                        if 'monitor_h265:' not in content:
                            append += "\n  monitor_h265:\n    source: publisher\n    overridePublisher: yes\n"
                        if 'filter_h265:' not in content:
                            append += "\n  filter_h265:\n    source: publisher\n    overridePublisher: yes\n"
                    if updated != content:
                        with open(cfg_path, 'w', encoding='utf-8') as f:
                            f.write(updated)
                        content = updated
                    if append:
                        with open(cfg_path, 'a', encoding='utf-8') as f:
                            f.write(append)
            except Exception:
                pass

        if self._is_listening(self.listen_addr, self.rtsp_port):
            self._terminate_existing_mtx()

        binary = self._ensure_extracted()
        if not binary:
            print("无法找到 MediaMTX 可执行文件")
            return False
        try:
            logf = open(self.log_path, 'ab', buffering=0)
            env = os.environ.copy()
            env["MTX_RTSPTRANSPORTS"] = "udp,tcp"
            self.process = subprocess.Popen(
                [binary, cfg_path],
                cwd=self.run_dir,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except Exception as e:
            print(f"启动 MediaMTX 失败: {e}")
            return False
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._is_listening(self.listen_addr, self.rtsp_port):
                print(f"MediaMTX 已启动并监听 RTSP: rtsp://{self.listen_addr}:{self.rtsp_port}/")
                return True
            time.sleep(0.1)
        print("MediaMTX 未在预期时间内完成监听，但将继续尝试推流")
        return False

    def stop(self) -> None:
        """停止 MediaMTX 服务（可选）"""
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=2)
        except Exception:
            try:
                if self.process:
                    self.process.kill()
            except Exception:
                pass
        finally:
            self.process = None
            self.process = None
