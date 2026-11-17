import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adb_client
import app
import runner

DEVICES = [{'serial': 'A', 'state': 'device'}, {'serial': 'B', 'state': 'device'}, {'serial':'C','state':'unauthorized'}]

class Tests(unittest.TestCase):
    def test_adb_requires_explicit_serial(self):
        with patch('adb_client.subprocess.run') as run:
            with self.assertRaises(adb_client.ADBError):
                adb_client.ADBClient().tap(10,20)
            run.assert_not_called()
            run.return_value.returncode=0
            run.return_value.stdout='ok'
            adb_client.ADBClient('B').tap(10,20)
            self.assertEqual(run.call_args.args[0][:3],[adb_client.ADB,'-s','B'])

    def test_selected_only_and_screenshots(self):
        calls=[]
        class Device:
            devices=staticmethod(lambda:DEVICES)
            def __init__(self,serial): self.serial=serial
            def launch(self,package): calls.append(('launch',self.serial))
            def tap(self,x,y): calls.append(('tap',self.serial))
            def screenshot(self,path):
                calls.append(('screenshot',self.serial))
                Path(path).write_bytes(str(len(calls)).encode())
        with tempfile.TemporaryDirectory() as root, patch.object(runner,'ADBClient',Device), patch.object(runner.time,'sleep'):
            task={'id':'one','serial':'B','package':'com.test','steps':[{'type':'launch'},{'type':'tap','width':100,'height':100,'x':.5,'y':.5}]}
            runner.TaskRunner(root,lambda task:None).execute(task)
            self.assertEqual(task['status'],'success')
            self.assertEqual(task['bound_serial'],'B')
            self.assertTrue(all(serial=='B' for _,serial in calls))
            self.assertEqual(len(task['screenshots']),4)
            self.assertTrue(all(s['review']=='pending' and s['serial']=='B' for s in task['screenshots']))

    def test_disconnect_never_falls_back(self):
        calls=[]
        class Device:
            count=0
            @staticmethod
            def devices():
                Device.count+=1
                return DEVICES if Device.count==1 else [DEVICES[0]]
            def __init__(self,serial): self.serial=serial
            def screenshot(self,path): calls.append(self.serial);raise RuntimeError('disconnected')
        with tempfile.TemporaryDirectory() as root, patch.object(runner,'ADBClient',Device), patch.object(runner.subprocess,'Popen') as popen:
            task={'id':'two','serial':'B','package':'com.test','steps':[{'type':'vision','goal':'tap'}]}
            runner.TaskRunner(root,lambda task:None).execute(task)
            self.assertEqual(task['status'],'failed')
            popen.assert_not_called()
            self.assertTrue(all(s=='B' for s in calls))

    def test_missing_serial_no_device_commands(self):
        with tempfile.TemporaryDirectory() as root, patch.object(runner,'ADBClient') as device:
            task={'id':'three','serial':'','steps':[{'type':'launch'}]}
            runner.TaskRunner(root,lambda task:None).execute(task)
            self.assertEqual(task['status'],'failed')
            device.return_value.launch.assert_not_called()
            device.return_value.screenshot.assert_not_called()

    def test_api_selection_and_review(self):
        with tempfile.TemporaryDirectory() as root, patch.object(app,'TASK_FILE',str(Path(root)/'tasks.json')), patch.object(app.ADBClient,'devices',return_value=DEVICES):
            server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            def call(path,body):
                req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                try:
                    with urllib.request.urlopen(req) as r:return r.status,json.load(r)
                except urllib.error.HTTPError as r:return r.code,json.load(r)
            try:
                base={'name':'test','package':'com.test','steps':[{'type':'vision','goal':'tap'}]}
                self.assertEqual(call('/api/tasks',base)[0],400)
                self.assertEqual(call('/api/tasks',{**base,'serial':'C'})[0],409)
                code,task=call('/api/tasks',{**base,'serial':'B'})
                self.assertEqual(code,201)
                task.update(status='success',screenshots=[{'path':'data/runs/test/one.png','label':'tap'}])
                app.save_task(task)
                route='/api/tasks/'+task['id']+'/review'
                self.assertEqual(call(route,{'path':'bad','decision':'passed'})[0],404)
                self.assertEqual(call(route,{'path':'data/runs/test/one.png','decision':'issue','note':'按钮未关闭'})[0],200)
                shot=app.read_tasks()[0]['screenshots'][0]
                self.assertEqual(shot['review'],'issue')
                self.assertEqual(shot['review_note'],'按钮未关闭')
                task['status']='running';app.save_task(task)
                self.assertEqual(call(route,{'path':shot['path'],'decision':'passed'})[0],409)
            finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
