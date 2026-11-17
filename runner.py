import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from datetime import datetime

from adb_client import ADB, ADBClient


class TaskRunner:
    def __init__(self, root, save_callback):
        self.root = root
        self.save_callback = save_callback
        self.lock = threading.Lock()

    def execute(self, task):
        serial = task.get("serial") or None
        adb = ADBClient(serial)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        folder = os.path.join(self.root, "data", "runs", run_id)
        os.makedirs(folder, exist_ok=True)
        task.update({"run_id": run_id, "status": "running", "logs": [], "screenshots": [],
                     "started_at": datetime.now().isoformat(timespec="seconds"),
                     "failure_step": None, "error": None, "result": None,
                     "finished_at": None, "current_step": None})
        task.pop("bound_serial", None)
        self.save_callback(task)

        def log(message, level="info"):
            task["logs"].append({"time": datetime.now().strftime("%H:%M:%S"),
                                 "level": level, "message": message})
            self.save_callback(task)

        def register_screenshot(name, label, metadata=None, source_folder=None):
            path = os.path.join(source_folder or folder, name)
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            rel = os.path.relpath(path, self.root).replace(os.sep, "/")
            task["screenshots"].append({"label": label, "path": rel, "sha256": digest,
                                        "serial": serial,
                                        "captured_at": datetime.now().isoformat(timespec="seconds"),
                                        "stage": task.get("current_step"),
                                        "review": "pending", "review_note": "",
                                        **(metadata or {})})
            log("已保存截图：{}".format(name))
            return digest

        def snap(label):
            name = "{:02d}-{}.png".format(len(task["screenshots"]) + 1, label)
            adb.screenshot(os.path.join(folder, name))
            return register_screenshot(name, label)

        try:
            # Bind once for the entire run. Never switch to another device.
            if not serial:
                raise ValueError("请明确选择执行设备；不会自动选择其他设备")
            ready = {d["serial"] for d in ADBClient.devices() if d["state"] == "device"}
            if serial not in ready:
                raise ValueError("所选设备已断开或未授权，任务停止，不切换设备")
            task["bound_serial"] = serial
            log("本次运行绑定设备：{}".format(serial))
            steps = task.get("steps", [])
            if not steps:
                raise ValueError("任务至少需要一个步骤")
            for index, step in enumerate(steps, 1):
                task["current_step"] = index
                self.save_callback(task)
                kind = step.get("type")
                label = step.get("label") or kind
                log("步骤 {}/{}：{}".format(index, len(steps), label))
                if kind == "launch":
                    snap("before-launch")
                    adb.launch(task["package"])
                    time.sleep(min(max(float(step.get("wait", 8)), 1), 30))
                    snap("launch")
                elif kind == "wait":
                    time.sleep(min(max(float(step.get("seconds", 2)), 0), 30))
                    snap("wait")
                elif kind == "screenshot":
                    snap(step.get("label", "checkpoint"))
                elif kind == "vision":
                    ready = [d["serial"] for d in ADBClient.devices() if d["state"] == "device"]
                    if serial not in ready:
                        raise ValueError("找不到已授权的执行设备，请检查 USB 连接")
                    adb = ADBClient(serial)
                    snap("before-vision")
                    vision_folder = os.path.join(folder, "vision-{}".format(index))
                    os.makedirs(vision_folder, exist_ok=True)
                    payload = json.dumps({"serial": serial, "package": task["package"],
                                          "goal": step["goal"], "assertion": step.get("assertion", ""),
                                          "folder": vision_folder, "adb": ADB})
                    proc = subprocess.Popen(["node", os.path.join(self.root, "midscene", "visual_agent.mjs")],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, universal_newlines=True,
                                             encoding="utf-8", errors="replace", bufsize=1,
                                             cwd=os.path.join(self.root, "midscene"))
                    output_queue = queue.Queue()
                    def read_output():
                        for line in proc.stdout:
                            output_queue.put(line.rstrip("\r\n"))
                    reader = threading.Thread(target=read_output, daemon=True)
                    reader.start()
                    proc.stdin.write(payload)
                    proc.stdin.close()
                    limit = 900
                    deadline = time.monotonic() + limit
                    error = None
                    confirmed = False
                    try:
                        while reader.is_alive() or not output_queue.empty():
                            if time.monotonic() >= deadline:
                                raise TimeoutError("视觉任务超过 {} 分钟，已停止".format(limit // 60))
                            try:
                                output_line = output_queue.get(timeout=0.2)
                            except queue.Empty:
                                continue
                            try:
                                event = json.loads(output_line)
                            except ValueError:
                                continue
                            if not isinstance(event, dict) or not isinstance(event.get("message"), str):
                                continue
                            event_type = event.get("type")
                            if event_type == "stage":
                                task["current_step"] = event["stage"]
                            if event_type == "screenshot":
                                file = event.get("file")
                                if isinstance(file, str) and (
                                    file in {"stage-{}.png".format(i) for i in range(22)} | {"failure.png"}
                                    or re.fullmatch(r"action-\d{4,8}-(before|after|failed)\.png", file)
                                ):
                                    metadata = {key: event[key] for key in
                                                ("action", "action_index", "stage", "phase", "captured_at")
                                                if key in event}
                                    register_screenshot(file, event.get("label") or file[:-4], metadata, vision_folder)
                                continue
                            if event_type == "error":
                                error = event["message"]
                            if event_type == "success":
                                confirmed = True
                                task["result"] = event["message"]
                            log("Midscene: " + event["message"], "error" if event_type == "error" else "info")
                        if proc.wait(timeout=2) or not confirmed:
                            raise ValueError(error or "Midscene 未返回成功结果")
                    except Exception:
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait()
                        if not any(s["label"] == "failure" for s in task["screenshots"]):
                            try:
                                snap("failure")
                            except Exception as capture_error:
                                log("无法保存现场截图：{}".format(capture_error), "error")
                        raise
                    finally:
                        reader.join(timeout=1)
                        proc.stdout.close()
                elif kind == "tap":
                    width, height = int(step["width"]), int(step["height"])
                    rx, ry = float(step["x"]), float(step["y"])
                    if not (0 <= rx <= 1 and 0 <= ry <= 1):
                        raise ValueError("点击坐标需为 0 到 1 之间的归一化比例")
                    before = snap("before-tap")
                    adb.tap(round(rx * width), round(ry * height))
                    time.sleep(min(max(float(step.get("wait", 2)), 0.5), 20))
                    after = snap("after-tap")
                    if step.get("verify_change", True) and before == after:
                        raise ValueError("点击后截图没有变化；请检查坐标/权限，任务已停止")
                    log("坐标点击完成并{}截图变化".format("检测到" if before != after else "未要求检查"))
                else:
                    raise ValueError("不支持的步骤类型：{}".format(kind))
            task["status"] = "success"
            task["result"] = task["result"] or "所有步骤完成，请查看关键截图"
            log("任务完成", "success")
        except Exception as exc:
            task["status"] = "failed"
            task["result"] = None
            task["failure_step"] = task.get("current_step")
            task["error"] = str(exc)
            log("任务失败：{}".format(exc), "error")
            if task.get("bound_serial") and not any(
                s.get("phase") == "failed" or s["label"] == "failure" for s in task["screenshots"]
            ):
                try:
                    snap("failure")
                except Exception as capture_error:
                    log("无法保存失败现场：{}".format(capture_error), "error")
        finally:
            task["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self.save_callback(task)
