import json
import os
import shutil
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.build_site import build_site
from scripts.serve_site import PublicSiteHandler


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("public-site") / "site"
    build_site(root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PublicSiteHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            channel="chromium",
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser, site):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.goto(site)
    expect(page.locator("#message")).to_contain_text("Calendario publicado cargado")
    yield page
    context.close()


def open_demo(page):
    page.locator("#demo").click()
    expect(page.locator(".event-card")).to_have_count(5)


def test_default_empty_state_and_explicit_demo(page):
    expect(page.locator("#empty-title")).to_have_text("Tu calendario empieza aquí")
    expect(page.locator("#demo-banner")).to_be_hidden()
    expect(page.locator("#metric-events")).to_have_text("0")
    open_demo(page)
    expect(page.locator("#demo-banner")).to_be_visible()
    expect(page.locator("#metric-events")).to_have_text("5")
    expect(page.locator("#metric-tracking")).to_have_text("2")
    expect(page.locator("#metric-changes")).to_have_text("1")
    page.locator("#live").click()
    expect(page.locator(".event-card")).to_have_count(0)
    expect(page.locator("#demo-banner")).to_be_hidden()


def test_filters_navigation_and_preserved_cycle_detail(page):
    open_demo(page)
    page.locator('[data-sport="FOOTBALL"]').click()
    expect(page.locator(".event-card")).to_have_count(2)
    page.locator("#search").fill("Costa")
    expect(page.locator(".event-card")).to_have_count(1)
    page.get_by_role("button", name="Ver detalle de Costa FC y Sierra FC").click()
    expect(page.locator("#detail")).to_be_visible()
    expect(page.locator(".cycle-item")).to_have_count(2)
    expect(page.locator(".cycle-item").first).to_contain_text("Aplazado")
    page.keyboard.press("Escape")
    expect(page.locator("#detail")).not_to_be_visible()
    page.locator("#search").fill("")
    page.locator('[data-sport="ALL"]').click()
    page.locator('[data-view="historial"]').click()
    expect(page.locator(".event-card")).to_have_count(6)
    page.locator('[data-view="seguimiento"]').click()
    expect(page.locator(".event-card")).to_have_count(3)


def test_today_uses_lima_day_not_utc(page):
    page.clock.set_fixed_time("2030-06-16T01:00:00Z")
    open_demo(page)
    page.locator("#date-filter").select_option("TODAY")
    expect(page.locator(".event-card")).to_have_count(4)
    page.locator("#date-filter").select_option("TOMORROW")
    expect(page.locator(".event-card")).to_have_count(1)


def test_local_file_private_data_rejected_without_network_upload(page):
    open_demo(page)
    requests = []
    page.on("request", lambda request: requests.append(request.method))
    payload = {"schema_version": "public_calendar_v1", "real_bet": {"stake": 50}}
    page.locator("#snapshot-file").set_input_files(
        {
            "name": "private.json",
            "mimeType": "application/json",
            "buffer": json.dumps(payload).encode(),
        }
    )
    expect(page.locator("#message")).to_contain_text("Archivo rechazado")
    expect(page.locator(".event-card")).to_have_count(5)
    assert not requests


def test_mobile_navigation_and_extension_download(page):
    page.set_viewport_size({"width": 390, "height": 844})
    open_demo(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator('[data-view="extension"]').click()
    expect(page.locator("#extension-title")).to_be_visible()
    with page.expect_download() as event:
        page.get_by_role("link", name="Descargar extensión ZIP").click()
    assert event.value.suggested_filename == "sports-capture-extension.zip"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_server_cannot_serve_repository_private_files(site):
    for path in ("/.git/config", "/.env", "/.local/", "/raw/", "/docs/", "/web/", "/../.env"):
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(site + path)  # noqa: S310 -- test server on loopback only
        assert error.value.code == 404


def test_missing_snapshot_fails_visibly_and_demo_still_works(browser, site):
    context = browser.new_context()
    page = context.new_page()
    page.route("**/web/public.json", lambda route: route.fulfill(status=404))
    page.goto(site)
    expect(page.locator("#message")).to_contain_text("No se pudo leer")
    open_demo(page)
    context.close()


def test_web_starts_scan_tracks_progress_and_downloads_automatic_batch(browser, site, tmp_path):
    from sports_analysis.providers.browser import parse_scan
    from tests.browser_fixtures import scan_data

    bundle = scan_data()
    context = browser.new_context()
    context.add_init_script(
        "window.bundle="
        + json.dumps(bundle)
        + ";"
        + """
        window.scanCommands=[]; window.run=null;
        window.addEventListener('message', event => {
            const message=event.data;
            if(message?.channel!=='sports_scan_request_v1')return;
            window.scanCommands.push(message);
            if(message.command==='START') {
                window.run={scan_id:bundle.scan_id,status:'RUNNING',started_at:bundle.started_at,finished_at:null,count:0,sources:[{id:'fixture',label:'Fixture',status:'RUNNING',count:0,error:null}]};
                setTimeout(()=>{window.run.status='COMPLETED';window.run.count=1;window.run.sources[0].status='COMPLETED';window.run.sources[0].count=1;window.run.preview=bundle.captures;},400);
            }
            const data=message.command==='RESULTS'?bundle:message.command==='REPORT'?{schema_version:'browser_scan_report_v1',scan_id:bundle.scan_id,sources:window.run.sources}:{configured:1,permitted:true,run:window.run};
            window.postMessage({channel:'sports_scan_response_v1',request_id:message.request_id,result:{ok:true,data}},location.origin);
        });
    """
    )
    page = context.new_page()
    page.goto(site + "/#extension")
    expect(page.locator("#scanner-start")).to_be_enabled()
    page.locator("#scanner-start").click()
    expect(page.locator("#scanner-state")).to_have_text("Escaneando")
    expect(page.locator("#scanner-start")).to_be_disabled()
    expect(page.locator("#scanner-download")).to_be_enabled(timeout=7000)
    with page.expect_download() as download:
        page.locator("#scanner-download").click()
    path = tmp_path / download.value.suggested_filename
    download.value.save_as(path)
    assert len(parse_scan(path.read_bytes())) == 1
    expect(page.locator("#scanner-preview-list")).to_contain_text("North FC")
    with page.expect_download() as report_download:
        page.locator("#scanner-report").click()
    report_path = tmp_path / report_download.value.suggested_filename
    report_download.value.save_as(report_path)
    report = json.loads(report_path.read_text())
    assert report["schema_version"] == "browser_scan_report_v1"
    assert "captures" not in report
    assert page.evaluate("window.scanCommands.filter(item=>item.command==='START').length") == 1
    assert page.evaluate("window.scanCommands.every(item=>Object.keys(item).length===3)")
    context.close()


def test_web_without_extension_does_not_claim_scanning_works(browser, site):
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(site + "/#extension")
    expect(page.locator("#scanner-state")).to_have_text("Extensión no conectada", timeout=7000)
    expect(page.locator("#scanner-start")).to_be_disabled()
    expect(page.locator("#scanner-open-sources")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    context.close()
