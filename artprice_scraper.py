import json
import os
import re
import time
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    pass

app = FastAPI(title="Artprice Scraper API")

# ── Keep-alive endpoint so Render doesn't cold-start ──
@app.get("/health")
def health():
    return {"status": "ok"}


def scrape_artprice():
    url = "https://www.artprice.com/artmarket-confidence-index"

    try:
        if os.name == 'nt':
            os.remove(os.path.join(os.environ.get('APPDATA', ''), 'undetected_chromedriver', 'undetected_chromedriver.exe'))
    except:
        pass

    def get_options():
        options = uc.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        # Speed optimizations
        options.add_argument('--disable-images')
        options.add_argument('--blink-settings=imagesEnabled=false')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-logging')
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        return options

    try:
        driver = uc.Chrome(options=get_options())
        driver.set_page_load_timeout(20)
    except Exception as e:
        return {"error": f"Failed to initialize Chrome: {str(e)}"}

    try:
        driver.get(url)

        # Wait for key element instead of fixed sleep
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.ID, "main_content"))
            )
        except:
            time.sleep(3)

        html = driver.page_source

        # ── Server-side parsing: extract all data in Python ──
        parsed = parse_html(html)

        # ── Extract all 5 chart types in ONE JavaScript call ──
        charts = extract_all_charts(driver)
        parsed["charts"] = charts

    except Exception as e:
        parsed = {"error": str(e)}
    finally:
        try:
            driver.quit()
        except:
            pass

    return parsed


def parse_html(html):
    """Parse AMCI values, confidence level, intraday, and sentiment bars from HTML."""
    result = {
        "amci_value": None,
        "confidence_level": None,
        "intraday": None,
        "sentiments": {}
    }

    # 1. AMCI from __PRELOADED_STATE__
    try:
        m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{[\s\S]*?\});', html)
        if m:
            state = json.loads(m.group(1))
            result["amci_value"] = state.get("footer", {}).get("lastAmciValue")
    except:
        pass

    # 2. Confidence Level — skip CSS class numbers like font-16
    m = re.search(r'Market Confidence Level:[\s\S]*?<div[^>]*>\s*([\d]+\.?\d*)', html)
    if m:
        result["confidence_level"] = m.group(1)

    # 3. Intraday
    m = re.search(r'Intraday progression:[\s\S]*?([+-]?\d+\s*%)', html)
    if m:
        result["intraday"] = m.group(1).strip()

    # 4. Sentiment progress bars
    bars = re.findall(r'progress-bar-(success|danger)[^>]*>[\s\n]*(\d+)%', html)
    labels = [
        ("artworks_strong", "artworks_weak"),
        ("financial_better", "financial_worse"),
        ("economic_favorable", "economic_unfavorable"),
        ("prices_rise", "prices_fall"),
    ]
    for i, (pos_key, neg_key) in enumerate(labels):
        if i * 2 + 1 < len(bars):
            result["sentiments"][pos_key] = bars[i * 2][1] + "%"
            result["sentiments"][neg_key] = bars[i * 2 + 1][1] + "%"

    return result


def extract_all_charts(driver):
    """Switch to Annual, then extract latest data point from all 5 chart types
    using a single optimized JavaScript execution per type."""

    charts = {}
    chart_types = [
        ("9", "barometer"),
        ("1,5", "artworks_acquisition"),
        ("2,6", "financial_situation"),
        ("3,7", "economic_climate"),
        ("4,8", "art_prices"),
    ]

    # Select Annual period once
    try:
        driver.execute_script("""
            const sel = document.querySelector('select.form-control');
            if (sel) { sel.value = 'year'; sel.dispatchEvent(new Event('change', {bubbles: true})); }
        """)
        time.sleep(1.5)
    except:
        pass

    for radio_value, chart_name in chart_types:
        try:
            # Click radio + extract in one go, with minimal wait
            result = driver.execute_script(f"""
                const radio = document.querySelector('input[type="radio"][value="{radio_value}"]');
                if (radio) radio.click();
                return true;
            """)
            time.sleep(1)  # minimal wait for chart re-render

            latest = driver.execute_script("""
                const svg = document.querySelector('.recharts-surface');
                if (!svg) return null;
                const yTicks = [];
                svg.querySelectorAll('.recharts-yAxis .recharts-cartesian-axis-tick').forEach(tick => {
                    const line = tick.querySelector('line');
                    const text = tick.querySelector('text tspan');
                    if (line && text) {
                        yTicks.push({ y: parseFloat(line.getAttribute('y1')), val: parseFloat(text.textContent) });
                    }
                });
                if (yTicks.length < 2) return null;
                yTicks.sort((a, b) => a.y - b.y);
                const y0 = yTicks[0].y, v0 = yTicks[0].val;
                const y1 = yTicks[yTicks.length-1].y, v1 = yTicks[yTicks.length-1].val;
                function yToVal(yPx) { return v0 + (yPx - y0) / (y1 - y0) * (v1 - v0); }
                const lines = {};
                svg.querySelectorAll('.recharts-line path').forEach(path => {
                    const name = path.getAttribute('name');
                    const d = path.getAttribute('d');
                    if (!name || !d || d.length < 5) { lines[name] = null; return; }
                    const coords = d.match(/[\\d.]+,[\\d.]+/g);
                    if (!coords || coords.length === 0) { lines[name] = null; return; }
                    const lastY = parseFloat(coords[coords.length-1].split(',')[1]);
                    lines[name] = Math.round(yToVal(lastY) * 100) / 100;
                });
                return lines;
            """)
            charts[chart_name] = latest
        except:
            charts[chart_name] = None

    return charts


@app.get("/scrape-artprice")
def api_scrape_artprice():
    result = scrape_artprice()
    return JSONResponse(content=result)


if __name__ == "__main__":
    print("Starting Artprice Scraper Server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
