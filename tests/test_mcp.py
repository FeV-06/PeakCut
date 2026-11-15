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

    def list_jobs(self) -> Dict[str, Any]:
        return {"jobs": [{"id": "job_123", "status": "done", "name": "sample_video"}]}

    def get_job(self, job_id: str) -> Dict[str, Any]:
        if job_id == "job_123":
            return {"id": "job_123", "status": "done", "clips": [{"id": "c1", "score": 95}]}
        raise ValueError("Job not found")

    def submit_video_url(self, url: str, creator: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if "youtube.com" not in url and "youtu.be" not in url and "twitch.tv" not in url:
            raise ValueError("Invalid URL")
        return {"id": "job_new", "url": url, "creator": creator, "status": "queued"}

    def upload_local_video(self, file_path: str, creator: Optional[str] = None) -> Dict[str, Any]:
        return {"id": "job_upload", "file": file_path, "status": "queued"}

    def render_clip(self, job_id: str, clip_id: str, style: str = "s1") -> Dict[str, Any]:
        return {"id": clip_id, "job_id": job_id, "style": style, "status": "rendering"}

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
        "peakcut_list_jobs",
        "peakcut_get_job",
        "peakcut_submit_video_url",
        "peakcut_upload_local_video",
        "peakcut_render_clip",
        "peakcut_list_creators",
        "peakcut_create_creator",
        "peakcut_start_live_monitoring",
        "peakcut_capture_live_moment",
        "peakcut_stop_live_monitoring",
        "peakcut_list_connected_accounts",
        "peakcut_publish_clip",
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

    # Call peakcut_list_jobs
    req_jobs = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "peakcut_list_jobs", "arguments": {}},
    }
    res_jobs = mcp.handle_request(client, req_jobs)
    check("tools/call list_jobs isError False", res_jobs["result"].get("isError") is False)
    jobs_content = json.loads(res_jobs["result"]["content"][0]["text"])
    check("tools/call list_jobs returns jobs list", len(jobs_content.get("jobs", [])) == 1)

    # Call peakcut_submit_video_url valid
    req_submit = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "peakcut_submit_video_url", "arguments": {"url": "https://youtu.be/abc1234"}},
    }
    res_submit = mcp.handle_request(client, req_submit)
    check("tools/call submit_video_url success", res_submit["result"].get("isError") is False)

    # Call peakcut_submit_video_url invalid
    req_submit_err = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "peakcut_submit_video_url", "arguments": {"url": "https://invalid.example/video"}},
    }
    res_err = mcp.handle_request(client, req_submit_err)
    check("tools/call submit_video_url error captured cleanly", res_err["result"].get("isError") is True)
    check("tools/call error message in content", "Invalid URL" in res_err["result"]["content"][0]["text"])

    # Call unknown tool
    req_unknown = {
        "jsonrpc": "2.0",
        "id": 24,
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
