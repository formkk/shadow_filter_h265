import socket
import uuid
import re
import requests
from urllib.parse import urlparse

def discover_devices(timeout=3):
    print("正在发送 WS-Discovery 探测包...")
    msg_id = "urn:uuid:" + str(uuid.uuid4())
    probe_msg = f"""
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
        <s:Header>
            <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
            <a:MessageID>{msg_id}</a:MessageID>
            <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
        </s:Header>
        <s:Body>
            <d:Probe>
                <d:Types>dn:NetworkVideoTransmitter</d:Types>
            </d:Probe>
        </s:Body>
    </s:Envelope>
    """
    
    # Send multicast probe
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    # Allow reusing the port (though we are client here)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except:
        pass
        
    try:
        sock.sendto(probe_msg.encode('utf-8'), ('239.255.255.250', 3702))
        
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                print(f"\n收到来自 {addr} 的响应")
                response = data.decode('utf-8', errors='ignore')
                
                # Simple parsing to find XAddrs
                xaddr_match = re.search(r'XAddrs>(.*?)</', response)
                if xaddr_match:
                    xaddr = xaddr_match.group(1).split()[0] # Take the first one
                    print(f"发现设备服务地址 (XAddr): {xaddr}")
                    return xaddr
            except socket.timeout:
                print("探测超时，未发现更多设备。")
                break
    finally:
        sock.close()
    return None

def get_profiles(service_url):
    print(f"\n正在向 {service_url} 请求 Media Profiles...")
    # Need to parse the service URL to get the media service URL (assuming standard onvif server structure or getting it from capabilities)
    # For this simple script, we'll assume the media service is at /onvif/media_service based on our server code, 
    # OR we should ask for capabilities. Let's ask for Capabilities first to be standard compliant.
    
    # 1. GetCapabilities
    cap_msg = """
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
        <s:Body>
            <tds:GetCapabilities>
                <tds:Category>Media</tds:Category>
            </tds:GetCapabilities>
        </s:Body>
    </s:Envelope>
    """
    
    try:
        # Note: onvif_server.py expects 'application/soap+xml'
        headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
        res = requests.post(service_url, data=cap_msg, headers=headers, timeout=5)
        
        media_url = None
        if res.status_code == 200:
            # Extract Media XAddr
            match = re.search(r'Media><.*?XAddr>(.*?)</', res.text, re.DOTALL)
            if match:
                media_url = match.group(1)
                print(f"获取到媒体服务地址: {media_url}")
        
        if not media_url:
            print("无法获取媒体服务地址，尝试猜测...")
            parsed = urlparse(service_url)
            media_url = f"{parsed.scheme}://{parsed.netloc}/onvif/media_service"

        # 2. GetProfiles
        prof_msg = """
        <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
            <s:Body>
                <trt:GetProfiles/>
            </s:Body>
        </s:Envelope>
        """
        
        res = requests.post(media_url, data=prof_msg, headers=headers, timeout=5)
        print(f"GetProfiles 响应码: {res.status_code}")
        
        profiles = []
        # Simple regex to find profile tokens
        tokens = re.findall(r'Profiles.*?token="(.*?)"', res.text)
        print(f"发现 {len(tokens)} 个 Profile Token: {tokens}")
        
        # 3. GetStreamUri for the first profile
        if tokens:
            token = tokens[0]
            print(f"\n尝试获取 Profile '{token}' 的流地址...")
            stream_msg = f"""
            <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
                <s:Body>
                    <trt:GetStreamUri>
                        <trt:StreamSetup>
                            <tt:Stream>RTP-Unicast</tt:Stream>
                            <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
                        </trt:StreamSetup>
                        <trt:ProfileToken>{token}</trt:ProfileToken>
                    </trt:GetStreamUri>
                </s:Body>
            </s:Envelope>
            """
            res = requests.post(media_url, data=stream_msg, headers=headers, timeout=5)
            uri_match = re.search(r'Uri>(.*?)</', res.text)
            if uri_match:
                print(f"成功获取流地址: {uri_match.group(1)}")
            else:
                print("获取流地址失败: " + res.text[:200])
                
    except Exception as e:
        print(f"请求发生错误: {e}")

if __name__ == "__main__":
    device_url = discover_devices()
    if device_url:
        get_profiles(device_url)
    else:
        print("未在局域网中发现 ONVIF 设备 (请检查 UDP 3702 是否通畅)")
