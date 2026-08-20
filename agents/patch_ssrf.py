import re

def add_ssrf_validator(file_path, url_field):
    with open(file_path, 'r') as f:
        content = f.read()
    
    if "urllib.parse" not in content:
        content = content.replace("import httpx", "import httpx\nfrom urllib.parse import urlparse")
    
    new_validator = f"""
    @validator("{url_field}")
    def validate_https_url(cls, v):
        if not v.startswith("https://"):
            raise ValueError("{url_field} must be an absolute HTTPS URL to prevent SSRF.")
        parsed = urlparse(v)
        hostname = (parsed.hostname or "").lower()
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or hostname.startswith("192.168.") or hostname.startswith("10."):
            raise ValueError(f"SSRF Attempt Blocked: {url_field} resolves to a private or loopback address.")
        return v
"""
    
    # Replace the existing validator
    content = re.sub(
        r'    @validator\("'+url_field+r'"\)\n    def validate_https_url.*?        return v',
        new_validator.strip('\n'),
        content,
        flags=re.DOTALL
    )
    
    with open(file_path, 'w') as f:
        f.write(content)

add_ssrf_validator('social_agent/mcp_tools/instagram.py', 'media_url')
add_ssrf_validator('social_agent/mcp_tools/tiktok.py', 'video_url')

