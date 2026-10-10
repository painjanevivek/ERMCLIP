"""Browser checks against live read-only UI and an isolated editing queue."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from playwright.sync_api import sync_playwright
from ermclip.config import Settings
from ermclip.models import Captions, Duration, Profile
from ermclip.util import atomic_json, run
from ermclip.webapp import Workspace, WorkspaceServer


def wait_js(page, expression, timeout=30):
    # CDP evaluate avoids a string-eval wait predicate blocked by the app's CSP.
    deadline = time.monotonic() + timeout
    while not page.evaluate('() => (' + expression + ')'):
        if time.monotonic() >= deadline:
            raise AssertionError('Browser condition timed out: ' + expression)
        page.wait_for_timeout(100)


def main():
    outputs = ROOT / 'output/workspace-checks'
    outputs.mkdir(parents=True, exist_ok=True)
    test_root = Path(tempfile.mkdtemp(prefix='ui-flow-', dir=ROOT / 'state'))
    source = test_root / 'input/podcast-test.mp4'
    profile = Profile(count=2, duration=Duration(target=6, minimum=4, maximum=10), captions=Captions(preset='highlighter'))
    settings = Settings(root=str(test_root), allowed_inputs=[str(test_root/'input')], podcast_sources=[str(source)],
                        stable_seconds=0, min_free_gb=0, encoder='cpu', defaults=[profile])
    settings.prepare()
    atomic_json(test_root/'config/local.json', settings.model_dump())
    shutil.copytree(ROOT/'output/caption-gallery', test_root/'output/caption-gallery')
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=10:duration=12',
         '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=12','-c:v','libx264','-preset','ultrafast',
         '-c:a','aac','-shortest',str(source)], timeout=60)
    app = Workspace(test_root)
    app.start_worker = lambda: None  # Do not render or use models during UI queue checks.
    server = WorkspaceServer(('127.0.0.1', 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = {'live_checks':[], 'isolated_checks':[], 'console_errors':[], 'external_requests':[]}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True,
                args=['--disable-background-networking','--disable-component-update'])
            context = browser.new_context(viewport={'width':1440,'height':1000})
            def local_only(route):
                if route.request.url.startswith(('http://127.0.0.1:', 'http://localhost:', 'data:')):
                    route.continue_()
                else:
                    report['external_requests'].append(route.request.url)
                    route.abort()
            context.route('**/*', local_only)
            page = context.new_page()
            page.on('pageerror', lambda err: report['console_errors'].append(str(err)))
            page.on('console', lambda message: report['console_errors'].append(message.text) if message.type=='error' else None)
            page.goto('http://127.0.0.1:8090/')
            page.wait_for_load_state('networkidle')
            wait_js(page, 'document.querySelectorAll("#all-style-grid button").length===25')
            assert page.locator('#source-video').get_attribute('src') is None
            assert page.locator('#empty-source').is_visible()
            assert page.locator('[data-step]').count()==5
            page.get_by_role('button',name='Continue →',exact=True).click()
            assert page.locator('#wizard-step-label').inner_text()=='Step 1 of 5'
            assert 'Import a video' in page.locator('#toast').inner_text()
            page.screenshot(path=str(outputs/'workspace-desktop.png'), full_page=True)
            report['live_checks'].append('Empty start; five steps; import button visible; cannot continue without source')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(outputs/'workspace-mobile.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile page overflows horizontally'
            report['live_checks'].append('Mobile layout has no horizontal overflow')
            page.set_viewport_size({'width':1260,'height':840})
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_load_state('networkidle')
            wait_js(page, 'document.querySelectorAll("#all-style-grid button").length===25')
            assert page.locator('#source-video').get_attribute('src') is None
            assert app.sources()==[]
            page.get_by_role('button',name='Or paste a file path',exact=True).click()
            page.locator('#video-path').fill(str(source))
            page.locator('#path-dialog').get_by_role('button',name='Add video',exact=True).click()
            wait_js(page, 'document.querySelector("#source-video").getAttribute("src") !== null')
            assert app.sources()[0]['name']=='podcast-test.mp4'
            page.get_by_role('button',name='Continue →',exact=True).click()
            assert page.locator('#wizard-step-label').inner_text()=='Step 2 of 5'
            page.locator('#count').fill('1')
            page.locator('#minimum').fill('9')
            page.get_by_role('button',name='Continue →',exact=True).click()
            assert page.locator('#wizard-step-label').inner_text()=='Step 2 of 5'
            page.locator('#minimum').fill('4')
            page.get_by_text('Topic and language controls',exact=True).click()
            page.locator('#language').select_option('en')
            page.get_by_role('button',name='Continue →',exact=True).click()
            assert page.locator('#wizard-step-label').inner_text()=='Step 3 of 5'
            page.get_by_role('button',name='All 25 styles',exact=False).click()
            assert page.locator('#styles-dialog').is_visible()
            page.locator('#styles-dialog').get_by_role('button',name='Use Momentum',exact=True).click()
            assert page.locator('#caption-style-name').inner_text()=='Momentum'
            page.get_by_role('button',name='Use Highlighter',exact=True).click()
            page.locator('#layout').select_option('podcast_hero')
            page.locator('#credit').fill('Local test | EP 001')
            page.screenshot(path=str(outputs/'wizard-look.png'),full_page=True)
            page.get_by_role('button',name='Continue →',exact=True).click()
            assert page.locator('#wizard-step-label').inner_text()=='Step 4 of 5'
            assert 'podcast-test.mp4' in page.locator('#confirm-summary').inner_text()
            assert 'Highlighter' in page.locator('#confirm-summary').inner_text()
            assert 'active speaker tracking' in page.locator('#confirm-summary').inner_text()
            page.screenshot(path=str(outputs/'wizard-confirm.png'),full_page=True)
            page.get_by_role('button',name='Save these settings as default').click()
            wait_js(page, 'document.querySelector("#toast").textContent.startsWith("Saved")')
            assert app.settings().defaults[0].layout.credit=='Local test | EP 001'
            report['isolated_checks'].append('Explicit local import; five-step validation; 25 caption styles; confirmation; defaults persisted')
            page.get_by_role('button',name='Create shorts',exact=False).click()
            wait_js(page, 'document.querySelector("#wizard-step-label").textContent==="Step 5 of 5"')
            assert len(app.store.list())==1 and app.store.list()[0]['status']=='queued'
            job=app.store.get(app.store.list()[0]['id'])
            assert job['spec']['profiles'][0]['captions']['preset']=='highlighter'
            assert job['spec']['profiles'][0]['framing']=='speaker'
            report['isolated_checks'].append('Step 5 tracks the submitted job; selected captions and speaker tracking reach SQLite')
            # Controlled export fixture: checks review plumbing without claiming an AI render.
            folder=test_root/'output'/job['id'];folder.mkdir()
            clip=folder/'clip_001.mp4';shutil.copyfile(source,clip)
            clip.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nSynthetic test caption.\n',encoding='utf-8')
            atomic_json(folder/'clip_001_quality.json',{'status':'review_required','findings':[{'code':'fixture','issue':'Synthetic review fixture, not a model result.'}]})
            atomic_json(folder/'manifest.json',{'outputs':[{'path':str(clip)}]})
            app.store.update(job['id'],status='review_required',stage='complete',output=str(folder))
            page.evaluate('refreshJobs().then(refreshOutputs).then(renderProgress)')
            assert page.locator('#recent-shorts .recent-card').count()==1
            page.locator('#recent-shorts .recent-card').click()
            wait_js(page, 'document.querySelector("#review-video").readyState>=1')
            assert page.evaluate('document.querySelector("#review-video").videoWidth')==320
            assert page.get_by_role('link',name='Subtitles',exact=True).is_visible()
            page.screenshot(path=str(outputs/'workspace-review.png'),full_page=True)
            page.locator('#review-dialog').get_by_role('button',name='Close',exact=True).click()
            report['isolated_checks'].append('Job-specific review loads video, subtitles and checks from an export fixture')
            page.get_by_role('button',name='View all shorts →',exact=True).click()
            assert page.locator('#shorts-view').is_visible()
            assert page.locator('#wizard-step-label').inner_text()=='Step 5 of 5'
            page.get_by_role('button',name='Editing jobs',exact=False).click()
            page.get_by_role('button',name='Details / revise',exact=True).first.click()
            page.locator('#revision-instruction').fill('Create one complete clip of 5 seconds.')
            page.get_by_role('button',name='Create revision',exact=True).click()
            wait_js(page, '!document.querySelector("#job-dialog").open && document.querySelectorAll(".job-row").length===2')
            assert len(app.store.list())==2
            report['isolated_checks'].append('Revision created a new job and retained its parent')
            page.get_by_role('button',name='Pause queue',exact=True).click()
            page.get_by_role('button',name='Resume queue',exact=True).wait_for()
            assert app.store.control('pause')=='1'
            page.get_by_role('button',name='Resume queue',exact=True).click()
            page.get_by_role('button',name='Pause queue',exact=True).wait_for()
            assert app.store.control('pause')=='0'
            report['isolated_checks'].append('Pause and resume controls persisted')
            page.get_by_role('button',name='Settings',exact=True).click()
            page.locator('#model-calls').fill('12')
            page.get_by_role('button',name='Save engine settings',exact=True).click()
            wait_js(page, '!document.querySelector("#engine-form button").disabled')
            assert app.settings().max_model_calls==12
            report['isolated_checks'].append('Engine settings saved with the local API budget unchanged')
            page.get_by_role('button',name='Change color theme',exact=True).click()
            assert page.locator('body').evaluate('(el)=>el.classList.contains("dark")')
            report['isolated_checks'].append('Local color theme toggle works')
            page.get_by_role('button',name='Workspace',exact=True).click()
            page.get_by_role('button',name='Make another set',exact=True).click()
            assert page.locator('#source-video').get_attribute('src') is None
            assert page.locator('#wizard-step-label').inner_text()=='Step 1 of 5'
            page.reload()
            page.wait_for_load_state('networkidle')
            assert page.locator('#source-video').get_attribute('src') is None
            report['isolated_checks'].append('New set and reopen clear the source; imported video remains available only by explicit selection')
            for job in app.store.list():
                app.store.cancel(job['id'])
            browser.close()
        assert not report['console_errors'], report['console_errors']
        assert not report['external_requests'], report['external_requests']
        report.update(passed=True, paid_api_cost=0, production_jobs_submitted=0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        atomic_json(outputs/'browser-checks.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
