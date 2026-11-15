"""Model Context Protocol (MCP) server for PeakCut.
Run with:  python -m studio.mcp

Exposes PeakCut's video clipping, live stream monitoring, and publishing capabilities
to AI agents (Claude Desktop, Hermes, Cursor, OpenCode) over stdio JSON-RPC 2.0.
"""
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

DEFAULT_URL = os.environ.get("PEAKCUT_URL") or "http://127.0.0.1:8765"
SESSION_COOKIE = os.environ.get("PEAKCUT_SESSION") or os.environ.get("PEAKCUT_COOKIE") or ""

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "peakcut", "version": "1.0.0"}


def _log(msg: str):
    """Write informational or error messages to stderr to keep stdout clean for JSON-RPC."""
    sys.stderr.write(f"[peakcut-mcp] {msg}\n")
    sys.stderr.flush()


class PeakCutClient:
    """HTTP client communicating with the live PeakCut server."""

    def __init__(self, base_url: str = DEFAULT_URL, session_cookie: str = SESSION_COOKIE):
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "http://127.0.0.1:8765"
        self.headers = {
            "Origin": origin,
            "User-Agent": "PeakCut-MCP/1.0",
        }
        self.cookies: Dict[str, str] = {}
        if session_cookie:
            self.cookies["peakcut_session"] = session_cookie

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, headers=self.headers, cookies=self.cookies, timeout=60.0)

    def _check(self, r: httpx.Response) -> Dict[str, Any]:
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = r.text
            try:
                data = r.json()
                if "detail" in data:
                    detail = str(data["detail"])
            except Exception:
                pass
            raise RuntimeError(f"PeakCut API error ({r.status_code}): {detail}") from e
        return r.json()

    def get_status(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/status"))

    def preview_url(self, url: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/preview", params={"url": url}))

    def list_jobs(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/jobs"))

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get(f"/api/jobs/{job_id}"))

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.delete(f"/api/jobs/{job_id}"))

    def delete_clip(self, job_id: str, clip_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.delete(f"/api/jobs/{job_id}/clips/{clip_id}"))

    def get_clip_media(self, job_id: str, clip_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        clip = next((c for c in job.get("clips", []) if c.get("id") == clip_id), None)
        if not clip:
            raise ValueError(f"Clip '{clip_id}' not found in job '{job_id}'")

        media_url = f"{self.base_url}/media/{job_id}/{clip_id}.mp4"
        thumbnail_url = f"{self.base_url}/media/{job_id}/{clip_id}.jpg"
        download_url = f"{self.base_url}/media/{job_id}/{clip_id}.mp4?download=1"

        local_mp4: Optional[str] = None
        local_ass: Optional[str] = None
        data_dir = Path(os.environ.get("PEAKCUT_DATA") or "data")
        matches = list(data_dir.glob(f"users/*/jobs/{job_id}/clips/{clip_id}.mp4"))
        if matches and matches[0].is_file():
            local_mp4 = str(matches[0].resolve())
            ass_candidate = matches[0].with_suffix(".ass")
            if ass_candidate.is_file():
                local_ass = str(ass_candidate.resolve())

        return {
            "job_id": job_id,
            "clip_id": clip_id,
            "status": clip.get("status"),
            "media_url": media_url,
            "thumbnail_url": thumbnail_url,
            "download_url": download_url,
            "file_path": local_mp4,
            "subtitles_path": local_ass,
            "clip": clip,
        }

    def submit_video_url(self, url: str, creator: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"url": url}
        if creator:
            payload["creator"] = creator
        if options:
            payload["options"] = options
        with self._client() as client:
            return self._check(client.post("/api/jobs", json=payload))

    def upload_local_video(self, file_path: str, creator: Optional[str] = None) -> Dict[str, Any]:
        p = Path(file_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Video file not found: {file_path}")
        with open(p, "rb") as f:
            files = {"file": (p.name, f, "video/mp4")}
            data = {"creator": creator or "", "options": "{}"}
            with self._client() as client:
                return self._check(client.post("/api/upload", files=files, data=data, timeout=300.0))

    def render_clip(
        self,
        job_id: str,
        clip_id: str,
        style: Optional[str] = None,
        layout: Optional[str] = None,
        hook: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if style:
            payload["style"] = style
        if layout:
            payload["layout"] = layout
        if hook is not None:
            payload["hook"] = hook
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if start is not None:
            payload["start"] = start
        if end is not None:
            payload["end"] = end
        with self._client() as client:
            return self._check(client.post(f"/api/jobs/{job_id}/clips/{clip_id}/render", json=payload))

    def export_clips_archive(self, clip_pairs: List[str], output_path: Optional[str] = None) -> Dict[str, Any]:
        ids = ",".join(clip_pairs)
        archive_url = f"{self.base_url}/api/clips.zip?ids={ids}"
        dest_path: Optional[str] = None
        if output_path:
            p = Path(output_path).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._client() as client:
                with client.stream("GET", "/api/clips.zip", params={"ids": ids}) as r:
                    r.raise_for_status()
                    with open(p, "wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
            dest_path = str(p)
        return {
            "archive_url": archive_url,
            "file_path": dest_path,
            "clips_count": len(clip_pairs),
        }

    def list_creators(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/creators"))

    def create_creator(
        self, name: str, channel: Optional[str] = None, channels: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": name}
        if channel:
            payload["channel"] = channel
        if channels:
            payload["channels"] = channels
        with self._client() as client:
            return self._check(client.post("/api/creators", json=payload))

    def start_live_monitoring(self, creator_id: str, platform: str = "", channel: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if platform:
            payload["platform"] = platform
        if channel:
            payload["channel"] = channel
        with self._client() as client:
            return self._check(client.post(f"/api/creators/{creator_id}/live", json=payload))

    def capture_live_moment(self, job_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.post(f"/api/live/{job_id}/clip"))

    def stop_live_monitoring(self, job_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.post(f"/api/live/{job_id}/stop"))

    def list_accounts(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/accounts"))

    def publish_clip(self, clip_id: str, account_id: str, caption: str = "") -> Dict[str, Any]:
        payload = {"clip_id": clip_id, "account_id": account_id, "caption": caption}
        with self._client() as client:
            return self._check(client.post("/api/posts", json=payload))

    def preview_channel(self, url: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/channel-preview", params={"url": url}))

    def update_creator(self, creator_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.put(f"/api/creators/{creator_id}", json=updates))

    def delete_creator(self, creator_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.delete(f"/api/creators/{creator_id}"))

    def disconnect_account(self, account_id: str) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.delete(f"/api/accounts/{account_id}"))

    def manage_post(self, post_id: str, action: str) -> Dict[str, Any]:
        if action not in ("cancel", "retry"):
            raise ValueError("Post action must be 'cancel' or 'retry'")
        with self._client() as client:
            return self._check(client.post(f"/api/posts/{post_id}/{action}"))

    def get_publishing_overview(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/overview"))

    def get_ai_usage(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/usage"))

    def get_ai_config(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/ai"))

    def update_ai_config(
        self, provider: str, models: Any, base_url: str = "", key: Optional[str] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"provider": provider, "models": models, "base_url": base_url}
        if key is not None:
            payload["key"] = key
        with self._client() as client:
            return self._check(client.put("/api/ai", json=payload))

    def list_ai_models(
        self, provider: Optional[str] = None, base_url: Optional[str] = None, key: Optional[str] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if provider:
            payload["provider"] = provider
        if base_url:
            payload["base_url"] = base_url
        if key:
            payload["key"] = key
        with self._client() as client:
            return self._check(client.post("/api/ai/models", json=payload))

    def test_ai_connection(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.post("/api/ai/test"))

    def get_notifications(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.get("/api/notifications"))

    def mark_notifications_read(self) -> Dict[str, Any]:
        with self._client() as client:
            return self._check(client.post("/api/notifications/read"))

    def bulk_delete(self, videos: Optional[List[str]] = None, clips: Optional[List[List[str]]] = None) -> Dict[str, Any]:
        payload = {"videos": videos or [], "clips": clips or []}
        with self._client() as client:
            return self._check(client.post("/api/bulk/delete", json=payload))


TOOLS = [
    {
        "name": "peakcut_get_system_status",
        "description": "Get PeakCut system telemetry: server status, current user, queue load, limits, and active AI model.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_preview_url",
        "description": "Preview a video URL before clipping: retrieves title, creator/uploader, duration, and thumbnail without downloading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "YouTube, Twitch, or Kick link to preview.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "peakcut_preview_channel",
        "description": "Preview a YouTube, Twitch, or Kick channel: profile info, channel link, and details before creating or editing a workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Channel URL or handle (YouTube, Twitch, or Kick).",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "peakcut_list_jobs",
        "description": "List all video clipping jobs and their current processing status (transcribing, clipping, done).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_get_job",
        "description": "Get full details of a clipping job: video metadata, transcript, and generated clip highlights.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The unique ID of the job.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "peakcut_delete_job",
        "description": "Delete a completed or failed clipping job and free disk space.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The unique ID of the job to delete.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "peakcut_delete_clip",
        "description": "Delete a specific generated clip from a job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job ID owning the clip.",
                },
                "clip_id": {
                    "type": "string",
                    "description": "The clip ID to delete (e.g. clip01).",
                },
            },
            "required": ["job_id", "clip_id"],
        },
    },
    {
        "name": "peakcut_bulk_delete",
        "description": "Bulk delete multiple video jobs and individual clips in a single operation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "videos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of video job IDs to delete completely.",
                },
                "clips": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Pairs of [job_id, clip_id].",
                    },
                    "description": "List of [job_id, clip_id] pairs to delete.",
                },
            },
        },
    },
    {
        "name": "peakcut_get_clip_media",
        "description": "Get downloadable URLs and local absolute file paths for a rendered clip, thumbnail, and subtitle files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job ID owning the clip.",
                },
                "clip_id": {
                    "type": "string",
                    "description": "The clip highlight ID (e.g. clip01).",
                },
            },
            "required": ["job_id", "clip_id"],
        },
    },
    {
        "name": "peakcut_submit_video_url",
        "description": "Submit a YouTube, Twitch, or Kick video URL to PeakCut for transcription and AI highlight clipping.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full link to a YouTube, Twitch, or Kick video.",
                },
                "creator": {
                    "type": "string",
                    "description": "Optional creator workspace ID or name to organize this video.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "peakcut_upload_local_video",
        "description": "Upload a local video file from disk into PeakCut for processing into vertical clips.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to the video file on disk (e.g. /home/user/video.mp4).",
                },
                "creator": {
                    "type": "string",
                    "description": "Optional creator workspace ID or name.",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "peakcut_render_clip",
        "description": "Render or re-render a candidate clip into a vertical 9:16 video with animated karaoke captions and customizable typography/metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job ID owning the clip.",
                },
                "clip_id": {
                    "type": "string",
                    "description": "The clip highlight ID to render.",
                },
                "style": {
                    "type": "string",
                    "description": "Caption typography preset: 'bounce' (yellow animated), 'hype' (high-contrast punch), 'clean' (subtle white).",
                    "enum": ["bounce", "hype", "clean", "s1", "s2", "s3"],
                },
                "layout": {
                    "type": "string",
                    "description": "Visual layout: 'blur' (16:9 on blurred background), 'zoom' (zoomed + blur), 'crop' (9:16 centre crop).",
                    "enum": ["blur", "zoom", "crop"],
                },
                "hook": {
                    "type": "string",
                    "description": "Custom hook banner text shown at the beginning (up to 60 characters).",
                },
                "title": {
                    "type": "string",
                    "description": "Custom title for the clip (up to 100 characters).",
                },
                "description": {
                    "type": "string",
                    "description": "Custom description text (up to 2000 characters).",
                },
                "start": {
                    "type": "number",
                    "description": "Optional custom start timestamp in seconds.",
                },
                "end": {
                    "type": "number",
                    "description": "Optional custom end timestamp in seconds.",
                },
            },
            "required": ["job_id", "clip_id"],
        },
    },
    {
        "name": "peakcut_export_clips_archive",
        "description": "Export multiple clips as a single downloadable ZIP archive, optionally saving to a local disk path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clip_pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 'job_id.clip_id' pairs to include in the ZIP (e.g. ['20261115-135846-3497ea5560.clip01']).",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional local file path to save the downloaded zip archive (e.g. /home/user/clips.zip).",
                },
            },
            "required": ["clip_pairs"],
        },
    },
    {
        "name": "peakcut_list_creators",
        "description": "List all configured creator workspaces, associated channels, and posting settings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_create_creator",
        "description": "Create a new creator workspace in PeakCut.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Creator or channel name.",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional primary channel link (YouTube, Twitch, Kick).",
                },
                "channels": {
                    "type": "object",
                    "description": "Optional map of platform to channel URL, e.g. {'youtube': 'https://youtube.com/@channel'}.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "peakcut_update_creator",
        "description": "Update settings, thresholds, and channels for an existing creator workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "creator_id": {
                    "type": "string",
                    "description": "ID of the creator workspace to update.",
                },
                "updates": {
                    "type": "object",
                    "description": "Dictionary of fields to update (name, channel, channels, style, layout, min_len, max_len, min_score, auto_watch, autopost, daily_cap, post_min_score, etc.).",
                },
            },
            "required": ["creator_id", "updates"],
        },
    },
    {
        "name": "peakcut_delete_creator",
        "description": "Delete a creator workspace and remove its associated configurations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "creator_id": {
                    "type": "string",
                    "description": "ID of the creator workspace to delete.",
                },
            },
            "required": ["creator_id"],
        },
    },
    {
        "name": "peakcut_start_live_monitoring",
        "description": "Start live stream recording and highlight clipping for a creator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "creator_id": {
                    "type": "string",
                    "description": "The ID of the creator whose stream should be monitored.",
                },
                "platform": {
                    "type": "string",
                    "description": "Optional platform: 'youtube', 'twitch', or 'kick'.",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional channel handle or link if not already saved on creator.",
                },
            },
            "required": ["creator_id"],
        },
    },
    {
        "name": "peakcut_capture_live_moment",
        "description": "Trigger an immediate clip capture from an active rolling live stream buffer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The live job ID currently recording.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "peakcut_stop_live_monitoring",
        "description": "Stop an ongoing live stream recording and finalize its highlights.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The active live job ID to terminate.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "peakcut_list_connected_accounts",
        "description": "List connected social media publishing accounts (YouTube Shorts, TikTok, Instagram).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_disconnect_account",
        "description": "Disconnect and remove a connected social media account (YouTube, TikTok, Instagram).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "The ID of the connected account to disconnect.",
                },
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "peakcut_publish_clip",
        "description": "Queue or publish a rendered clip to a connected social media account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clip_id": {
                    "type": "string",
                    "description": "ID of the clip to publish.",
                },
                "account_id": {
                    "type": "string",
                    "description": "Target connected account ID from peakcut_list_connected_accounts.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional post caption or description with hashtags.",
                },
            },
            "required": ["clip_id", "account_id"],
        },
    },
    {
        "name": "peakcut_manage_post",
        "description": "Manage an existing social media post item (cancel queued post or retry failed post).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "string",
                    "description": "The post ID to act upon.",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'cancel' to cancel a queued post, 'retry' to retry a failed post.",
                    "enum": ["cancel", "retry"],
                },
            },
            "required": ["post_id", "action"],
        },
    },
    {
        "name": "peakcut_get_publishing_overview",
        "description": "Get aggregated publishing metrics across all creators, accounts, and queue states.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_get_ai_usage",
        "description": "Get detailed AI token usage, request counts, and cost breakdown per creator and video.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_get_ai_config",
        "description": "Get current AI service configuration: active provider, configured model IDs, and base URL.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_update_ai_config",
        "description": "Update AI service configuration (provider, model IDs, base URL, API key).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "AI provider ID: 'gemini', 'openai', 'anthropic', 'openrouter', 'groq', 'xai', 'ollama', 'omniroute', or 'custom'.",
                },
                "models": {
                    "type": "string",
                    "description": "Comma-separated list of model IDs to try in order (e.g. 'gemini-2.5-flash').",
                },
                "base_url": {
                    "type": "string",
                    "description": "Base URL for custom or local endpoints (e.g. 'http://localhost:20128/v1').",
                },
                "key": {
                    "type": "string",
                    "description": "Optional API key for the service.",
                },
            },
            "required": ["provider", "models"],
        },
    },
    {
        "name": "peakcut_list_ai_models",
        "description": "Discover available model IDs from an AI service endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Optional provider ID (defaults to active provider).",
                },
                "base_url": {
                    "type": "string",
                    "description": "Optional base URL override.",
                },
                "key": {
                    "type": "string",
                    "description": "Optional API key to authenticate model discovery.",
                },
            },
        },
    },
    {
        "name": "peakcut_test_ai_connection",
        "description": "Send a lightweight verification request using active AI settings to verify key, endpoint, and model connectivity.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_get_notifications",
        "description": "Get in-app activity notifications (clip completions, render notices, errors).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "peakcut_mark_notifications_read",
        "description": "Mark all unread in-app activity notifications as read.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def dispatch_tool(client: PeakCutClient, name: str, args: Dict[str, Any]) -> Any:
    """Execute a tool call against the PeakCut client and return JSON-serializable content."""
    if name == "peakcut_get_system_status":
        return client.get_status()
    elif name == "peakcut_preview_url":
        return client.preview_url(str(args.get("url", "")))
    elif name == "peakcut_list_jobs":
        return client.list_jobs()
    elif name == "peakcut_get_job":
        return client.get_job(str(args.get("job_id", "")))
    elif name == "peakcut_delete_job":
        return client.delete_job(str(args.get("job_id", "")))
    elif name == "peakcut_delete_clip":
        return client.delete_clip(str(args.get("job_id", "")), str(args.get("clip_id", "")))
    elif name == "peakcut_bulk_delete":
        return client.bulk_delete(videos=args.get("videos"), clips=args.get("clips"))
    elif name == "peakcut_preview_channel":
        return client.preview_channel(str(args.get("url", "")))
    elif name == "peakcut_get_clip_media":
        return client.get_clip_media(str(args.get("job_id", "")), str(args.get("clip_id", "")))
    elif name == "peakcut_submit_video_url":
        return client.submit_video_url(str(args.get("url", "")), creator=args.get("creator"))
    elif name == "peakcut_upload_local_video":
        return client.upload_local_video(str(args.get("file_path", "")), creator=args.get("creator"))
    elif name == "peakcut_render_clip":
        start_val = float(args["start"]) if "start" in args and args["start"] is not None else None
        end_val = float(args["end"]) if "end" in args and args["end"] is not None else None
        return client.render_clip(
            str(args.get("job_id", "")),
            str(args.get("clip_id", "")),
            style=args.get("style"),
            layout=args.get("layout"),
            hook=args.get("hook"),
            title=args.get("title"),
            description=args.get("description"),
            start=start_val,
            end=end_val,
        )
    elif name == "peakcut_export_clips_archive":
        return client.export_clips_archive(
            list(args.get("clip_pairs") or []), output_path=args.get("output_path")
        )
    elif name == "peakcut_list_creators":
        return client.list_creators()
    elif name == "peakcut_create_creator":
        return client.create_creator(
            str(args.get("name", "")), channel=args.get("channel"), channels=args.get("channels")
        )
    elif name == "peakcut_update_creator":
        return client.update_creator(str(args.get("creator_id", "")), dict(args.get("updates") or {}))
    elif name == "peakcut_delete_creator":
        return client.delete_creator(str(args.get("creator_id", "")))
    elif name == "peakcut_start_live_monitoring":
        return client.start_live_monitoring(
            str(args.get("creator_id", "")), platform=str(args.get("platform", "")), channel=str(args.get("channel", ""))
        )
    elif name == "peakcut_capture_live_moment":
        return client.capture_live_moment(str(args.get("job_id", "")))
    elif name == "peakcut_stop_live_monitoring":
        return client.stop_live_monitoring(str(args.get("job_id", "")))
    elif name == "peakcut_list_connected_accounts":
        return client.list_accounts()
    elif name == "peakcut_disconnect_account":
        return client.disconnect_account(str(args.get("account_id", "")))
    elif name == "peakcut_publish_clip":
        return client.publish_clip(str(args.get("clip_id", "")), str(args.get("account_id", "")), caption=str(args.get("caption", "")))
    elif name == "peakcut_manage_post":
        return client.manage_post(str(args.get("post_id", "")), str(args.get("action", "")))
    elif name == "peakcut_get_publishing_overview":
        return client.get_publishing_overview()
    elif name == "peakcut_get_ai_usage":
        return client.get_ai_usage()
    elif name == "peakcut_get_ai_config":
        return client.get_ai_config()
    elif name == "peakcut_update_ai_config":
        return client.update_ai_config(
            str(args.get("provider", "")),
            args.get("models"),
            base_url=str(args.get("base_url") or ""),
            key=args.get("key"),
        )
    elif name == "peakcut_list_ai_models":
        return client.list_ai_models(
            provider=args.get("provider"), base_url=args.get("base_url"), key=args.get("key")
        )
    elif name == "peakcut_test_ai_connection":
        return client.test_ai_connection()
    elif name == "peakcut_get_notifications":
        return client.get_notifications()
    elif name == "peakcut_mark_notifications_read":
        return client.mark_notifications_read()
    else:
        raise ValueError(f"Unknown tool: {name}")


def handle_request(client: PeakCutClient, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC 2.0 request and return the response dictionary."""
    msg_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if not method:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32600, "message": "Invalid Request: missing method"}}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": SERVER_INFO,
            },
        }

    elif method == "notifications/initialized":
        # Notification: no response required
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": TOOLS,
            },
        }

    elif method == "tools/call":
        tool_name = str(params.get("name") or "")
        tool_args = params.get("arguments") or {}
        try:
            res = dispatch_tool(client, tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as e:
            _log(f"Error executing {tool_name}: {e}\n{traceback.format_exc()}")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                },
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def run_stdio_server(client: Optional[PeakCutClient] = None):
    """Main stdio loop reading JSON-RPC lines from stdin and writing responses to stdout."""
    active_client = client or PeakCutClient()
    _log(f"PeakCut MCP server started (endpoint: {active_client.base_url}). Listening on stdin...")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                req = json.loads(line)
            except json.JSONDecodeError as err:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {err}"}}
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
                continue

            resp = handle_request(active_client, req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as e:
            _log(f"Unhandled loop error: {e}\n{traceback.format_exc()}")

    _log("PeakCut MCP server stopped.")


if __name__ == "__main__":
    run_stdio_server()
