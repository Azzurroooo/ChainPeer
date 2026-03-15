
"""网络搜索与抓取工具"""
import requests
from bs4 import BeautifulSoup
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from markdownify import markdownify as md
    HAS_MD = True
except ImportError:
    HAS_MD = False

def search_web(query: str, max_results: int = 5) -> str:
    """
    使用 Bing 搜索互联网 (无需 API Key)。
    注意：这是一个简单的爬虫，可能会因为反爬策略失效。
    :param query: 搜索关键词
    :param max_results: 返回结果数量 (默认 5)
    """
    try:
        url = "https://www.bing.com/search"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
        }
        params = {"q": query}
        
        # 使用 verify=False 避免 SSL 证书问题
        response = requests.get(url, params=params, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        results = []
        # Bing 结果结构 (li class="b_algo")
        for result in soup.find_all("li", class_="b_algo", limit=max_results):
            title_tag = result.find("h2")
            if title_tag:
                link_tag = title_tag.find("a")
                if link_tag:
                    title = link_tag.get_text(strip=True)
                    link = link_tag.get("href")
                    
                    # 尝试寻找摘要
                    snippet = ""
                    caption = result.find("div", class_="b_caption")
                    if caption:
                        p_tag = caption.find("p")
                        if p_tag:
                            snippet = p_tag.get_text(strip=True)
                    
                    if title and link:
                        results.append(f"Title: {title}\nURL: {link}\nSnippet: {snippet}\n")
        
        if not results:
            # 备用：尝试 DuckDuckGo (如果 Bing 失败)
            return _search_ddg(query, max_results)
            
        return "\n---\n".join(results)
    except Exception as e:
        return f"搜索错误: {e}"

def _search_ddg(query: str, max_results: int) -> str:
    """备用：DuckDuckGo 搜索"""
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://html.duckduckgo.com/"
        }
        data = {"q": query}
        response = requests.post(url, data=data, headers=headers, timeout=10, verify=False)
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        for result in soup.find_all("div", class_="result", limit=max_results):
            title_tag = result.find("a", class_="result__a")
            snippet_tag = result.find("a", class_="result__snippet")
            if title_tag and snippet_tag:
                results.append(f"Title: {title_tag.get_text(strip=True)}\nURL: {title_tag['href']}\nSnippet: {snippet_tag.get_text(strip=True)}\n")
        return "\n---\n".join(results) if results else f"未找到关于 '{query}' 的搜索结果。"
    except Exception as e:
        return f"搜索错误 (Bing & DDG): {e}"

def fetch_web_page(url: str) -> str:
    """
    抓取网页内容并转换为 Markdown 格式。
    :param url: 目标网页 URL
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        # 使用 verify=False 避免 SSL 证书问题
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        
        # 自动检测编码
        response.encoding = response.apparent_encoding
        
        html_content = response.text
        
        if HAS_MD:
            # 使用 markdownify 转换为 Markdown
            content = md(html_content, heading_style="ATX")
        else:
            # 回退到简单的文本提取
            soup = BeautifulSoup(html_content, "html.parser")
            # 移除脚本和样式
            for script in soup(["script", "style"]):
                script.decompose()
            content = soup.get_text(separator="\n\n")
            
        # 简单的清理：移除过多空行
        lines = [line.strip() for line in content.splitlines()]
        clean_content = "\n".join(line for line in lines if line)
        
        # 限制返回长度
        if len(clean_content) > 20000:
             clean_content = clean_content[:20000] + "\n\n... (Content truncated due to length) ..."
             
        return f"URL: {url}\n\n{clean_content}"
        
    except Exception as e:
        return f"抓取错误: {e}"
