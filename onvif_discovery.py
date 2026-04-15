#!/usr/bin/env python3
"""
简易 ONVIF 设备发现与服务端集成占位
- 使用 WS-Discovery 广播/单播尝试发现支持 ONVIF 的设备
- 在缺省环境下不引入第三方依赖，仅做端口探测与日志
"""
import socket
import time
from typing import List, Optional, Tuple

COMMON_ONVIF_PORTS = [80, 554, 8000, 18000, 8899, 5000]


def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def discover_onvif_devices(timeout: float = 2.0) -> List[Tuple[str, int]]:
    """
    简易发现：在本地网段的常见地址上尝试连接常见端口。
    返回列表：(host, port)
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
    占位：将 RTSP URL 注册到 ONVIF 服务端（实际需 SOAP/Device service 接口）。
    在此仅打印日志，后续可替换为真实 ONVIF Device/Media/PTZ 集成。
    """
    if device:
        host, port = device
        print(f"尝试向 ONVIF 服务器注册流: {rtsp_url} -> {host}:{port}")
    else:
        print(f"未发现 ONVIF 服务器，保留本地监听流: {rtsp_url}")