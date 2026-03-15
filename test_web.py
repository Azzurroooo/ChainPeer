
from tools.web import search_web, fetch_web_page

def test_search():
    print("Testing search_web...")
    results = search_web("Python programming", max_results=3)
    print(results)

def test_fetch():
    print("\nTesting fetch_web_page...")
    # Fetch a simple page, e.g., example.com
    content = fetch_web_page("https://example.com")
    print(content[:500]) # Print first 500 chars

if __name__ == "__main__":
    test_search()
    test_fetch()
