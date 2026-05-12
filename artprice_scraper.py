import json
import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

try:
    import undetected_chromedriver as uc
except ImportError:
    pass

app = FastAPI(title="Artprice Scraper API")

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
        options.add_argument('--disable-dev-shm-usage') # Crucial for Docker/Render
        options.add_argument('--window-size=1920,1080')
        return options
    
    try:
        driver = uc.Chrome(options=get_options())
    except Exception as e:
        return {"error": f"Failed to initialize Chrome: {str(e)}"}

    try:
        driver.get(url)
        import time
        time.sleep(5)
        html = driver.page_source
        data = {"data": html}
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

