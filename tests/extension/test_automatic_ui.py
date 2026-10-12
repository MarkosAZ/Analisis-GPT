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
    page.locator("#advanced-profiles > summary").click()
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
    page.locator('#preset-sources input[value="sofascore"]').uncheck()
    page.locator('#preset-sources input[value="apuesta_total"]').uncheck()
    page.locator('#preset-sources input[value="flashscore_pe"]').uncheck()
    assert page.locator('#preset-sources input[value="te_apuesto"]').is_disabled()
    page.locator("#save-presets").click()
    page.wait_for_function("window.config.sources[0]?.reader==='betano_public_v1'")
    assert page.evaluate("window.grants.at(-1)") == {"origins": ["https://www.betano.pe/*"]}
    assert page.evaluate("window.config.sources.length") == 1
    context.close()


def test_betano_page_projection_excludes_private_state_and_never_clicks_or_hooks(browser):
    context = browser.new_context()
    context.route(
        "https://www.betano.pe/**",
        lambda route: route.fulfill(
            content_type="text/html",
            body="<!doctype html><title>Fixture public football</title><button onclick='window.clicked=true'>1.90</button>",
        ),
    )
    page = context.new_page()
    page.goto("https://www.betano.pe/sport/futbol/")
    page.evaluate("""() => {
      window.originalFetch=window.fetch;
      const market={name:'Total de goles',selections:[{name:'Más de 2.5',price:1.9},{name:'Menos de 2.5',price:2.0}]};
      window.initial_state={events:[{id:101,name:'Fixture Home - Fixture Away',sportId:1,markets:[market],stake:'SECRET_STAKE'}],
        wallet:{events:[{id:999,name:'PRIVATE_ACCOUNT',sportId:1,markets:[market]}]},token:'SECRET_TOKEN'};
      Object.defineProperty(window.initial_state,'accessor',{enumerable:true,get:()=>{throw new Error('MUST_NOT_READ_GETTER');}});
    }""")
    script = (EXTENSION / "source-page.mjs").read_text().replace("export function", "function", 1)
    result = page.evaluate(f"() => {{ {script}; return collectBetano(); }}")
    assert [event["id"] for event in result["events"]] == ["101"]
    assert "SECRET" not in json.dumps(result)
    assert "PRIVATE_ACCOUNT" not in json.dumps(result)
    assert page.evaluate("window.fetch === window.originalFetch && !window.clicked")
    context.route(
        "https://www.betano.pe/ext/*",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body=(EXTENSION / route.request.url.rsplit("/", 1)[-1]).read_bytes(),
        ),
    )
    capture = page.evaluate(
        """async projection => {
          const { nativeProfile } = await import('/ext/connectors.mjs');
          const { betanoRows } = await import('/ext/source-parsers.mjs');
          const { automaticCapture, profileHash } = await import('/ext/scan-contract.mjs');
          const profile=nativeProfile('betano_pe');
          return automaticCapture(profile,betanoRows(projection.events).records[0],new Date().toISOString(),crypto.randomUUID(),await profileHash(profile));
        }""",
        result,
    )
    parsed = parse_capture(json.dumps(capture).encode())
    assert parsed.capture_method == "AUTOMATIC_SOURCE"
    assert parsed.record.event_id == "101"
    page.evaluate("document.title='CAPTCHA: verify you are human'")
    assert page.evaluate(f"() => {{ {script}; return collectBetano(); }}") == {
        "error": "ACCESS_RESTRICTED"
    }
    context.close()
