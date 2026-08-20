import re

files_and_targets = {
    'social_agent/mcp_tools/x_twitter.py': 'https://api.x.com/2/tweets',
    'social_agent/mcp_tools/instagram.py': 'https://graph.facebook.com/',
    'social_agent/mcp_tools/tiktok.py': 'https://open.tiktokapis.com/v2/',
    'social_agent/mcp_tools/web_search.py': 'https://api.tavily.com/search' 
}

for file_path, test_url in files_and_targets.items():
    with open(file_path, 'r') as f:
        content = f.read()

    if "import time" not in content:
        content = content.replace("import httpx", "import httpx\nimport time")

    # Replace the health_check completely to inject ping logic
    
    old_health_start = content.find("async def health_check(")
    old_health_end = content.find('if __name__ == "__main__":', old_health_start)
    
    if old_health_start != -1 and old_health_end != -1:
        new_fn = f"""async def health_check() -> Dict[str, Any]:
    \"\"\"Returns the operational status, version, and connection latency of the FastMCP connector.\"\"\"
    import time
    creds = await resolve_platform_credentials("{file_path.split("/")[-1].replace(".py", "")}") if not "{file_path}".endswith("web_search.py") else {{}}
    t0 = time.time()
    latency = -1
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.options("{test_url}")
            latency = int((time.time() - t0) * 1000)
    except Exception:
        pass

    return {{
        "status": "healthy",
        "service": "{file_path.split("/")[-1].replace(".py", "_mcp")}",
        "version": mcp.version,
        "auth_configured": bool(creds.get("access_token") and "mock" not in creds.get("access_token", "")),
        "latency_ms": latency,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }}

"""
        
        content = content[:old_health_start] + new_fn + content[old_health_end:]
        with open(file_path, 'w') as f:
            f.write(content)

