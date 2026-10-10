"""Real Chromium UI/DOM tests with mocked Chrome APIs.

The managed browser forbids loading unpacked extensions. Serve the extension's
own assets with its CSP without changing that administrative policy. Installation,
toolbar grants and sidePanel integration still need manual acceptance testing.
"""

import json
import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from sports_analysis.providers.browser import parse_capture

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "extension"


@pytest.fixture(scope="module")
def browser_context():
    executable = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            channel="chromium",
        )
        context = browser.new_context()
        context.set_default_timeout(8000)
        yield context
        context.close()
        browser.close()


@pytest.fixture
def panel(browser_context):
    page = browser_context.new_page()
    assets = {
        "panel.html": "text/html",
        "panel.css": "text/css",
        "panel.mjs": "text/javascript",
        "core.mjs": "text/javascript",
        "picker.mjs": "text/javascript",
    }
    csp = json.loads((EXTENSION / "manifest.json").read_text())["content_security_policy"][
        "extension_pages"
    ]

    def serve(route):
        name = route.request.url.rsplit("/", 1)[-1]
        if name not in assets:
            route.abort()
            return
        route.fulfill(
            body=(EXTENSION / name).read_bytes(),
            content_type=assets[name],
            headers={"Content-Security-Policy": csp},
        )

    page.route("https://extension-ui.example/**", serve)
    page.add_init_script(
        """window.chrome = window.chrome || {}; chrome.tabs = {query: async () => [{id: 42, url: 'https://fixture.example/match/1?session=private'}]};"""
    )
    page.goto("https://extension-ui.example/panel.html")
    expect(page.locator("h1")).to_contain_text("tus datos")
    yield page
    page.close()


def fill_odds(panel):
    panel.locator("#connect").click()
    expect(panel.locator("#source")).to_have_text("https://fixture.example")
    panel.locator("#kind").select_option("ODDS")
    for key, value in {
        "event_id": "fixture-1",
        "bookmaker": "Fixture Book",
        "market": "TOTAL_GOALS",
        "period": "FULL_TIME",
        "outcome_1": "OVER",
        "odds_1": "1.90",
        "outcome_2": "UNDER",
        "odds_2": "2.00",
    }.items():
        panel.locator(f"#{key}").fill(value)
    panel.locator("#line_type").select_option("HALF_LINE")
    panel.locator("#line").fill("2.5")


def test_review_export_and_python_contract(panel, tmp_path):
    fill_odds(panel)
    panel.locator("#preview").click()
    expect(panel.locator("#review")).to_be_visible()
    expect(panel.locator("#download")).to_be_disabled()
    panel.locator("#confirmed").check()
    with panel.expect_download() as download:
        panel.locator("#download").click()
    path = tmp_path / download.value.suggested_filename
    download.value.save_as(path)
    payload = path.read_bytes()
    capture = parse_capture(payload)
    assert capture.kind == "ODDS"
    assert capture.record.outcomes[0][1].as_tuple().digits == (1, 9, 0)
    assert b"session" not in payload and b"/match/" not in payload
    panel.locator("#odds_1").fill("1.95")
    expect(panel.locator("#review")).to_be_hidden()
    expect(panel.locator("#download")).to_be_disabled()


def test_navigation_and_reset_invalidate_capture(panel):
    fill_odds(panel)
    panel.locator("#preview").click()
    panel.locator("#confirmed").check()
    panel.evaluate(
        """() => { chrome.tabs.query = async () => [{id: 42, url: 'https://fixture.example/match/2'}]; }"""
    )
    panel.locator("#download").click()
    expect(panel.locator("#review")).to_be_hidden()
    expect(panel.locator("#notice")).to_contain_text("pestaña cambió")
    panel.locator("#connect").click()
    expect(panel.locator("#event_id")).to_have_value("")


@pytest.fixture
def public_page(browser_context):
    page = browser_context.new_page()
    page.route(
        "https://fixture.example/**",
        lambda route: route.fulfill(
            content_type="text/html",
            body="""
        <!doctype html><html><body style="padding-top:80px">
        <button id="price" onclick="window.accidentalClick=true">1.90</button>
        <div class="betslip"><span id="private-price">1.80</span></div>
        <form><label id="account">Account information</label><input type="password" value="private"></form>
        <span id="public-team">North FC</span>
        </body></html>""",
        ),
    )
    page.goto("https://fixture.example/match/1")
    picker = (EXTENSION / "picker.mjs").read_text().replace("export function", "function", 1)
    page.evaluate(f"() => {{ {picker}; window.beginPick = pickPublicText; }}")
    yield page
    page.close()


def begin_pick(page):
    page.evaluate(
        "() => { window.picked = null; window.beginPick().then(value => window.picked = value); }"
    )
    expect(page.locator("[data-sports-picker]")).to_have_count(1)


def pick_at(page, selector):
    box = page.locator(selector).bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("[data-sports-picker]")).to_have_count(0)
    return page.evaluate("window.picked")


def test_picker_extracts_only_selected_text_without_clicking_market(public_page):
    begin_pick(public_page)
    result = pick_at(public_page, "#price")
    assert result == {"text": "1.90", "origin": "https://fixture.example"}
    assert not public_page.evaluate("Boolean(window.accidentalClick)")


@pytest.mark.parametrize("selector", ["#private-price", "#account"])
def test_picker_rejects_betslip_and_account_fields(public_page, selector):
    begin_pick(public_page)
    result = pick_at(public_page, selector)
    assert result["error"] == "PRIVATE_FIELD"
    assert "text" not in result


def test_picker_escape_cleanup_and_synthetic_event_rejected(public_page):
    begin_pick(public_page)
    public_page.locator("[data-sports-picker]").dispatch_event(
        "click", {"clientX": 100, "clientY": 100}
    )
    expect(public_page.locator("[data-sports-picker]")).to_have_count(1)
    public_page.keyboard.press("Escape")
    expect(public_page.locator("[data-sports-picker]")).to_have_count(0)
    assert public_page.evaluate("window.picked") == {"error": "CANCELLED"}
    begin_pick(public_page)
    assert pick_at(public_page, "#public-team")["text"] == "North FC"


def test_calendar_three_way_and_dates_in_ui(panel):
    panel.locator("#connect").click()
    values = {
        "event_id": "fixture-1",
        "competition_id": "league-1",
        "competition_name": "Fixture league",
        "home_id": "north",
        "home_name": "North FC",
        "away_id": "south",
        "away_name": "South FC",
        "scheduled_start_at": "2040-02-30T20:00:00Z",
    }
    for key, value in values.items():
        panel.locator(f"#{key}").fill(value)
    panel.locator("#preview").click()
    expect(panel.locator("#review")).to_be_hidden()
    panel.locator("#scheduled_start_at").fill("2040-06-15T20:00:00-05:00")
    panel.locator("#preview").click()
    expect(panel.locator("#review")).to_be_visible()
    payload = panel.locator("#json").inner_text().encode()
    assert parse_capture(payload).kind == "CALENDAR"
    fill_odds(panel)
    panel.locator("#line_type").select_option("THREE_WAY")
    panel.locator("#outcome_3").fill("DRAW")
    panel.locator("#odds_3").fill("3.00")
    panel.locator("#preview").click()
    assert len(json.loads(panel.locator("#json").inner_text())["record"]["outcomes"]) == 3
