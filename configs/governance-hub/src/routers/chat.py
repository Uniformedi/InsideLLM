"""Embed Mattermost chat under /governance/chat.

Mattermost runs behind nginx at /chat/. This router renders a thin wrapper page
that iframes the Mattermost UI so governance-hub users can chat without leaving
the admin console.

v2 TODO: Forward messages through DLP/Humility callbacks via Mattermost outgoing
webhooks + a signed receiver endpoint here.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import settings

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def chat_embed() -> HTMLResponse:
    if not settings.chat_enable:
        raise HTTPException(status_code=404, detail="Chat feature is not enabled")

    team = settings.chat_team_name
    channel = settings.chat_default_channel
    target = f"/chat/{team}/channels/{channel}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>InsideLLM — Team Chat</title>
<style>
  html, body {{ margin:0; padding:0; height:100%; background:#1a2234; }}
  iframe {{ width:100%; height:100vh; border:none; display:block; }}
</style>
</head>
<body>
<iframe src="{target}" allow="clipboard-read; clipboard-write; microphone; camera"></iframe>
</body>
</html>"""
    return HTMLResponse(content=html)
