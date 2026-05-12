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

def get_intercepted_data(driver):
    """Extract raw JSON data intercepted from fetch/XHR."""
    try:
        return driver.execute_script("return window.__API_INTERCEPT__;")
    except:
        return {}

def scrape_artprice():
    url = "https://www.artprice.com/artmarket-confidence-index"
    
    # Clean up profile on Windows
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
        # Inject interceptor BEFORE page loads
        interceptor_script = """
            window.__API_INTERCEPT__ = {};
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : 'unknown');
                const response = await origFetch.apply(this, args);
                const clone = response.clone();
                clone.text().then(text => {
                    try { window.__API_INTERCEPT__[url] = JSON.parse(text); } catch(e) {}
                });
                return response;
            };
            const origXhrOpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url) {
                this._url = url;
                this.addEventListener('load', function() {
                    try { window.__API_INTERCEPT__[this._url] = JSON.parse(this.responseText); } catch(e) {}
                });
                origXhrOpen.apply(this, arguments);
            };
        """
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': interceptor_script})
        
        driver.get(url)
        time.sleep(5)
        
        html = driver.page_source
        
        charts = {}
        chart_types = [
            ("9", "barometer"),
            ("1,5", "artworks_acquisition"),
            ("2,6", "financial_situation"),
            ("3,7", "economic_climate"),
            ("4,8", "art_prices"),
        ]

        # Select Annual
        try:
            driver.execute_script("const sel = document.querySelector('select.form-control'); if (sel) { sel.value = 'year'; sel.dispatchEvent(new Event('change', {bubbles: true})); }")
            time.sleep(2)
        except:
            pass

        # We will collect the SVG fallbacks just in case the interceptor misses something
        def get_svg_fallback():
            return driver.execute_script("""
                const svg = document.querySelector('.recharts-surface');
                if (!svg) return null;
                const yTicks = [];
                svg.querySelectorAll('.recharts-yAxis .recharts-cartesian-axis-tick').forEach(tick => {
                    const line = tick.querySelector('line');
                    const text = tick.querySelector('text tspan');
                    if (line && text) yTicks.push({ y: parseFloat(line.getAttribute('y1')), val: parseFloat(text.textContent) });
                });
                if (yTicks.length < 2) return null;
                yTicks.sort((a, b) => a.y - b.y);
                const y0 = yTicks[0].y, v0 = yTicks[0].val, y1 = yTicks[yTicks.length - 1].y, v1 = yTicks[yTicks.length - 1].val;
                const lines = {};
                svg.querySelectorAll('.recharts-line path').forEach(path => {
                    const name = path.getAttribute('name');
                    const d = path.getAttribute('d');
                    if (!name || !d || d.length < 5) return;
                    const coords = d.match(/[\\d.]+,[\\d.]+/g);
                    if (!coords) return;
                    const lastY = parseFloat(coords[coords.length - 1].split(',')[1]);
                    lines[name] = Math.round((v0 + (lastY - y0) / (y1 - y0) * (v1 - v0)) * 100) / 100;
                });
                return lines;
            """)

        for radio_value, chart_name in chart_types:
            try:
                driver.execute_script(f'const radio = document.querySelector(\\'input[type="radio"][value="{radio_value}"]\\'); if (radio) radio.click();')
                time.sleep(1)
                charts[chart_name] = get_svg_fallback()
            except:
                charts[chart_name] = None
                
        # Get exact intercepted API data
        api_data = get_intercepted_data(driver)
        
        data = {"data": html, "charts": charts, "api_data": api_data}
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
