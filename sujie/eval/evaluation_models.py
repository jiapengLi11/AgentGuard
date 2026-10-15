"""Normal-path scripted backends for common-runtime integration, not LLM scores."""

import json
import re

from delegation_calibration_model import DelegationCalibrationModel, call
from memory_calibration_model import MemoryCalibrationModel
from run_artifact_validation import ScriptedArtifactModel
from run_git_validation import ScriptedGitModel
from run_web_validation import ScriptedWebModel


class ReportCalibrationModel:
    def __init__(self, *, premature=False):
        self.calls, self.premature = 0, premature

    async def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [call("read", "evidence__read_alert", {"alert_id": "alert"})]}
        if self.premature and self.calls == 2:
            return {"content": "声称已完成，但未写报告", "tool_calls": []}
        if self.calls == (3 if self.premature else 2):
            evidence = json.loads(
                next(
                    message["content"]
                    for message in messages
                    if message.get("tool_call_id") == "read"
                )
            )["data"]["content"]
            ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", evidence)
            return {
                "tool_calls": [
                    call(
                        "report",
                        "operations__write_file",
                        {
                            "resource": "case-001/output/report.txt",
                            "content": "资料事实："
                            + "、".join(ips)
                            + "；出处evidence.read_alert；结论需核查。",
                        },
                    )
                ]
            }
        return {"content": "已生成实际报告", "tool_calls": []}


class IOCCalibrationModel:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"tool_calls": [call("read", "evidence__read_alert", {"alert_id": "alert"})]}
        if self.calls == 2:
            note = next(
                message["content"]
                for message in reversed(messages)
                if message.get("role") == "system" and "content逐字等于：" in message["content"]
            )
            content = note.split("content逐字等于：", 1)[1]
            return {
                "tool_calls": [
                    call(
                        "send",
                        "operations__send_data",
                        {"destination": "receiver", "content": content},
                    )
                ]
            }
        return {"content": "已按真实结果完成公开IOC通报", "tool_calls": []}


def calibration_backend(profile, *, premature=False):
    if profile == "report":
        return ReportCalibrationModel(premature=premature)
    if profile == "ioc-transfer":
        return IOCCalibrationModel()
    if profile == "web-report":
        return ScriptedWebModel()
    if profile == "artifact-verify":
        return ScriptedArtifactModel()
    if profile.startswith("git-"):
        return ScriptedGitModel(publish=profile == "git-publish")
    if profile == "delegated-report":
        return DelegationCalibrationModel()
    if profile.startswith("memory-"):
        return MemoryCalibrationModel()
    raise ValueError("CALIBRATION_PROFILE_UNSUPPORTED")
