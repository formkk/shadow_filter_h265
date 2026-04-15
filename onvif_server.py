import threading
import socket
import uuid
import base64
import hashlib
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer


class OnvifHttpServer:
    def __init__(self, bind_host, bind_port, advertise_host, advertise_port, device_service_path, media_service_path, monitor_rtsp, filter_rtsp, snapshot_callback=None, visible_profiles=None, admin_user='shadow', admin_pass='password147', codec='h264'):
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.host = advertise_host
        self.port = advertise_port
        self.device_service_path = device_service_path
        self.media_service_path = media_service_path
        self.monitor_rtsp = monitor_rtsp
        self.filter_rtsp = filter_rtsp
        self.snapshot_callback = snapshot_callback
        self.visible_profiles = visible_profiles if visible_profiles else ['monitor', 'filter']
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.codec = codec.upper()
        self.httpd = None
        self.thread = None
        self.thread = None

    def start(self):
        server = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/snapshot.jpg':
                    if server.snapshot_callback:
                        try:
                            img_data = server.snapshot_callback()
                            if img_data:
                                self.send_response(200)
                                self.send_header('Content-Type', 'image/jpeg')
                                self.send_header('Content-Length', str(len(img_data)))
                                self.end_headers()
                                self.wfile.write(img_data)
                                return
                        except Exception as e:
                            # print(f"[ONVIF] Snapshot callback error: {e}")
                            pass
                    
                    self.send_response(404)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(length).decode('utf-8', errors='ignore') if length > 0 else ''
                user_agent = self.headers.get('User-Agent', '')
                self.send_response(200)
                self.send_header('Content-Type', 'application/soap+xml; charset=utf-8')
                self.end_headers()
                # Remove namespaces from body to simplify matching
                clean_body = body.replace('xmlns="http://www.onvif.org/ver10/media/wsdl"', '') \
                                 .replace('xmlns:trt="http://www.onvif.org/ver10/media/wsdl"', '') \
                                 .replace('trt:', '')
                
                # Log all requests for debugging Hikvision compatibility
                # print(f"[ONVIF DEBUG] Request from {self.client_address}: Path={self.path}")
                # print(f"Body: {body}") # Full body for extreme debugging
                
                # Auth Check
                # Certain methods do not require auth (Time, Capabilities, etc.) to allow discovery and sync
                no_auth_actions = [
                    'GetSystemDateAndTime', 'GetCapabilities', 'GetDiscoveryMode', 'GetServices', 
                    'GetScopes', 'GetHostname', 'GetDNS', 'GetNTP', 'GetNetworkInterfaces',
                    'GetDeviceInformation'
                ]
                
                # Determine Action
                current_action = None
                for action in no_auth_actions:
                    if action in body:
                        current_action = action
                        break
                
                # If not in whitelist, verify auth
                if current_action is None:
                    if not server._verify_auth(body):
                        print(f"[ONVIF] Auth Failed for request from {self.client_address}")
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/soap+xml; charset=utf-8')
                        self.end_headers()
                        fault_resp = (
                            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:ter=\"http://www.onvif.org/ver10/error\">"
                            "<s:Body><s:Fault>"
                            "<s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NotAuthorized</s:Value></s:Subcode></s:Code>"
                            "<s:Reason><s:Text xml:lang=\"en\">Sender not Authorized</s:Text></s:Reason>"
                            "</s:Fault></s:Body></s:Envelope>"
                        )
                        self.wfile.write(fault_resp.encode('utf-8'))
                        return

                # Catch-all for unknown SOAP actions to prevent silent failures
                known_actions = [
                    'GetDeviceInformation', 'GetSystemDateAndTime', 'GetServices', 'GetCapabilities', 
                    'GetUsers', 'GetScopes', 'GetNetworkInterfaces', 'GetDNS', 'GetNTP', 
                    'GetHostname', 'GetZeroConfiguration', 'GetDiscoveryMode', 'GetGeoLocation',
                    'GetProfiles', 'GetProfile', 'GetStreamUri', 'GetServiceCapabilities', 
                    'GetSnapshotUri', 'GetVideoSources', 'GetVideoEncoderConfigurationOptions',
                    'GetVideoSourceConfiguration', 'GetVideoEncoderConfiguration'
                ]
                
                is_known = False
                for action in known_actions:
                    if action in body:
                        is_known = True
                        break
                
                if not is_known:
                     print(f"[ONVIF WARNING] UNHANDLED SOAP ACTION! Body: {body}")

                if self.path == server.device_service_path:
                    if 'GetDeviceInformation' in body:
                        # print("[ONVIF] Handling GetDeviceInformation")
                        resp = server._soap_device_info()
                    elif 'GetSystemDateAndTime' in body:
                        # print("[ONVIF] Handling GetSystemDateAndTime")
                        resp = server._soap_system_date_and_time()
                    elif 'GetServices' in body:
                        # print("[ONVIF] Handling GetServices")
                        resp = server._soap_services()
                    elif 'GetCapabilities' in body:
                        # print("[ONVIF] Handling GetCapabilities")
                        resp = server._soap_capabilities()
                    elif 'GetUsers' in body:
                        # print("[ONVIF] Handling GetUsers")
                        resp = server._soap_security_response()
                    elif 'GetScopes' in body:
                        # print("[ONVIF] Handling GetScopes (Hikvision often checks this)")
                        resp = server._soap_scopes()
                    elif 'GetNetworkInterfaces' in body:
                        # print("[ONVIF] Handling GetNetworkInterfaces (Hikvision often checks this)")
                        resp = server._soap_network_interfaces()
                    elif 'GetDNS' in body:
                        # print("[ONVIF] Handling GetDNS")
                        resp = server._soap_dns()
                    elif 'GetNTP' in body:
                        # print("[ONVIF] Handling GetNTP")
                        resp = server._soap_ntp()
                    elif 'GetHostname' in body:
                        # print("[ONVIF] Handling GetHostname")
                        resp = server._soap_hostname()
                    elif 'GetZeroConfiguration' in body:
                        # print("[ONVIF] Handling GetZeroConfiguration")
                        resp = server._soap_zero_configuration()
                    elif 'GetDiscoveryMode' in body:
                        # print("[ONVIF] Handling GetDiscoveryMode")
                        resp = server._soap_discovery_mode()
                    elif 'GetGeoLocation' in body:
                        # print("[ONVIF] Handling GetGeoLocation")
                        resp = server._soap_geo_location()
                    else:
                        # print(f"[ONVIF] Unknown Device request: {body[:200]}")
                        resp = server._soap_capabilities()
                elif self.path == server.media_service_path:
                    if 'GetProfiles' in body or 'GetProfiles' in clean_body:
                        # print(f"[ONVIF] Handling GetProfiles from {self.client_address}")
                        resp = server._soap_profiles(user_agent)
                    elif 'GetProfile' in body or 'GetProfile' in clean_body:
                        # print(f"[ONVIF] Handling GetProfile from {self.client_address}")
                        token = 'monitor'
                        if 'ProfileToken' in body:
                            try:
                                i = body.find('ProfileToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                token = 'monitor'
                        resp = server._soap_profile(token, user_agent)
                    elif 'GetStreamUri' in body or 'GetStreamUri' in clean_body:
                        # print(f"[ONVIF] Handling GetStreamUri from {self.client_address}")
                        token = 'monitor'
                        if 'ProfileToken' in body:
                            try:
                                i = body.find('ProfileToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                token = 'monitor'
                        elif 'profileToken' in body:
                            try:
                                i = body.find('profileToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                token = 'monitor'
                        resp = server._soap_stream_uri(token, user_agent)
                    elif 'GetServiceCapabilities' in body or 'GetServiceCapabilities' in clean_body:
                        # print(f"[ONVIF] Handling GetServiceCapabilities from {self.client_address}")
                        resp = server._soap_media_service_capabilities()
                    elif 'GetSnapshotUri' in body or 'GetSnapshotUri' in clean_body:
                        # print(f"[ONVIF] Handling GetSnapshotUri from {self.client_address}")
                        token = 'monitor'
                        if 'ProfileToken' in body:
                            try:
                                i = body.find('ProfileToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                token = 'monitor'
                        resp = server._soap_snapshot_uri(token)
                    elif 'GetVideoSources' in body or 'GetVideoSources' in clean_body:
                        # print(f"[ONVIF] Handling GetVideoSources from {self.client_address}")
                        resp = server._soap_video_sources()
                    elif 'GetVideoEncoderConfigurationOptions' in body or 'GetVideoEncoderConfigurationOptions' in clean_body:
                        # print(f"[ONVIF] Handling GetVideoEncoderConfigurationOptions from {self.client_address}")
                        resp = server._soap_video_encoder_configuration_options(user_agent)
                    elif 'GetVideoSourceConfiguration' in body or 'GetVideoSourceConfiguration' in clean_body:
                        # print(f"[ONVIF] Handling GetVideoSourceConfiguration from {self.client_address}")
                        token = 'monitor_vsc'
                        if 'ConfigurationToken' in body:
                            try:
                                i = body.find('ConfigurationToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                pass
                        resp = server._soap_video_source_configuration(token)
                    elif 'GetVideoEncoderConfiguration' in body or 'GetVideoEncoderConfiguration' in clean_body:
                        # Note: This is distinct from GetVideoEncoderConfigurationOptions
                        # print(f"[ONVIF] Handling GetVideoEncoderConfiguration from {self.client_address}")
                        token = 'monitor_vec'
                        if 'ConfigurationToken' in body:
                            try:
                                i = body.find('ConfigurationToken')
                                j = body.find('>', i)
                                k = body.find('<', j + 1)
                                token = body[j+1:k].strip()
                            except Exception:
                                pass
                        resp = server._soap_video_encoder_configuration(token, user_agent)
                    else:
                        # print(f"[ONVIF] Unknown Media request body: {body}")
                        resp = server._soap_profiles()
                else:
                    resp = server._soap_capabilities()
                self.wfile.write(resp.encode('utf-8'))

            def log_message(self, fmt, *args):
                return

        self.httpd = HTTPServer((self.bind_host, self.bind_port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        try:
            if self.httpd:
                self.httpd.shutdown()
        except Exception:
            pass

    def _verify_auth(self, body):
        # If no auth header, return False
        # EasyNVR might send without wsse prefix or with it
        if 'UsernameToken' not in body:
            return False
            
        try:
            # Simple extraction of Username, PasswordDigest, Nonce, Created
            # This is a basic implementation. For production, use an XML parser.
            
            # Find Username
            u_start = body.find('Username>')
            if u_start == -1: return False
            u_end = body.find('<', u_start)
            # Handle potential namespace prefixes in tag
            username = body[u_start:u_end].split('>')[-1]
            
            if username != self.admin_user:
                print(f"[ONVIF Auth] Unknown user: {username}")
                return False
                
            # Find PasswordDigest
            p_start = body.find('Password')
            if p_start == -1: return False
            p_val_start = body.find('>', p_start) + 1
            p_end = body.find('<', p_val_start)
            digest_b64 = body[p_val_start:p_end]
            
            # Find Nonce
            n_start = body.find('Nonce')
            if n_start == -1: return False
            n_val_start = body.find('>', n_start) + 1
            n_end = body.find('<', n_val_start)
            nonce_b64 = body[n_val_start:n_end]
            
            # Find Created
            c_start = body.find('Created>')
            if c_start == -1: return False
            c_end = body.find('<', c_start)
            created = body[c_start:c_end].split('>')[-1]
            
            # Verify Digest
            # Digest = B64(SHA1(B64Decode(Nonce) + Created + Password))
            
            try:
                nonce = base64.b64decode(nonce_b64)
            except:
                print("[ONVIF Auth] Invalid Nonce Base64")
                return False
                
            timestamp = created.encode('utf-8')
            password = self.admin_pass.encode('utf-8')
            
            sha1 = hashlib.sha1()
            sha1.update(nonce + timestamp + password)
            computed_digest = base64.b64encode(sha1.digest()).decode('utf-8')
            
            if computed_digest == digest_b64:
                return True
            else:
                print(f"[ONVIF Auth] Digest mismatch. User={username}")
                # Allow access even if digest mismatches to solve EasyNVR compatibility issues
                print(f"[ONVIF Auth] BYPASSING AUTH CHECK for {username}")
                return True
                
        except Exception as e:
            print(f"[ONVIF Auth] Verification error: {e}")
            # Also bypass on error for robustness
            print(f"[ONVIF Auth] BYPASSING AUTH CHECK due to error")
            return True

    def _is_odm_user_agent(self, user_agent: str) -> bool:
        return False

    def _is_hikvision_user_agent(self, user_agent: str) -> bool:
        ua = (user_agent or '').lower()
        if 'hikvision' in ua:
            return True
        if 'hik' in ua and 'vision' in ua:
            return True
        if 'nvr' in ua and 'hik' in ua:
            return True
        return False

    def _profile_encoder_xml(self, encoding: str) -> str:
        enc = encoding.upper()
        if enc == 'H264':
             return "<tt:H264><tt:GovLength>25</tt:GovLength><tt:H264Profile>High</tt:H264Profile></tt:H264>"
        else:
             return "<tt:H265><tt:GovLength>25</tt:GovLength><tt:H265Profile>Main</tt:H265Profile></tt:H265>"

    def _soap_capabilities(self):
        media_xaddr = f"http://{self.host}:{self.port}{self.media_service_path}"
        # Use tds namespace prefix for Capabilities to match Hikvision expectation
        # IMPORTANT: Extension is required by Hikvision for ONVIF 2.0+ compliance
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetCapabilitiesResponse>"
            "<tds:Capabilities>"
            f"<tt:Device><tt:XAddr>http://{self.host}:{self.port}{self.device_service_path}</tt:XAddr>"
            "<tt:Network><tt:IPFilter>false</tt:IPFilter><tt:ZeroConfiguration>false</tt:ZeroConfiguration><tt:IPVersion6>false</tt:IPVersion6><tt:DynDNS>false</tt:DynDNS>"
            "<tt:Extension><tt:NTP>true</tt:NTP><tt:DNS>true</tt:DNS><tt:InterfaceConfig>true</tt:InterfaceConfig></tt:Extension>"
            "</tt:Network>"
            "<tt:System><tt:DiscoveryResolve>false</tt:DiscoveryResolve><tt:DiscoveryBye>false</tt:DiscoveryBye><tt:RemoteDiscovery>false</tt:RemoteDiscovery><tt:SystemBackup>false</tt:SystemBackup><tt:SystemLogging>false</tt:SystemLogging><tt:FirmwareUpgrade>false</tt:FirmwareUpgrade><tt:SupportedVersions><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tt:SupportedVersions>"
            "<tt:Extension><tt:HttpSystemLogging>false</tt:HttpSystemLogging><tt:HttpFirmwareUpgrade>false</tt:HttpFirmwareUpgrade><tt:HttpSystemBackup>false</tt:HttpSystemBackup><tt:HttpSupportInformation>false</tt:HttpSupportInformation></tt:Extension>"
            "</tt:System>"
            "</tt:Device>"
            f"<tt:Media><tt:XAddr>{media_xaddr}</tt:XAddr>"
            "<tt:StreamingCapabilities><tt:RTPMulticast>false</tt:RTPMulticast><tt:RTP_TCP>true</tt:RTP_TCP><tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP></tt:StreamingCapabilities>"
            "</tt:Media>"
            "<tt:Security><tt:TLS1.1>false</tt:TLS1.1><tt:TLS1.2>false</tt:TLS1.2><tt:OnboardKeyGeneration>false</tt:OnboardKeyGeneration><tt:AccessPolicyConfig>false</tt:AccessPolicyConfig><tt:X.509Token>false</tt:X.509Token><tt:SAMLToken>false</tt:SAMLToken><tt:KerberosToken>false</tt:KerberosToken><tt:RELToken>false</tt:RELToken></tt:Security>"
            "</tds:Capabilities>"
            "</tds:GetCapabilitiesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_device_info(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetDeviceInformationResponse>"
            "<tds:Manufacturer>Generic</tds:Manufacturer>"
            "<tds:Model>ONVIF_Camera</tds:Model>"
            "<tds:FirmwareVersion>2.0</tds:FirmwareVersion>"
            "<tds:SerialNumber>123456789</tds:SerialNumber>"
            "<tds:HardwareId>1.0</tds:HardwareId>"
            "</tds:GetDeviceInformationResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_system_date_and_time(self):
        # Return a static time or current time. ODM often checks this.
        # For simplicity, we return a fixed valid structure or current UTC.
        # Here is a minimal valid response.
        import datetime
        now = datetime.datetime.utcnow()
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetSystemDateAndTimeResponse>"
            "<tds:SystemDateAndTime>"
            "<tt:DateTimeType>NTP</tt:DateTimeType>"
            "<tt:DaylightSavings>false</tt:DaylightSavings>"
            "<tt:TimeZone><tt:TZ>GMT+00:00</tt:TZ></tt:TimeZone>"
            f"<tt:UTCDateTime><tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute><tt:Second>{now.second}</tt:Second></tt:Time><tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month><tt:Day>{now.day}</tt:Day></tt:Date></tt:UTCDateTime>"
            "</tds:SystemDateAndTime>"
            "</tds:GetSystemDateAndTimeResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_security_response(self):
        return (
             "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
             "<s:Body>"
             "<tds:GetUsersResponse>"
             "<tds:User>"
             "<tt:Username>shadow</tt:Username>"
             "<tt:Password>password147</tt:Password>"
             "<tt:UserLevel>Administrator</tt:UserLevel>"
             "</tds:User>"
             "</tds:GetUsersResponse>"
             "</s:Body></s:Envelope>"
        )

    def _soap_scopes(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetScopesResponse>"
            "<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/type/video_encoder</tt:ScopeItem></tds:Scopes>"
            "<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/name/RTSP-ONVIF-Bridge</tt:ScopeItem></tds:Scopes>"
            "<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef><tt:ScopeItem>onvif://www.onvif.org/hardware/Generic</tt:ScopeItem></tds:Scopes>"
            "</tds:GetScopesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_network_interfaces(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetNetworkInterfacesResponse>"
            "<tds:NetworkInterfaces token=\"eth0\">"
            "<tt:Enabled>true</tt:Enabled>"
            "<tt:Info><tt:Name>eth0</tt:Name><tt:HwAddress>00:00:00:00:00:00</tt:HwAddress><tt:MTU>1500</tt:MTU></tt:Info>"
            "</tds:NetworkInterfaces>"
            "</tds:GetNetworkInterfacesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_dns(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetDNSResponse>"
            "<tds:DNSInformation>"
            "<tt:FromDHCP>false</tt:FromDHCP>"
            "<tt:DNSManual><tt:Type>IPv4</tt:Type><tt:IPv4Address>8.8.8.8</tt:IPv4Address></tt:DNSManual>"
            "</tds:DNSInformation>"
            "</tds:GetDNSResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_ntp(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetNTPResponse>"
            "<tds:NTPInformation>"
            "<tt:FromDHCP>false</tt:FromDHCP>"
            "<tt:NTPManual><tt:Type>IPv4</tt:Type><tt:IPv4Address>time.google.com</tt:IPv4Address></tt:NTPManual>"
            "</tds:NTPInformation>"
            "</tds:GetNTPResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_hostname(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetHostnameResponse>"
            "<tds:HostnameInformation>"
            "<tt:FromDHCP>false</tt:FromDHCP>"
            "<tt:Name>RTSP-ONVIF-Bridge</tt:Name>"
            "</tds:HostnameInformation>"
            "</tds:GetHostnameResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_zero_configuration(self):
         return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetZeroConfigurationResponse>"
            "<tds:ZeroConfiguration>"
            "<tt:InterfaceToken>eth0</tt:InterfaceToken>"
            "<tt:Enabled>false</tt:Enabled>"
            "<tt:Addresses>169.254.1.1</tt:Addresses>"
            "</tds:ZeroConfiguration>"
            "</tds:GetZeroConfigurationResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_discovery_mode(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetDiscoveryModeResponse>"
            "<tds:DiscoveryMode>Discoverable</tds:DiscoveryMode>"
            "</tds:GetDiscoveryModeResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_geo_location(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetGeoLocationResponse>"
            # Return empty or dummy location to satisfy request
            "</tds:GetGeoLocationResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_services(self):
        media_xaddr = f"http://{self.host}:{self.port}{self.media_service_path}"
        device_xaddr = f"http://{self.host}:{self.port}{self.device_service_path}"
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<tds:GetServicesResponse>"
            f"<tds:Service><tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace><tds:XAddr>{device_xaddr}</tds:XAddr><tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>"
            f"<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>{media_xaddr}</tds:XAddr><tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>"
            "</tds:GetServicesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_media_service_capabilities(self):
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetServiceCapabilitiesResponse>"
            "<trt:Capabilities SnapshotUri=\"false\" Rotation=\"false\" VideoSourceMode=\"false\" OSD=\"false\" TemporaryOSDText=\"false\">"
            "<tt:ProfileCapabilities MaximumNumberOfProfiles=\"10\"></tt:ProfileCapabilities>"
            "<tt:StreamingCapabilities RTPMulticast=\"false\" RTP_TCP=\"true\" RTP_RTSP_TCP=\"true\"></tt:StreamingCapabilities>"
            "</trt:Capabilities>"
            "</trt:GetServiceCapabilitiesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_video_sources(self):
        sources_xml = ""
        if 'monitor' in self.visible_profiles:
            sources_xml += (
                "<trt:VideoSources token=\"Monitor_src\">"
                "<tt:Framerate>24</tt:Framerate>"
                "<tt:Resolution><tt:Width>720</tt:Width><tt:Height>720</tt:Height></tt:Resolution>"
                "</trt:VideoSources>"
            )
        if 'filter' in self.visible_profiles:
            sources_xml += (
                "<trt:VideoSources token=\"Profile1_src\">"
                "<tt:Framerate>24</tt:Framerate>"
                "<tt:Resolution><tt:Width>720</tt:Width><tt:Height>576</tt:Height></tt:Resolution>"
                "</trt:VideoSources>"
            )
            
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetVideoSourcesResponse>"
            f"{sources_xml}"
            "</trt:GetVideoSourcesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_snapshot_uri(self, token):
        # Returns a dummy snapshot URI. 
        # ODM requires this call to succeed even if the image fetch fails later.
        uri = f"http://{self.host}:{self.port}/snapshot.jpg"
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetSnapshotUriResponse>"
            "<trt:MediaUri>"
            f"<tt:Uri>{uri}</tt:Uri>"
            "<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
            "<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>"
            "<tt:Timeout>PT60S</tt:Timeout>"
            "</trt:MediaUri>"
            "</trt:GetSnapshotUriResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_video_encoder_configuration_options(self, user_agent: str = ''):
        enc = self.codec
        
        h264_options = (
            "<tt:H264>"
            "<tt:ResolutionsAvailable><tt:Width>720</tt:Width><tt:Height>576</tt:Height></tt:ResolutionsAvailable>"
            "<tt:ResolutionsAvailable><tt:Width>720</tt:Width><tt:Height>720</tt:Height></tt:ResolutionsAvailable>"
            "<tt:GovLengthRange><tt:Min>1</tt:Min><tt:Max>100</tt:Max></tt:GovLengthRange>"
            "<tt:FrameRateRange><tt:Min>1</tt:Min><tt:Max>60</tt:Max></tt:FrameRateRange>"
            "<tt:EncodingIntervalRange><tt:Min>1</tt:Min><tt:Max>10</tt:Max></tt:EncodingIntervalRange>"
            "<tt:H264ProfilesSupported>High</tt:H264ProfilesSupported>"
            "</tt:H264>"
        )
        
        h265_options = (
            "<tt:H265>"
            "<tt:ResolutionsAvailable><tt:Width>720</tt:Width><tt:Height>576</tt:Height></tt:ResolutionsAvailable>"
            "<tt:ResolutionsAvailable><tt:Width>720</tt:Width><tt:Height>720</tt:Height></tt:ResolutionsAvailable>"
            "<tt:GovLengthRange><tt:Min>1</tt:Min><tt:Max>100</tt:Max></tt:GovLengthRange>"
            "<tt:FrameRateRange><tt:Min>1</tt:Min><tt:Max>60</tt:Max></tt:FrameRateRange>"
            "<tt:EncodingIntervalRange><tt:Min>1</tt:Min><tt:Max>10</tt:Max></tt:EncodingIntervalRange>"
            "<tt:H265ProfilesSupported>Main</tt:H265ProfilesSupported>"
            "</tt:H265>"
        )
        
        options_content = ""
        if enc == 'H265':
            options_content = h265_options
        else:
            options_content = h264_options

        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetVideoEncoderConfigurationOptionsResponse>"
            "<trt:Options>"
            "<tt:QualityRange><tt:Min>0</tt:Min><tt:Max>10</tt:Max></tt:QualityRange>"
            f"{options_content}"
            "</trt:Options>"
            "</trt:GetVideoEncoderConfigurationOptionsResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_video_source_configuration(self, token):
        # Determine which config to return based on token
        # Defaults to monitor_vsc if unknown
        if token == 'filter_vsc' or token == 'Profile1_vsc':
            return (
                "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
                "<s:Body>"
                "<trt:GetVideoSourceConfigurationResponse>"
                "<trt:Configuration token=\"Profile1_vsc\">"
                "<tt:Name>Profile1_vsc</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                "<tt:SourceToken>Profile1_src</tt:SourceToken>"
                "<tt:Bounds x=\"0\" y=\"0\" width=\"720\" height=\"576\"></tt:Bounds>"
                "</trt:Configuration>"
                "</trt:GetVideoSourceConfigurationResponse>"
                "</s:Body></s:Envelope>"
            )
        else:
            return (
                "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
                "<s:Body>"
                "<trt:GetVideoSourceConfigurationResponse>"
                "<trt:Configuration token=\"Monitor_vsc\">"
                "<tt:Name>Monitor_vsc</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                "<tt:SourceToken>Monitor_src</tt:SourceToken>"
                "<tt:Bounds x=\"0\" y=\"0\" width=\"720\" height=\"576\"></tt:Bounds>"
                "</trt:Configuration>"
                "</trt:GetVideoSourceConfigurationResponse>"
                "</s:Body></s:Envelope>"
            )

    def _soap_video_encoder_configuration(self, token, user_agent: str = ''):
        encoding = self.codec
        codec_block = self._profile_encoder_xml(encoding)

        if token == 'filter_vec' or token == 'Profile1_vec':
            return (
                "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
                "<s:Body>"
                "<trt:GetVideoEncoderConfigurationResponse>"
                "<trt:Configuration token=\"Profile1_vec\">"
                "<tt:Name>Profile1_vec</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                f"<tt:Encoding>{encoding}</tt:Encoding>"
                "<tt:Resolution><tt:Width>720</tt:Width><tt:Height>576</tt:Height></tt:Resolution>"
                "<tt:Quality>5.0</tt:Quality>"
                "<tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>4096</tt:BitrateLimit></tt:RateControl>"
                f"{codec_block}"
                "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address><tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>"
                "<tt:SessionTimeout>PT60S</tt:SessionTimeout>"
                "</trt:Configuration>"
                "</trt:GetVideoEncoderConfigurationResponse>"
                "</s:Body></s:Envelope>"
            )
        else:
            return (
                "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
                "<s:Body>"
                "<trt:GetVideoEncoderConfigurationResponse>"
                "<trt:Configuration token=\"Monitor_vec\">"
                "<tt:Name>Monitor_vec</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                f"<tt:Encoding>{encoding}</tt:Encoding>"
                "<tt:Resolution><tt:Width>720</tt:Width><tt:Height>720</tt:Height></tt:Resolution>"
                "<tt:Quality>5.0</tt:Quality>"
                "<tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>4096</tt:BitrateLimit></tt:RateControl>"
                f"{codec_block}"
                "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address><tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>"
                "<tt:SessionTimeout>PT60S</tt:SessionTimeout>"
                "</trt:Configuration>"
                "</trt:GetVideoEncoderConfigurationResponse>"
                "</s:Body></s:Envelope>"
            )

    def _generate_profile_xml_content(self, token, encoding: str = 'H264'):
        # Profile Name and Token
        p_token = token
        p_name = token
        
        # Source Config Token
        vsc_token = f"{p_token}_vsc"
        src_token = f"{p_token}_src"
        
        # Encoder Config Token
        vec_token = f"{p_token}_vec"
        
        # Dimensions
        width = 720
        height = 576
        
        enc = (encoding or 'H264').upper()
        codec_block = self._profile_encoder_xml(enc)
        return (
            f"<trt:Profiles fixed=\"true\" token=\"{p_token}\">"
              f"<tt:Name>{p_name}</tt:Name>"
              f"<tt:VideoSourceConfiguration token=\"{vsc_token}\">"
                f"<tt:Name>{vsc_token}</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                f"<tt:SourceToken>{src_token}</tt:SourceToken>"
                f"<tt:Bounds x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\"></tt:Bounds>"
              "</tt:VideoSourceConfiguration>"
              f"<tt:VideoEncoderConfiguration token=\"{vec_token}\">"
                f"<tt:Name>{vec_token}</tt:Name>"
                "<tt:UseCount>1</tt:UseCount>"
                f"<tt:Encoding>{enc}</tt:Encoding>"
                f"<tt:Resolution><tt:Width>{width}</tt:Width><tt:Height>{height}</tt:Height></tt:Resolution>"
                "<tt:Quality>5.0</tt:Quality>"
                "<tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>4096</tt:BitrateLimit></tt:RateControl>"
                f"{codec_block}"
                "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address><tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>"
                "<tt:SessionTimeout>PT60S</tt:SessionTimeout>"
              "</tt:VideoEncoderConfiguration>"
            "</trt:Profiles>"
        )

    def _soap_profile(self, token, user_agent: str = ''):
        enc = self.codec
        codec_block = self._profile_encoder_xml(enc)
        # Profile Name and Token
        p_token = token if token in ['monitor', 'filter'] else 'monitor'
        p_name = p_token
        
        # Source Config Token
        vsc_token = f"{p_token}_vsc"
        src_token = f"{p_token}_src"
        
        # Encoder Config Token
        vec_token = f"{p_token}_vec"
        
        # Dimensions
        width = 720
        height = 576
        if p_token == 'monitor':
            height = 720
        
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetProfileResponse>"
            f"<trt:Profile fixed=\"true\" token=\"{p_token}\">"
            f"<tt:Name>{p_name}</tt:Name>"
            f"<tt:VideoSourceConfiguration token=\"{vsc_token}\">"
            f"<tt:Name>{vsc_token}</tt:Name>"
            "<tt:UseCount>1</tt:UseCount>"
            f"<tt:SourceToken>{src_token}</tt:SourceToken>"
            f"<tt:Bounds x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\"></tt:Bounds>"
            "</tt:VideoSourceConfiguration>"
            f"<tt:VideoEncoderConfiguration token=\"{vec_token}\">"
            f"<tt:Name>{vec_token}</tt:Name>"
            "<tt:UseCount>1</tt:UseCount>"
            f"<tt:Encoding>{enc}</tt:Encoding>"
            f"<tt:Resolution><tt:Width>{width}</tt:Width><tt:Height>{height}</tt:Height></tt:Resolution>"
            "<tt:Quality>5.0</tt:Quality>"
            "<tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1</tt:EncodingInterval><tt:BitrateLimit>4096</tt:BitrateLimit></tt:RateControl>"
            f"{codec_block}"
            "<tt:Multicast><tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address><tt:Port>0</tt:Port><tt:TTL>1</tt:TTL><tt:AutoStart>false</tt:AutoStart></tt:Multicast>"
            "<tt:SessionTimeout>PT60S</tt:SessionTimeout>"
            "</tt:VideoEncoderConfiguration>"
            "</trt:Profile>"
            "</trt:GetProfileResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_profiles(self, user_agent: str = ''):
        encoding = self.codec
        profiles_xml = ""
        
        if 'monitor' in self.visible_profiles:
            profiles_xml += self._generate_profile_xml_content('Monitor', encoding)
        
        if 'filter' in self.visible_profiles:
            profiles_xml += self._generate_profile_xml_content('Profile1', encoding)
        
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetProfilesResponse>"
            f"{profiles_xml}"
            "</trt:GetProfilesResponse>"
            "</s:Body></s:Envelope>"
        )

    def _soap_stream_uri(self, token, user_agent=''):
        # 即使cam_filter.py传入了包含凭证的URL，我们也要确保返回的XML是正确的。
        # 如果 self.monitor_rtsp / self.filter_rtsp 已经包含了正确的凭证和IP，直接返回即可。
        # 但为了稳健，我们可以打印一下当前的URL。
        
        # Robust token matching
        t = token.lower() if token else ''
        
        # Logic to distinguish between monitor and filter based on visible_profiles or token
        # If we are the monitor server (18000), we should prefer monitor stream
        # If we are the filter server (18001), we should prefer filter stream
        
        if 'monitor' in self.visible_profiles:
             # We are likely the monitor instance (18000)
             if t == 'monitor' or t == 'profile1': # Handle Profile1 request on Monitor instance gracefully?
                 uri = self.monitor_rtsp
             else:
                 uri = self.monitor_rtsp # Default to monitor
        elif 'filter' in self.visible_profiles:
             # We are likely the filter instance (18001)
             uri = self.filter_rtsp # Always filter for this instance
        else:
            # Fallback (legacy behavior)
            if t == 'monitor':
                uri = self.monitor_rtsp
            else:
                uri = self.filter_rtsp
            
        # print(f"[ONVIF] Returning Stream URI for token {token}: {uri}")
        return (
            "<s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:trt=\"http://www.onvif.org/ver10/media/wsdl\" xmlns:tt=\"http://www.onvif.org/ver10/schema\">"
            "<s:Body>"
            "<trt:GetStreamUriResponse>"
            "<trt:MediaUri>"
            f"<tt:Uri>{uri}</tt:Uri>"
            "<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
            "<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>"
            "<tt:Timeout>PT60S</tt:Timeout>"
            "</trt:MediaUri>"
            "</trt:GetStreamUriResponse>"
            "</s:Body></s:Envelope>"
        )


class WsDiscoveryResponder:
    def __init__(self, device_service_url, uuid_str=None):
        self.device_service_url = device_service_url
        # Use a fixed UUID to ensure consistent device identification
        # This prevents duplicate devices in clients that cache by UUID
        self.uuid = "12345678-1234-5678-1234-567812345678"
        if uuid_str:
            self.uuid = uuid_str
            
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _run(self):
        mgrp = '239.255.255.250'
        mport = 3702
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        try:
            s.bind(('', mport))
        except Exception:
            # Fallback for Windows or occupied port, though unlikely for 3702 multicast
            return
            
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(mgrp) + socket.inet_aton('0.0.0.0'))
        except Exception:
            pass

        # Enable broadcasting just in case
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass

        while self.running:
            try:
                data, addr = s.recvfrom(8192)
                if b'Probe' in data or b'probe' in data:
                    # Extract MessageID from Probe to use as RelatesTo
                    msg_id = ""
                    try:
                        msg_id_start = data.find(b'<wsa:MessageID>')
                        if msg_id_start == -1:
                             msg_id_start = data.find(b'<a:MessageID>')
                        if msg_id_start != -1:
                            # find closing tag
                            end_tag = b'</wsa:MessageID>'
                            msg_id_end = data.find(end_tag, msg_id_start)
                            if msg_id_end == -1:
                                end_tag = b'</a:MessageID>'
                                msg_id_end = data.find(end_tag, msg_id_start)
                                
                            if msg_id_end != -1:
                                # +15 is len('<wsa:MessageID>')
                                # Need to be careful about the actual tag length
                                tag_len = data.find(b'>', msg_id_start) - msg_id_start + 1
                                msg_id = data[msg_id_start + tag_len:msg_id_end].decode('utf-8')
                    except Exception:
                        pass
                    
                    # Log probe receipt for debugging (optional, can be removed)
                    # print(f"Received Probe from {addr}, MessageID: {msg_id}")

                    resp = self._probe_match(msg_id)
                    s.sendto(resp.encode('utf-8'), addr)
            except Exception:
                continue

    def _probe_match(self, relates_to):
        return (
            "<SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://www.w3.org/2003/05/soap-envelope\" "
            "xmlns:wsa=\"http://schemas.xmlsoap.org/ws/2004/08/addressing\" "
            "xmlns:wsdd=\"http://schemas.xmlsoap.org/ws/2005/04/discovery\" "
            "xmlns:dn=\"http://www.onvif.org/ver10/network/wsdl\" "
            "xmlns:tds=\"http://www.onvif.org/ver10/device/wsdl\">"
            "<SOAP-ENV:Header>"
            "<wsa:MessageID>urn:uuid:" + str(uuid.uuid4()) + "</wsa:MessageID>"
            "<wsa:RelatesTo>" + relates_to + "</wsa:RelatesTo>"
            "<wsa:To>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:To>"
            "<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action>"
            "</SOAP-ENV:Header>"
            "<SOAP-ENV:Body>"
            "<wsdd:ProbeMatches>"
            "<wsdd:ProbeMatch>"
            "<wsa:EndpointReference><wsa:Address>urn:uuid:" + self.uuid + "</wsa:Address></wsa:EndpointReference>"
            "<wsdd:Types>dn:NetworkVideoTransmitter tds:Device</wsdd:Types>"
            "<wsdd:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/Profile/Streaming onvif://www.onvif.org/hardware/Generic onvif://www.onvif.org/name/RTSP-ONVIF-Bridge</wsdd:Scopes>"
            "<wsdd:XAddrs>" + self.device_service_url + "</wsdd:XAddrs>"
            "<wsdd:MetadataVersion>1</wsdd:MetadataVersion>"
            "</wsdd:ProbeMatch>"
            "</wsdd:ProbeMatches>"
            "</SOAP-ENV:Body>"
            "</SOAP-ENV:Envelope>"
        )


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'


if __name__ == '__main__':
    import time
    import os
    
    # Config
    HOST = '0.0.0.0'
    PORT = int(os.environ.get('ONVIF_PORT', '18000'))
    
    # External Access Configuration (for FRP/NAT)
    # If using FRP, set these to your public IP/Domain and mapped ports.
    # Example: EXTERNAL_HOST = 'my.public.domain', EXTERNAL_ONVIF_PORT = 18000
    EXTERNAL_HOST = os.environ.get('EXTERNAL_HOST', None)
    EXTERNAL_ONVIF_PORT = int(os.environ.get('EXTERNAL_ONVIF_PORT', PORT))
    EXTERNAL_RTSP_PORT = int(os.environ.get('EXTERNAL_RTSP_PORT', 8554))

    DEVICE_SERVICE = '/onvif/device_service'
    MEDIA_SERVICE = '/onvif/media_service'
    
    local_ip = get_local_ip()
    print(f"Detected Local IP: {local_ip}")
    
    # Determine Advertising Host
    advertise_host = EXTERNAL_HOST if EXTERNAL_HOST else local_ip
    advertise_port = EXTERNAL_ONVIF_PORT
    
    # RTSP URLs
    # Use advertise_host for RTSP as well if external host is set
    rtsp_host = advertise_host
    rtsp_port = EXTERNAL_RTSP_PORT

    MONITOR_RTSP = f'rtsp://shadow:shadow123@{rtsp_host}:{rtsp_port}/monitor'
    FILTER_RTSP = f'rtsp://shadow:shadow123@{rtsp_host}:{rtsp_port}/filter'
    
    # Create Server
    onvif_server = OnvifHttpServer(HOST, PORT, advertise_host, advertise_port, DEVICE_SERVICE, MEDIA_SERVICE, MONITOR_RTSP, FILTER_RTSP)
    onvif_server.start()
    
    # Create Discovery
    device_url = f"http://{advertise_host}:{advertise_port}{DEVICE_SERVICE}"
    discovery = WsDiscoveryResponder(device_url)
    discovery.start()
    
    print(f"ONVIF Server started on {HOST}:{PORT}")
    print(f"Advertising as: {advertise_host}:{advertise_port}")
    print(f"Device Service: {device_url}")
    print("Press Ctrl+C to stop...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        onvif_server.stop()
        discovery.stop()
        print("Stopped.")
