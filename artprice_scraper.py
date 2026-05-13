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


def parse_svg_latest_values(driver):
    """Extract the latest data point from each SVG chart line using y-axis scale."""
    script = """
    const svg = document.querySelector('.recharts-surface');
    if (!svg) return null;

    // Get y-axis tick values and positions
    const yTicks = [];
    svg.querySelectorAll('.recharts-yAxis .recharts-cartesian-axis-tick').forEach(tick => {
        const line = tick.querySelector('line');
        const text = tick.querySelector('text tspan');
        if (line && text) {
            yTicks.push({ y: parseFloat(line.getAttribute('y1')), val: parseFloat(text.textContent) });
        }
    });
    if (yTicks.length < 2) return null;

    // Build linear scale from y-pixel to value
    yTicks.sort((a, b) => a.y - b.y);
    const y0 = yTicks[0].y, v0 = yTicks[0].val;
    const y1 = yTicks[yTicks.length - 1].y, v1 = yTicks[yTicks.length - 1].val;

    function yToValue(yPx) {
        return v0 + (yPx - y0) / (y1 - y0) * (v1 - v0);
    }

    // Extract last coordinate from each path
    const lines = {};
    svg.querySelectorAll('.recharts-line path').forEach(path => {
        // Ignore hidden or faded out paths from animations
        const strokeOpacity = window.getComputedStyle(path).strokeOpacity;
        const opacity = window.getComputedStyle(path).opacity;
        if (strokeOpacity === '0' || opacity === '0' || path.getAttribute('stroke') === 'none') {
            return;
        }

        const name = path.getAttribute('name');
        const d = path.getAttribute('d');
        if (!name || !d || d.length < 5) return;
        
        // Last coordinate pair: find the final y value
        const coords = d.match(/[\\d.]+,[\\d.]+/g);
        if (!coords || coords.length === 0) return;
        const lastCoord = coords[coords.length - 1].split(',');
        const lastY = parseFloat(lastCoord[1]);
        lines[name] = Math.round(yToValue(lastY) * 100) / 100;
    });
    return Object.keys(lines).length > 0 ? lines : null;
    """
    try:
        return driver.execute_script(script)
    except:
        return None

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
        return options

    try:
        driver = uc.Chrome(options=get_options())
    except Exception as e:
        return {"error": f"Failed to initialize Chrome: {str(e)}"}

    try:
        driver.get(url)
        time.sleep(5)
        html = driver.page_source

        # --- Extract ALL chart data in a single async JS call ---
        all_charts_script = """
        const callback = arguments[arguments.length - 1];
        const delay = ms => new Promise(r => setTimeout(r, ms));

        function readChart() {
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
                const so = window.getComputedStyle(path).strokeOpacity;
                const op = window.getComputedStyle(path).opacity;
                if (so === '0' || op === '0' || path.getAttribute('stroke') === 'none') return;
                const name = path.getAttribute('name');
                const d = path.getAttribute('d');
                if (!name || !d || d.length < 5) return;
                const coords = d.match(/[\\d.]+,[\\d.]+/g);
                if (!coords || coords.length === 0) return;
                const lastCoord = coords[coords.length - 1].split(',');
                lines[name] = Math.round(yToValue(parseFloat(lastCoord[1])) * 100) / 100;
            });
            return Object.keys(lines).length > 0 ? lines : null;
        }

        function clickRadio(val) {
            const radio = document.querySelector('input[type="radio"][value="' + val + '"]');
            if (radio) {
                const label = radio.closest('label');
                if (label) label.click(); else radio.click();
            }
        }

        (async () => {
            try {
                // Select Annual period
                const sel = document.querySelector('select.form-control');
                if (sel) { sel.value = 'year'; sel.dispatchEvent(new Event('change', {bubbles: true})); }
                await delay(2000);

                const chartTypes = [
                    ['9', 'barometer'],
                    ['1,5', 'artworks_acquisition'],
                    ['2,6', 'financial_situation'],
                    ['3,7', 'economic_climate'],
                    ['4,8', 'art_prices']
                ];
                const results = {};
                for (const [val, name] of chartTypes) {
                    clickRadio(val);
                    await delay(1500);
                    results[name] = readChart();
                }
                callback(results);
            } catch(e) {
                callback({error: e.message});
            }
        })();
        """

        driver.set_script_timeout(30)
        charts = driver.execute_async_script(all_charts_script) or {}

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
