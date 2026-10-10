"""Instrument the actual ERMCLIP WebView2 window without enabling a debug port."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import time
import faulthandler
import psutil
import webview

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'output/workspace-checks'
OUTPUT.mkdir(parents=True,exist_ok=True)
trace=(OUTPUT/'native-stack.txt').open('w')
faulthandler.dump_traceback_later(25,repeat=False,file=trace)
spec=importlib.util.spec_from_file_location('desktop_launcher',ROOT/'scripts/launch-ermclip.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
chrome_before={p.pid for p in psutil.process_iter(['name']) if p.info['name']=='chrome.exe'}
real_start=webview.start
result={'passed':False,'browser_opened':False}

def verify():
    window=webview.windows[0]
    try:
        (OUTPUT/'native-stage.txt').write_text('Waiting for loaded event')
        if not window.events.loaded.wait(30):
            raise AssertionError('Native window did not load')
        deadline=time.monotonic()+30
        (OUTPUT/'native-stage.txt').write_text('Reading window DOM')
        while time.monotonic()<deadline:
            details=json.loads(window.run_js('JSON.stringify({title:document.title,source:document.querySelector("#source-video").getAttribute("src"),steps:document.querySelectorAll("[data-step]").length,step:document.querySelector("#wizard-step-label").textContent,styles:document.querySelectorAll("#all-style-grid button").length,importVisible:!document.querySelector("#choose-first-video").hidden,engine:document.querySelector("#worker-status").textContent,urls:performance.getEntriesByType("resource").map(r=>r.name)})'))
            if details['styles']==25:break
            time.sleep(.2)
        assert details['source'] is None and details['steps']==5 and details['styles']==25, details
        assert details['step']=='Step 1 of 5'
        assert all(url.startswith('http://127.0.0.1:8090/') for url in details['urls'])
        assert webview.guilib.renderer=='edgechromium'
        # Capture through this window's own WebView2 rendering API.
        from System import Func, Object
        (OUTPUT/'native-stage.txt').write_text('Capturing renderer')
        from webview.platforms.winforms import BrowserView
        browser=BrowserView.instances[window.uid].browser
        task=browser.webview.Invoke(Func[Object](lambda: browser.webview.CoreWebView2.CallDevToolsProtocolMethodAsync('Page.captureScreenshot','{"format":"png"}')))
        deadline=time.monotonic()+20
        while not task.IsCompleted and time.monotonic()<deadline:
            time.sleep(.05)  # Release the Python GIL while the CLR callback completes.
        assert task.IsCompleted, 'Native screenshot timed out'
        screenshot=json.loads(str(task.Result))
        (OUTPUT/'native-window.png').write_bytes(base64.b64decode(screenshot['data']))
        after={p.pid for p in psutil.process_iter(['name']) if p.info['name']=='chrome.exe'}
        assert not after-chrome_before,'Native launcher started Chrome'
        result.update(passed=True,renderer=webview.guilib.renderer,window_title=window.title,dom=details,new_chrome_processes=list(after-chrome_before),paid_api_cost=0)
    except Exception as error:
        result['error']=repr(error)
    finally:
        (OUTPUT/'native-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        faulthandler.cancel_dump_traceback_later()
        window.destroy()

def tested_start(**kwargs):
    return real_start(verify,**kwargs)

webview.start=tested_start
try:
    launcher.launch(ROOT,False)
except Exception as error:
    result['error']=repr(error)
    (OUTPUT/'native-checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
sys.exit(0 if result['passed'] else 1)
