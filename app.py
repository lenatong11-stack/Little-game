import json
import mimetypes
import os
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from adb_client import ADBClient, ADBError
from runner import TaskRunner

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
TASK_FILE = os.path.join(DATA, "tasks.json")
os.makedirs(os.path.join(DATA, "runs"), exist_ok=True)
state_lock = threading.Lock()


def read_tasks():
    try:
        with open(TASK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (IOError, ValueError):
        return []


def save_tasks(items):
    temp = TASK_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(temp, TASK_FILE)


def save_task(task):
    with state_lock:
        items = read_tasks()
        for i, old in enumerate(items):
            if old.get("id") == task["id"]:
                items[i] = task
                break
        else:
            items.insert(0, task)
        save_tasks(items[:100])


runner = TaskRunner(ROOT, save_task)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.send_file(os.path.join(ROOT, "templates", "index.html"))
        if path == "/api/devices":
            try:
                found = ADBClient.devices()
                for device in found:
                    if device["state"] == "device":
                        try:
                            device["resolution"] = ADBClient(device["serial"]).resolution()
                        except ADBError as exc:
                            device["resolution_error"] = str(exc)
                return self.send_json({"ok": True, "devices": found})
            except ADBError as exc:
                return self.send_json({"ok": False, "error": str(exc), "devices": []}, 503)
        if path == "/api/tasks":
            return self.send_json(read_tasks())
        if path.startswith("/data/"):
            rel = unquote(path[len("/data/"):])
            target = os.path.abspath(os.path.join(DATA, rel))
            if os.path.commonpath([DATA, target]) != DATA:
                return self.send_json({"error": "invalid path"}, 400)
            return self.send_file(target)
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/tasks":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 1000000)
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return self.send_json({"error": "invalid JSON body"}, 400)
            name = str(data.get("name", "")).strip()
            package = str(data.get("package", "")).strip()
            steps = data.get("steps")
            if not name or not package or not isinstance(steps, list) or not steps:
                return self.send_json({"error": "请填写任务名称、应用包名和至少一个步骤"}, 400)
            for step in steps:
                if not isinstance(step, dict):
                    return self.send_json({"error": "步骤格式不正确"}, 400)
                if step.get("type") == "vision":
                    goal = step.get("goal")
                    if not isinstance(goal, str) or not 1 <= sum(
                        bool(line.strip()) for line in goal.splitlines()
                    ) <= 20:
                        return self.send_json({"error": "请填写 1 至 20 行自然语言步骤"}, 400)
                    if not isinstance(step.get("assertion", ""), str):
                        return self.send_json({"error": "验收条件必须是文本"}, 400)
            task = {"id": uuid.uuid4().hex[:10], "name": name, "package": package,
                    "serial": data.get("serial") or "", "steps": steps, "status": "queued",
                    "logs": [], "screenshots": [],
                    "created_at": datetime.now().isoformat(timespec="seconds")}
            save_task(task)
            return self.send_json(task, 201)
        if path.startswith("/api/tasks/") and path.endswith("/run"):
            task_id = path.split("/")[-2]
            task = next((x for x in read_tasks() if x.get("id") == task_id), None)
            if not task:
                return self.send_json({"error": "任务不存在"}, 404)
            if task.get("status") == "running":
                return self.send_json({"error": "任务正在执行"}, 409)
            if not runner.lock.acquire(blocking=False):
                return self.send_json({"error": "已有测试任务正在运行，请等待结束"}, 409)

            def execute():
                try:
                    runner.execute(task)
                finally:
                    runner.lock.release()

            threading.Thread(target=execute, daemon=True).start()
            return self.send_json({"ok": True, "id": task_id}, 202)
        return self.send_json({"error": "not found"}, 404)

    def send_file(self, path):
        if not os.path.isfile(path):
            return self.send_json({"error": "file not found"}, 404)
        with open(path, "rb") as f:
            body = f.read()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[http] " + fmt % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 5000), Handler)
    print("打开 http://127.0.0.1:5000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
