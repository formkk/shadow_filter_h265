import requests
import hashlib
import base64
import datetime
import os
import random
import string

def generate_auth_header(username, password):
    # Generate Nonce
    nonce_raw = os.urandom(16)
    nonce = base64.b64encode(nonce_raw).decode('utf-8')
    
    # Generate Created timestamp
    created = datetime.datetime.utcnow().isoformat() + "Z"
    
    # Generate PasswordDigest
    # Digest = B64(SHA1(B64Decode(Nonce) + Created + Password))
    sha1 = hashlib.sha1()
    sha1.update(nonce_raw + created.encode('utf-8') + password.encode('utf-8'))
    digest = base64.b64encode(sha1.digest()).decode('utf-8')
    
    header = f"""<s:Header>
    <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
        <wsse:UsernameToken wsu:Id="UsernameToken-1">
            <wsse:Username>{username}</wsse:Username>
            <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>
            <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce}</wsse:Nonce>
            <wsu:Created>{created}</wsu:Created>
        </wsse:UsernameToken>
    </wsse:Security>
    </s:Header>"""
    return header

def test_authenticated_calls():
    # Note: Using localhost because we are running on the server
    url_device = "http://127.0.0.1:18000/onvif/device_service"
    url_media = "http://127.0.0.1:18000/onvif/media_service"
    
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    auth_header = generate_auth_header('shadow', 'password147')
    
    print("--- Testing GetServices (Authenticated) ---")
    body = f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
    {auth_header}
    <s:Body><tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices></s:Body></s:Envelope>"""
    
    try:
        r = requests.post(url_device, data=body, headers=headers)
        print(f"Status: {r.status_code}")
        if r.status_code != 200:
            print("Response:", r.text[:500])
        else:
            print("Response OK (truncated):", r.text[:200])
            if "tds:Service" in r.text:
                print("Found Services!")
            else:
                print("WARNING: No Services found in response")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing GetProfiles (Authenticated) ---")
    # Regenerate auth for new request to be safe with nonce/time
    auth_header = generate_auth_header('shadow', 'password147')
    
    body = f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
    {auth_header}
    <s:Body><trt:GetProfiles/></s:Body></s:Envelope>"""
    
    try:
        r = requests.post(url_media, data=body, headers=headers)
        print(f"Status: {r.status_code}")
        if r.status_code != 200:
            print("Response:", r.text[:500])
        else:
            print("Response Content:", r.text)
            if "trt:Profiles" in r.text:
                print("Found Profiles!")
            else:
                print("WARNING: No Profiles found in response")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing GetVideoSources (Authenticated) ---")
    auth_header = generate_auth_header('shadow', 'password147')
    body = f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
    {auth_header}
    <s:Body><trt:GetVideoSources/></s:Body></s:Envelope>"""
    
    try:
        r = requests.post(url_media, data=body, headers=headers)
        print(f"Status: {r.status_code}")
        if r.status_code != 200:
            print("Response:", r.text[:500])
        else:
            print("Response Content:", r.text)
            if "trt:VideoSources" in r.text:
                print("Found VideoSources!")
            else:
                print("WARNING: No VideoSources found in response")
    except Exception as e:
        print(f"Error: {e}")

    print("\n--- Testing GetStreamUri (Authenticated) ---")
    auth_header = generate_auth_header('shadow', 'password147')
    body = f"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
    {auth_header}
    <s:Body>
        <trt:GetStreamUri>
            <trt:StreamSetup>
                <tt:Stream>RTP-Unicast</tt:Stream>
                <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
            </trt:StreamSetup>
            <trt:ProfileToken>filter</trt:ProfileToken>
        </trt:GetStreamUri>
    </s:Body>
    </s:Envelope>"""
    
    try:
        r = requests.post(url_media, data=body, headers=headers)
        print(f"Status: {r.status_code}")
        if r.status_code != 200:
            print("Response:", r.text[:500])
        else:
            print("Response Content:", r.text)
            if "tt:Uri" in r.text:
                print("Found URI!")
            else:
                print("WARNING: No URI found in response")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_authenticated_calls()
