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
        time.sleep(6)
        html = driver.page_source

        # --- Extract chart data for all 5 types with Annual period ---
        charts = {}
        chart_types = [
            ("9", "barometer"),
            ("1,5", "artworks_acquisition"),
            ("2,6", "financial_situation"),
            ("3,7", "economic_climate"),
            ("4,8", "art_prices"),
        ]

        # Select "Annual" period
        try:
            driver.execute_script("""
                const sel = document.querySelector('select.form-control');
                if (sel) {
                    sel.value = 'year';
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                }
            """)
            time.sleep(3)
        except:
            pass

        for radio_value, chart_name in chart_types:
            try:
                driver.execute_script("""
                    const radio = document.querySelector('input[type="radio"][value="{{radio_value}}"]');
                    if (radio) {
                        const label = radio.closest('label');
                        if (label) {
                            label.click();
                        } else {
                            radio.click();
                        }
                    }
                """.replace("{{radio_value}}", radio_value))
                time.sleep(4)
                latest = parse_svg_latest_values(driver)
                charts[chart_name] = latest
            except:
                charts[chart_name] = None

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
