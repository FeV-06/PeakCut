"""Unit tests for PeakCut Model Context Protocol (MCP) server.
Tests JSON-RPC 2.0 handshake, tools/list, tool execution, and stdio processing.
"""
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import mcp

fails: List[str] = []


def check(name: str, ok: bool, extra: str = ""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    if not ok:
        fails.append(name)


class MockPeakCutClient(mcp.PeakCutClient):
    """In-memory mock for PeakCutClient to test tool dispatching without network."""

    def __init__(self):
        self.base_url = "http://127.0.0.1:8765"

    def get_status(self) -> Dict[str, Any]:
        return {"ready": True, "accounts": False, "ai": {"ready": True, "provider": "OmniRoute"}}

    def preview_url(self, url: str) -> Dict[str, Any]:
        if "youtube.com" not in url and "youtu.be" not in url:
            raise ValueError("Invalid URL for preview")
        return {"title": "Test Video", "uploader": "Creator", "duration": 120.0}

    def list_jobs(self) -> Dict[str, Any]:
        return {"jobs": [{"id": "job_123", "status": "done", "name": "sample_video"}]}

    def get_job(self, job_id: str) -> Dict[str, Any]:
        if job_id == "job_123":
            return {"id": "job_123", "status": "done", "clips": [{"id": "c1", "score": 95, "status": "done"}]}
        raise ValueError("Job not found")

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        if job_id == "job_123":
            return {"ok": True}
        raise ValueError("Job not found")

    def delete_clip(self, job_id: str, clip_id: str) -> Dict[str, Any]:
        if job_id == "job_123" and clip_id == "c1":
            return {"ok": True}
        raise ValueError("Clip not found")

    def get_clip_media(self, job_id: str, clip_id: str) -> Dict[str, Any]:
        if job_id == "job_123" and clip_id == "c1":
            return {
                "job_id": job_id,
                "clip_id": clip_id,
                "status": "done",
                "media_url": f"http://127.0.0.1:8765/media/{job_id}/{clip_id}.mp4",
                "thumbnail_url": f"http://127.0.0.1:8765/media/{job_id}/{clip_id}.jpg",
                "download_url": f"http://127.0.0.1:8765/media/{job_id}/{clip_id}.mp4?download=1",
                "file_path": "/fake/path/clip.mp4",
                "subtitles_path": "/fake/path/clip.ass",
                "clip": {"id": "c1", "score": 95},
            }
        raise ValueError("Clip not found")

    def submit_video_url(self, url: str, creator: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if "youtube.com" not in url and "youtu.be" not in url and "twitch.tv" not in url:
            raise ValueError("Invalid URL")
        return {"id": "job_new", "url": url, "creator": creator, "status": "queued"}

    def upload_local_video(self, file_path: str, creator: Optional[str] = None) -> Dict[str, Any]:
        return {"id": "job_upload", "file": file_path, "status": "queued"}

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
        return {
            "id": clip_id,
            "job_id": job_id,
            "style": style or "s1",
            "layout": layout or "blur",
            "hook": hook,
            "title": title,
            "description": description,
            "start": start,
            "end": end,
            "status": "rendering",
        }

    def export_clips_archive(self, clip_pairs: List[str], output_path: Optional[str] = None) -> Dict[str, Any]:
        return {"archive_url": "http://127.0.0.1:8765/api/clips.zip?ids=" + ",".join(clip_pairs), "file_path": output_path, "clips_count": len(clip_pairs)}

    def list_creators(self) -> Dict[str, Any]:
        return {"creators": [{"id": "cr_1", "name": "TechReviewer"}]}

    def create_creator(
        self, name: str, channel: Optional[str] = None, channels: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        return {"id": "cr_new", "name": name, "channel": channel, "channels": channels or {}}

    def start_live_monitoring(self, creator_id: str, platform: str = "", channel: str = "") -> Dict[str, Any]:
        return {"id": "live_job_1", "creator_id": creator_id, "status": "recording"}

    def capture_live_moment(self, job_id: str) -> Dict[str, Any]:
        return {"id": "clip_live_1", "job_id": job_id, "status": "captured"}

    def stop_live_monitoring(self, job_id: str) -> Dict[str, Any]:
        return {"id": job_id, "status": "stopped"}

    def list_accounts(self) -> Dict[str, Any]:
        return {"accounts": [{"id": "acc_yt", "platform": "youtube"}]}

    def publish_clip(self, clip_id: str, account_id: str, caption: str = "") -> Dict[str, Any]:
        return {"id": "post_1", "clip_id": clip_id, "account_id": account_id, "caption": caption}

    def preview_channel(self, url: str) -> Dict[str, Any]:
        return {"title": "Sample Channel", "channel": url, "subscribers": "100K"}

    def update_creator(self, creator_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": creator_id, "updated": True, **updates}

    def delete_creator(self, creator_id: str) -> Dict[str, Any]:
        return {"id": creator_id, "deleted": True}

    def disconnect_account(self, account_id: str) -> Dict[str, Any]:
        return {"ok": True, "disconnected": account_id}

    def manage_post(self, post_id: str, action: str) -> Dict[str, Any]:
        if action not in ("cancel", "retry"):
            raise ValueError("Invalid post action")
        return {"ok": True, "post_id": post_id, "action": action}

    def get_publishing_overview(self) -> Dict[str, Any]:
        return {"queued": 2, "posted": 15, "failed": 0}

    def get_ai_usage(self) -> Dict[str, Any]:
        return {"calls": 42, "tokens": 85000}

    def get_ai_config(self) -> Dict[str, Any]:
        return {"provider": "OmniRoute", "models": ["antigravity/gemini-3.8-flash-medium"], "has_key": True}

    def update_ai_config(
        self, provider: str, models: Any, base_url: str = "", key: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"provider": provider, "models": models, "base_url": base_url, "has_key": bool(key)}

    def list_ai_models(
        self, provider: Optional[str] = None, base_url: Optional[str] = None, key: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"models": ["gemini-2.5-flash", "gpt-4o-mini"]}

    def test_ai_connection(self) -> Dict[str, Any]:
        return {"ok": True, "model": "test-model"}

    def get_notifications(self) -> Dict[str, Any]:
        return {"notifications": [{"id": "n1", "text": "Clips ready"}]}

    def mark_notifications_read(self) -> Dict[str, Any]:
        return {"ok": True}

    def bulk_delete(self, videos: Optional[List[str]] = None, clips: Optional[List[List[str]]] = None) -> Dict[str, Any]:
        return {"deleted_videos": len(videos or []), "deleted_clips": len(clips or [])}


def test_handshake():
    client = MockPeakCutClient()

    # initialize
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
    res = mcp.handle_request(client, init_req)
    check("initialize: response structure", res.get("id") == 1 and res.get("jsonrpc") == "2.0")
    check("initialize: protocolVersion", res["result"].get("protocolVersion") == "2024-11-05")
    check("initialize: serverInfo", res["result"].get("serverInfo", {}).get("name") == "peakcut")
    check("initialize: tools capability", "tools" in res["result"].get("capabilities", {}))

    # notifications/initialized (notification -> returns None, no response)
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    check("notifications/initialized returns None", mcp.handle_request(client, notif) is None)

    # ping
    ping_req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    res_ping = mcp.handle_request(client, ping_req)
    check("ping returns empty result", res_ping == {"jsonrpc": "2.0", "id": 2, "result": {}})

    # invalid request without method
    bad_req = {"jsonrpc": "2.0", "id": 3}
    res_bad = mcp.handle_request(client, bad_req)
    check("missing method returns error -32600", res_bad.get("error", {}).get("code") == -32600)

    # unknown method
    unknown_req = {"jsonrpc": "2.0", "id": 4, "method": "non_existent_method"}
    res_unk = mcp.handle_request(client, unknown_req)
    check("unknown method returns error -32601", res_unk.get("error", {}).get("code") == -32601)


def test_tools_list():
    client = MockPeakCutClient()
    req = {"jsonrpc": "2.0", "id": 10, "method": "tools/list"}
    res = mcp.handle_request(client, req)
    check("tools/list returns 200 result", res.get("id") == 10 and "tools" in res.get("result", {}))

    tools = res["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    expected_tools = {
        "peakcut_get_system_status",
        "peakcut_preview_url",
        "peakcut_preview_channel",
        "peakcut_list_jobs",
        "peakcut_get_job",
        "peakcut_delete_job",
        "peakcut_delete_clip",
        "peakcut_bulk_delete",
        "peakcut_get_clip_media",
        "peakcut_submit_video_url",
        "peakcut_upload_local_video",
        "peakcut_render_clip",
        "peakcut_export_clips_archive",
        "peakcut_list_creators",
        "peakcut_create_creator",
        "peakcut_update_creator",
        "peakcut_delete_creator",
        "peakcut_start_live_monitoring",
        "peakcut_capture_live_moment",
        "peakcut_stop_live_monitoring",
        "peakcut_list_connected_accounts",
        "peakcut_disconnect_account",
        "peakcut_publish_clip",
        "peakcut_manage_post",
        "peakcut_get_publishing_overview",
        "peakcut_get_ai_usage",
        "peakcut_get_ai_config",
        "peakcut_update_ai_config",
        "peakcut_list_ai_models",
        "peakcut_test_ai_connection",
        "peakcut_get_notifications",
        "peakcut_mark_notifications_read",
    }
    check("all expected tools registered", expected_tools.issubset(tool_names), f"Missing: {expected_tools - tool_names}")

    # Check that each tool has description and inputSchema
    schemas_valid = all(
        isinstance(t.get("description"), str)
        and len(t["description"]) > 5
        and t.get("inputSchema", {}).get("type") == "object"
        for t in tools
    )
    check("all tool schemas valid", schemas_valid)


def test_tools_call():
    client = MockPeakCutClient()

    # Call peakcut_get_system_status
    req_status = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "peakcut_get_system_status", "arguments": {}},
    }
    res = mcp.handle_request(client, req_status)
    check("tools/call get_system_status isError False", res["result"].get("isError") is False)
    content = json.loads(res["result"]["content"][0]["text"])
    check("tools/call get_system_status content matches", content.get("ready") is True)

    # Call peakcut_preview_url
    req_prev = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "peakcut_preview_url", "arguments": {"url": "https://youtu.be/sample1"}},
    }
    res_prev = mcp.handle_request(client, req_prev)
    check("tools/call preview_url success", res_prev["result"].get("isError") is False)
    prev_data = json.loads(res_prev["result"]["content"][0]["text"])
    check("tools/call preview_url returns metadata", prev_data.get("title") == "Test Video")

    # Call peakcut_list_jobs
    req_jobs = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "peakcut_list_jobs", "arguments": {}},
    }
    res_jobs = mcp.handle_request(client, req_jobs)
    check("tools/call list_jobs isError False", res_jobs["result"].get("isError") is False)
    jobs_content = json.loads(res_jobs["result"]["content"][0]["text"])
    check("tools/call list_jobs returns jobs list", len(jobs_content.get("jobs", [])) == 1)

    # Call peakcut_get_clip_media
    req_media = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "peakcut_get_clip_media", "arguments": {"job_id": "job_123", "clip_id": "c1"}},
    }
    res_media = mcp.handle_request(client, req_media)
    check("tools/call get_clip_media success", res_media["result"].get("isError") is False)
    media_data = json.loads(res_media["result"]["content"][0]["text"])
    check("tools/call get_clip_media contains media_url", "media/job_123/c1.mp4" in media_data.get("media_url", ""))

    # Call peakcut_render_clip with full options
    req_render = {
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "peakcut_render_clip",
            "arguments": {
                "job_id": "job_123",
                "clip_id": "c1",
                "style": "hype",
                "layout": "crop",
                "hook": "INSANE CLUTCH",
                "title": "New Title",
                "start": 10.5,
                "end": 45.0,
            },
        },
    }
    res_render = mcp.handle_request(client, req_render)
    check("tools/call render_clip with options success", res_render["result"].get("isError") is False)
    render_data = json.loads(res_render["result"]["content"][0]["text"])
    check("tools/call render_clip matches parameters", render_data.get("hook") == "INSANE CLUTCH" and render_data.get("start") == 10.5)

    # Call peakcut_export_clips_archive
    req_zip = {
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {"name": "peakcut_export_clips_archive", "arguments": {"clip_pairs": ["job_123.c1"]}},
    }
    res_zip = mcp.handle_request(client, req_zip)
    check("tools/call export_clips_archive success", res_zip["result"].get("isError") is False)

    # Call peakcut_delete_clip
    req_del_clip = {
        "jsonrpc": "2.0",
        "id": 26,
        "method": "tools/call",
        "params": {"name": "peakcut_delete_clip", "arguments": {"job_id": "job_123", "clip_id": "c1"}},
    }
    res_del_clip = mcp.handle_request(client, req_del_clip)
    check("tools/call delete_clip success", res_del_clip["result"].get("isError") is False)

    # Call peakcut_delete_job
    req_del_job = {
        "jsonrpc": "2.0",
        "id": 27,
        "method": "tools/call",
        "params": {"name": "peakcut_delete_job", "arguments": {"job_id": "job_123"}},
    }
    res_del_job = mcp.handle_request(client, req_del_job)
    check("tools/call delete_job success", res_del_job["result"].get("isError") is False)

    # Call peakcut_preview_channel
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {"name": "peakcut_preview_channel", "arguments": {"url": "https://youtube.com/@tech"}}})
    check("tools/call preview_channel success", res["result"].get("isError") is False)

    # Call peakcut_update_creator
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 32, "method": "tools/call", "params": {"name": "peakcut_update_creator", "arguments": {"creator_id": "cr_1", "updates": {"style": "clean"}}}})
    check("tools/call update_creator success", res["result"].get("isError") is False)

    # Call peakcut_delete_creator
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 33, "method": "tools/call", "params": {"name": "peakcut_delete_creator", "arguments": {"creator_id": "cr_1"}}})
    check("tools/call delete_creator success", res["result"].get("isError") is False)

    # Call peakcut_disconnect_account
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 34, "method": "tools/call", "params": {"name": "peakcut_disconnect_account", "arguments": {"account_id": "acc_1"}}})
    check("tools/call disconnect_account success", res["result"].get("isError") is False)

    # Call peakcut_manage_post
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 35, "method": "tools/call", "params": {"name": "peakcut_manage_post", "arguments": {"post_id": "p_1", "action": "retry"}}})
    check("tools/call manage_post success", res["result"].get("isError") is False)

    # Call peakcut_get_publishing_overview
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 36, "method": "tools/call", "params": {"name": "peakcut_get_publishing_overview", "arguments": {}}})
    check("tools/call get_publishing_overview success", res["result"].get("isError") is False)

    # Call peakcut_get_ai_usage
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 37, "method": "tools/call", "params": {"name": "peakcut_get_ai_usage", "arguments": {}}})
    check("tools/call get_ai_usage success", res["result"].get("isError") is False)

    # Call peakcut_get_ai_config
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 38, "method": "tools/call", "params": {"name": "peakcut_get_ai_config", "arguments": {}}})
    check("tools/call get_ai_config success", res["result"].get("isError") is False)

    # Call peakcut_update_ai_config
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 39, "method": "tools/call", "params": {"name": "peakcut_update_ai_config", "arguments": {"provider": "omniroute", "models": "antigravity/gemini-3.8-flash-medium"}}})
    check("tools/call update_ai_config success", res["result"].get("isError") is False)

    # Call peakcut_list_ai_models
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 40, "method": "tools/call", "params": {"name": "peakcut_list_ai_models", "arguments": {}}})
    check("tools/call list_ai_models success", res["result"].get("isError") is False)

    # Call peakcut_test_ai_connection
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 41, "method": "tools/call", "params": {"name": "peakcut_test_ai_connection", "arguments": {}}})
    check("tools/call test_ai_connection success", res["result"].get("isError") is False)

    # Call peakcut_get_notifications
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "peakcut_get_notifications", "arguments": {}}})
    check("tools/call get_notifications success", res["result"].get("isError") is False)

    # Call peakcut_mark_notifications_read
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 43, "method": "tools/call", "params": {"name": "peakcut_mark_notifications_read", "arguments": {}}})
    check("tools/call mark_notifications_read success", res["result"].get("isError") is False)

    # Call peakcut_bulk_delete
    res = mcp.handle_request(client, {"jsonrpc": "2.0", "id": 44, "method": "tools/call", "params": {"name": "peakcut_bulk_delete", "arguments": {"videos": ["v1"], "clips": [["v1", "c1"]]}}})
    check("tools/call bulk_delete success", res["result"].get("isError") is False)

    # Call peakcut_submit_video_url valid
    req_submit = {
        "jsonrpc": "2.0",
        "id": 28,
        "method": "tools/call",
        "params": {"name": "peakcut_submit_video_url", "arguments": {"url": "https://youtu.be/abc1234"}},
    }
    res_submit = mcp.handle_request(client, req_submit)
    check("tools/call submit_video_url success", res_submit["result"].get("isError") is False)

    # Call peakcut_submit_video_url invalid
    req_submit_err = {
        "jsonrpc": "2.0",
        "id": 29,
        "method": "tools/call",
        "params": {"name": "peakcut_submit_video_url", "arguments": {"url": "https://invalid.example/video"}},
    }
    res_err = mcp.handle_request(client, req_submit_err)
    check("tools/call submit_video_url error captured cleanly", res_err["result"].get("isError") is True)
    check("tools/call error message in content", "Invalid URL" in res_err["result"]["content"][0]["text"])

    # Call unknown tool
    req_unknown = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {"name": "peakcut_teleport", "arguments": {}},
    }
    res_unk_tool = mcp.handle_request(client, req_unknown)
    check("tools/call unknown tool returns isError True", res_unk_tool["result"].get("isError") is True)
    check("tools/call unknown tool message", "Unknown tool" in res_unk_tool["result"]["content"][0]["text"])


def test_stdio_loop():
    client = MockPeakCutClient()

    simulated_input = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + "malformed-json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        + "\n"
    )

    old_stdin = sys.stdin
    old_stdout = sys.stdout
    try:
        sys.stdin = io.StringIO(simulated_input)
        sys.stdout = io.StringIO()
        mcp.run_stdio_server(client)
        captured_output = sys.stdout.getvalue()
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    output_lines = [json.loads(line) for line in captured_output.splitlines() if line.strip()]
    check("stdio loop handled 3 responses", len(output_lines) == 3)
    check("first response is initialize", output_lines[0].get("id") == 1 and "result" in output_lines[0])
    check("second response is parse error -32700", output_lines[1].get("error", {}).get("code") == -32700)
    check("third response is ping result", output_lines[2].get("id") == 2 and output_lines[2].get("result") == {})


if __name__ == "__main__":
    test_handshake()
    test_tools_list()
    test_tools_call()
    test_stdio_loop()

    if fails:
        print(f"\n{len(fails)} failed")
        sys.exit(1)
    else:
        print("\nALL PASSED")
        sys.exit(0)
