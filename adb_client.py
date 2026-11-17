import os
import shutil
import subprocess
import time


ADB = os.environ.get("ADB_PATH") or shutil.which("adb") or r"D:\Android\platform-tools\adb.exe"


class ADBError(RuntimeError):
    pass


class ADBClient:
    def __init__(self, serial=None):
        self.serial = serial

    def run(self, *args, timeout=20):
        if not self.serial:
            raise ADBError("必须明确指定执行设备序列号，禁止自动选择设备")
        command = [ADB, "-s", self.serial]
        command += list(args)
        try:
            p = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout, universal_newlines=True, encoding="utf-8",
                               errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ADBError(str(exc))
        if p.returncode:
            raise ADBError((p.stderr or p.stdout).strip() or "ADB command failed")
        return p.stdout.strip()

    @staticmethod
    def devices():
        try:
            p = subprocess.run([ADB, "devices", "-l"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True,
                               encoding="utf-8", errors="replace", timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ADBError("无法查询设备：{}".format(exc))
        if p.returncode:
            raise ADBError(p.stderr.strip() or "无法启动 ADB")
        result = []
        for line in p.stdout.splitlines()[1:]:
            cols = line.split()
            if cols:
                result.append({"serial": cols[0], "state": cols[1] if len(cols) > 1 else "unknown",
                               "details": " ".join(cols[2:])})
        return result

    def resolution(self):
        size = self.run("shell", "wm", "size")
        # Orientation is read dynamically from the current screenshot dimensions.
        vals = [x for x in size.split() if "x" in x]
        physical = vals[0].split("x") if vals else ["0", "0"]
        override = vals[-1].split("x") if vals else physical
        return {"physical": physical, "override": override, "raw": size}

    def launch(self, package):
        return self.run("shell", "monkey", "-p", package, "1", timeout=30)

    def tap(self, x, y):
        return self.run("shell", "input", "tap", str(int(x)), str(int(y)))

    def screenshot(self, destination):
        remote = "/sdcard/codex-automation-{}.png".format(int(time.time() * 1000))
        self.run("shell", "screencap", "-p", remote)
        self.run("pull", remote, os.path.abspath(destination), timeout=30)
        try:
            self.run("shell", "rm", remote)
        except ADBError:
            pass
        return destination

    def hierarchy(self):
        remote = "/sdcard/codex-window.xml"
        self.run("shell", "uiautomator", "dump", remote, timeout=30)
        return self.run("shell", "cat", remote)
