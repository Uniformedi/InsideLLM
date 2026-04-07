"""
title: DocForge - File Generation & Conversion
author: InsideLLM
version: 1.0.0
description: Generate and convert documents (DOCX, XLSX, PPTX, PDF, CSV, and more) from structured data.
"""

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, Field


class Valves(BaseModel):
    """Configuration for the DocForge tool."""

    docforge_url: str = Field(
        default="http://docforge:3000",
        description="DocForge service URL (internal Docker network)",
    )
    max_file_size_mb: int = Field(
        default=50,
        description="Maximum file size for conversion uploads (MB)",
    )
    enabled: bool = Field(
        default=True,
        description="Enable or disable the DocForge tool",
    )
    upload_dir: str = Field(
        default="/app/backend/data/uploads",
        description="Open WebUI uploads directory",
    )


class Tools:
    def __init__(self):
        self.valves = Valves()

    def generate_file(
        self,
        format: str,
        data: dict,
        filename: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Generate a document file from structured data.

        Supported formats and their data structures:
        - docx: {"title": "...", "sections": [{"heading": "...", "paragraphs": ["..."]}]}
        - xlsx: {"sheets": [{"name": "...", "headers": ["..."], "rows": [[...]]}]}
        - pptx: {"title": "...", "slides": [{"title": "...", "content": "...", "notes": "..."}]}
        - pdf:  {"title": "...", "content": "markdown or plain text"}
        - csv:  {"headers": ["..."], "rows": [[...]], "delimiter": ","}
        - json: {"content": <any JSON-serializable value>}
        - xml:  {"root": "rootElement", "content": <object>}
        - yaml: {"content": <any value>}
        - markdown: {"content": "markdown text"}
        - txt:  {"content": "plain text"}

        :param format: Output file format (docx, xlsx, pptx, pdf, csv, json, xml, yaml, markdown, txt)
        :param data: Structured data matching the format's schema (see above)
        :param filename: Optional output filename (auto-generated if empty)
        :return: A message with the download link for the generated file
        """
        if not self.valves.enabled:
            return "DocForge is currently disabled. Contact an administrator."

        url = f"{self.valves.docforge_url}/api/generate"
        payload = {"format": format, "data": data}
        if filename:
            payload["filename"] = filename

        try:
            resp = requests.post(url, json=payload, timeout=60)
        except requests.RequestException as e:
            return f"Error connecting to DocForge: {e}"

        if resp.status_code != 200:
            try:
                err = resp.json()
                return f"DocForge error: {err.get('error', resp.text)}"
            except Exception:
                return f"DocForge error (HTTP {resp.status_code}): {resp.text[:500]}"

        return self._save_and_link(resp, format, filename, __user__)

    def convert_file(
        self,
        file_url: str,
        target_format: str,
        __user__: dict = {},
    ) -> str:
        """
        Convert an uploaded file to a different format.

        Supported target formats: pdf, docx, xlsx, pptx, odt, ods, odp, csv, html, rtf, txt

        Common conversions:
        - DOCX to PDF, ODT to DOCX, XLSX to CSV, PPTX to PDF, etc.
        - LibreOffice handles the conversion, so most office format combinations work.

        :param file_url: URL or path to the source file (from a previous upload or message attachment)
        :param target_format: Target format to convert to (pdf, docx, xlsx, pptx, odt, ods, odp, csv, html, rtf, txt)
        :return: A message with the download link for the converted file
        """
        if not self.valves.enabled:
            return "DocForge is currently disabled. Contact an administrator."

        # Fetch the source file (HTTP URLs only — no local filesystem access)
        if not file_url.startswith(("http://", "https://")):
            return "Only HTTP/HTTPS URLs are supported. Use the file's Open WebUI URL."

        try:
            file_resp = requests.get(file_url, timeout=30)
            file_resp.raise_for_status()
            file_bytes = file_resp.content
            file_name = file_url.split("/")[-1].split("?")[0] or "upload"
        except Exception as e:
            return f"Error reading source file: {e}"

        if len(file_bytes) > self.valves.max_file_size_mb * 1024 * 1024:
            return f"File exceeds maximum size of {self.valves.max_file_size_mb} MB."

        url = f"{self.valves.docforge_url}/api/convert?targetFormat={target_format}"
        try:
            resp = requests.post(
                url,
                files={"file": (file_name, file_bytes)},
                timeout=120,
            )
        except requests.RequestException as e:
            return f"Error connecting to DocForge: {e}"

        if resp.status_code != 200:
            try:
                err = resp.json()
                return f"DocForge error: {err.get('error', resp.text)}"
            except Exception:
                return f"DocForge error (HTTP {resp.status_code}): {resp.text[:500]}"

        return self._save_and_link(resp, target_format, "", __user__)

    def _save_and_link(
        self,
        resp: requests.Response,
        format: str,
        filename: str,
        user: dict,
    ) -> str:
        """Save the response file and return a download link."""
        # Extract filename from Content-Disposition or generate one
        cd = resp.headers.get("Content-Disposition", "")
        if 'filename="' in cd:
            out_name = cd.split('filename="')[1].rstrip('"')
        elif filename:
            out_name = filename
        else:
            out_name = f"document-{int(time.time())}.{format}"

        # Sanitize filename — strip directory separators and path traversal
        out_name = re.sub(r'[/\\]', '_', out_name)
        out_name = out_name.lstrip('.')

        upload_dir = Path(self.valves.upload_dir).resolve()
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_id = str(uuid.uuid4())
        file_path = (upload_dir / f"{file_id}_{out_name}").resolve()
        if not str(file_path).startswith(str(upload_dir)):
            return "Error: invalid filename received from service."

        file_path.write_bytes(resp.content)

        user_name = user.get("name", "User")
        size_kb = len(resp.content) / 1024

        return (
            f"Generated **{out_name}** ({size_kb:.1f} KB) for {user_name}.\n\n"
            f"[Download {out_name}](/api/v1/files/{file_id}/content/{out_name})"
        )
