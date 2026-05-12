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
except ImportError:
    pass

app = FastAPI(title="Artprice Scraper API")


EXTRACT_ALL_CHARTS_JS = """
// Single JS call: select Annual, iterate all 5 radio types, extract SVG data
// Returns a Promise that resolves with all chart data

async function extractAllCharts() {
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function parseLatestFromSVG() {
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
        const y1 = yTicks[yTicks.length - 1].y, v1 = yTicks[yTicks.length - 1].val;
        function yToValue(yPx) { return v0 + (yPx - y0) / (y1 - y0) * (v1 - v0); }
        const lines = {};
        svg.querySelectorAll('.recharts-line path').forEach(path => {
            const name = path.getAttribute('name');
            const d = path.getAttribute('d');
            if (!name || !d || d.length < 5) { lines[name] = null; return; }
            const coords = d.match(/[\\d.]+,[\\d.]+/g);
            if (!coords || coords.length === 0) { lines[name] = null; return; }
            const lastCoord = coords[coords.length - 1].split(',');
            lines[name] = Math.round(yToValue(parseFloat(lastCoord[1])) * 100) / 100;
        });
        return lines;
    }

    // Select Annual period
    const sel = document.querySelector('select.form-control');
    if (sel) {
        sel.value = 'year';
        sel.dispatchEvent(new Event('change', {bubbles: true}));
    }
    await sleep(1500);

    const types = [
        ["9", "barometer"],
        ["1,5", "artworks_acquisition"],
        ["2,6", "financial_situation"],
        ["3,7", "economic_climate"],
        ["4,8", "art_prices"]
    ];

    const result = {};
    for (const [val, name] of types) {
        const radio = document.querySelector('input[type="radio"][value="' + val + '"]');
        if (radio) radio.click();
        await sleep(1200);
        result[name] = parseLatestFromSVG();
    }
    return result;
}

return extractAllCharts();
"""


def scrape_artprice():
    url = "https://www.artprice.com/artmarket-confidence-index"

    # Clean up profile on Windows (ignore on Linux/Render)
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
        options.add_argument('--blink-settings=imagesEnabled=false')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-logging')
        options.page_load_strategy = 'eager'
        return options

    try:
        driver = uc.Chrome(options=get_options())
    except Exception as e:
        return {"error": f"Failed to initialize Chrome: {str(e)}"}

    try:
        driver.get(url)
        time.sleep(3)
        html = driver.page_source

        # Single JS call extracts all 5 chart types with Annual period
        charts = {}
        try:
            charts = driver.execute_async_script("""
                const callback = arguments[arguments.length - 1];
                """ + EXTRACT_ALL_CHARTS_JS.replace("return extractAllCharts();", "extractAllCharts().then(callback);"))
            if not charts:
                charts = {}
        except Exception as e:
            charts = {}

        data = {"data": html, "charts": charts}
    except Exception as e:
        data = {"error": str(e), "data": ""}
    finally:
        try:
            driver.quit()
        except:
            pass

    return data


@app.get("/scrape-artprice")
def api_scrape_artprice():
    result = scrape_artprice()
    return JSONResponse(content=result)


if __name__ == "__main__":
    print("Starting Artprice Scraper Server on port 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
