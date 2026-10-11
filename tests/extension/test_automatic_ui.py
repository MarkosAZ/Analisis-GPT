import json
import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from sports_analysis.providers.browser import parse_capture

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "extension"
READER = (EXTENSION / "reader.mjs").read_text().replace("export function", "function", 1)


def source_profile():
    constants = {
        "sport": "FOOTBALL",
        "bookmaker": "Fixture Book",
        "market": "TOTAL_GOALS",
        "period": "FULL_TIME",
        "line_type": "HALF_LINE",
        "outcome_1": "OVER",
        "outcome_2": "UNDER",
    }
    fields = {key: {"value": value} for key, value in constants.items()}
    fields.update(
        {
            "event_id": {"selector": ":scope", "attribute": "data-event-id"},
            "line": {"selector": ".line", "attribute": None},
            "odds_1": {"selector": ".price-one", "attribute": None},
            "odds_2": {"selector": ".price-two", "attribute": None},
        }
    )
    return {
        "id": "fixture",
        "version": "1",
        "label": "Public fixture",
        "url": "https://fixture.example/markets",
        "reader": "dom_fields_v1",
        "kind": "ODDS",
        "row_selector": ".market",
        "fields": fields,
    }


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
def market(browser):
    context = browser.new_context()
    page = context.new_page()

    def serve(route):
        url = route.request.url
        if "/ext/" in url:
            path = EXTENSION / url.rsplit("/", 1)[-1]
            route.fulfill(body=path.read_bytes(), content_type="text/javascript")
        else:
            route.fulfill(
                content_type="text/html",
                body="""<!doctype html><title>Public markets</title><article class="market" data-event-id="fixture-1"><span class="line">2.5</span><button class="price-one" onclick="window.betClicked=true">1.90</button><button class="price-two">2.00</button></article><div class="betslip"><span>PRIVATE BOLETA</span></div>""",
            )

    page.route("https://fixture.example/**", serve)
    page.goto("https://fixture.example/markets")
    page.evaluate(f"() => {{ {READER}; window.readRows = readPublicRows; }}")
    yield page
    context.close()


def test_reader_captures_visible_market_without_click_and_matches_python(market):
    capture = market.evaluate(
        """async profile => {
        const read = window.readRows(profile);
        const { automaticCapture, profileHash } = await import('/ext/scan-contract.mjs');
        return automaticCapture(profile, read.records[0], read.observed_at, crypto.randomUUID(), await profileHash(profile));
    }""",
        source_profile(),
    )
    parsed = parse_capture(json.dumps(capture).encode())
    assert parsed.capture_method == "AUTOMATIC_DOM"
    assert parsed.record.outcomes[0][1].as_tuple().digits == (1, 9, 0)
    assert not market.evaluate("Boolean(window.betClicked)")
    assert "PRIVATE BOLETA" not in json.dumps(capture)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("document.querySelector('.market').classList.add('betslip')", "PRIVATE_FIELD"),
        ("document.querySelector('.price-one').hidden=true", "PRIVATE_FIELD"),
        (
            "document.querySelector('.price-one').after(document.querySelector('.price-one').cloneNode(true))",
            "AMBIGUOUS_FIELD",
        ),
        ("document.title='CAPTCHA: verify you are human'", "ACCESS_RESTRICTED"),
        ("document.querySelector('.price-one').remove()", "NOT_READY"),
        (
            "for(let i=0;i<51;i++)document.body.append(document.querySelector('.market').cloneNode(true))",
            "ROW_LIMIT",
        ),
    ],
)
def test_reader_fails_closed_for_private_hidden_ambiguous_or_blocked_content(
    market, mutation, expected
):
    market.evaluate(mutation)
    assert market.evaluate("profile => window.readRows(profile)", source_profile()) == {
        "error": expected
    }


def test_bridge_rejects_other_pages_frames_and_arbitrary_urls(browser):
    context = browser.new_context()
    context.route(
        "https://markosaz.github.io/**",
        lambda route: route.fulfill(
            content_type="text/html", body="<!doctype html><title>Bridge fixture</title>"
        ),
    )
    context.add_init_script(
        "window.sent=[]; window.chrome={runtime:{sendMessage:async message=>{window.sent.push(message);return {ok:true,data:{}};}}};"
    )
    context.add_init_script((EXTENSION / "bridge.js").read_text())
    page = context.new_page()
    page.goto("https://markosaz.github.io/Analisis-GPT/")
    page.evaluate(
        "window.postMessage({channel:'sports_scan_request_v1',request_id:crypto.randomUUID(),command:'STATUS'},location.origin)"
    )
    page.wait_for_function("window.sent.length===1")
    page.evaluate(
        "window.postMessage({channel:'sports_scan_request_v1',request_id:crypto.randomUUID(),command:'START',url:'https://evil.example'},location.origin)"
    )
    page.evaluate(
        "window.postMessage({channel:'sports_scan_request_v1',request_id:crypto.randomUUID(),command:'SET_CONFIG'},location.origin)"
    )
    page.evaluate(
        "window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:null,data:{channel:'sports_scan_request_v1',request_id:crypto.randomUUID(),command:'START'}}))"
    )
    page.wait_for_timeout(100)
    assert page.evaluate("window.sent.length") == 1
    page.goto("https://markosaz.github.io/another-project/")
    page.evaluate(
        "window.postMessage({channel:'sports_scan_request_v1',request_id:crypto.randomUUID(),command:'START'},location.origin)"
    )
    page.wait_for_timeout(100)
    assert page.evaluate("window.sent.length") == 0
    context.close()


def test_profile_setup_requests_only_selected_hosts_after_user_gesture(browser):
    context = browser.new_context()

    def serve(route):
        name = route.request.url.rsplit("/", 1)[-1]
        path = EXTENSION / name
        if not path.is_file():
            route.abort()
            return
        kind = (
            "text/html"
            if name.endswith(".html")
            else "text/css"
            if name.endswith(".css")
            else "text/javascript"
        )
        csp = json.loads((EXTENSION / "manifest.json").read_text())["content_security_policy"][
            "extension_pages"
        ]
        route.fulfill(
            body=path.read_bytes(), content_type=kind, headers={"Content-Security-Policy": csp}
        )

    context.route("https://extension-ui.example/**", serve)
    context.add_init_script("""
        window.grants=[];window.config={schema_version:'browser_scan_config_v1',sources:[]};
        window.chrome={permissions:{request:async permissions=>{grants.push(permissions);return true;},remove:async()=>true},runtime:{sendMessage:async message=>{
          if(message.command==='GET_CONFIG')return {ok:true,data:window.config};
          if(message.command==='SET_CONFIG')window.config=message.config;
          return {ok:true,data:{}};
        }}};
    """)
    page = context.new_page()
    page.goto("https://extension-ui.example/scan.html")
    page.wait_for_function("document.getElementById('profiles').value.includes('schema_version')")
    page.locator("#profiles").fill(
        json.dumps({"schema_version": "browser_scan_config_v1", "sources": [source_profile()]})
    )
    page.locator("#save-sources").click()
    assert page.evaluate("window.grants.length") == 0
    page.locator("#authorized").check()
    page.locator("#save-sources").click()
    page.wait_for_function(
        "document.getElementById('scan-notice').textContent.includes('Fuentes guardadas')"
    )
    assert page.evaluate("window.grants") == [{"origins": ["https://fixture.example/*"]}]
    page.locator("#clear-sources").click()
    page.wait_for_function(
        "document.getElementById('scan-notice').textContent.includes('Fuentes eliminadas')"
    )
    assert page.evaluate("window.config.sources") == []
    context.close()
