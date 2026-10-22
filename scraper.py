import re
import hashlib

from urllib.parse import urlparse, urljoin, urldefrag, urlsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup

# Cache dictionary to store rfp instances per domain
ROBOTS_CACHE = {}
def scraper(url, resp):
    if not resp or not resp.raw_response or not resp.raw_response.content:
        return []

    return extract_next_links(url, resp)

def extract_next_links(url, resp):
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
    
    url_list = []

    # Page requested properly (Successful response)
    if resp.status == 200:
        # Extract raw response object from the response container
        raw_response = resp.raw_response

        # Return empty list if request is successful but page is empty
        if raw_response is None or not raw_response.content:
            return []
        # Determine the base URL for resolving relative links, prioritizing the raw
        # response URL over response or request URL
        base_url = getattr(raw_response, "url", None) or resp.url or url

        # Parse HTML body content using BeautifulSoup and Python's build-in html.parser function
        html_parser = BeautifulSoup(raw_response.content, "html.parser")

        # Iterate over all anchor tags (<a>) found in the parsed HTML document
        for link in html_parser.find_all('a'):

            # Extract 'href' attribute string and trim whitespace
            href = link.get('href', '').strip()
            # Skip empty href attributes or non HTTP schemes
            if href and not href.startswith(('javascript:', 'mailto:', 'tel:')):
                # Convert relative path URLS into absolute URLs
                absolute_url = urljoin(base_url, href)
                # Strip out fragment identifiers
                absolute_url = urldefrag(absolute_url)[0]

                if is_valid(absolute_url):
                    url_list.append(absolute_url)
        # Convert list to set to eliminate dupes then back
        return list(set(url_list))
        # Otherwise, return empty list

    # Check error and handle crashes appropriately
    # Handle redirects that were not automatically followed
    elif resp.status in {301, 302, 303, 307, 308}:
        # Follow redirect
        raw_response = resp.raw_response
        if raw_response is None:
            return []
        
        # Read the redirect destination from the response headers
        headers = getattr(raw_response, "headers", {})
        # Accounts for case-insensitive header keys
        location = headers.get("Location") or headers.get("location")

        if not location:
            return []
        
        # Find the absolute URL of the redirect destination
        base_url = getattr(raw_response, "url", None) or resp.url or url
        redirect_url = urljoin(base_url, location)

        redirect_url = urldefrag(redirect_url)[0]

        if is_valid(redirect_url):
            return [redirect_url]
        

    return []

    

def is_allowed_by_bots(url, user_agent = '*'):
    """
    Helper function to get robots.txt for a domain, then see if the URL can be crawled
    """
    try:
        parsed = urlparse(url)
        # Make the base domain URL (https://networklocation)
        domain = f'{parsed.scheme}://{parsed.netloc}'
        robots_url = urljoin(domain, '/robots.txt')

        if domain not in ROBOTS_CACHE:
            rfp = RobotFileParser()
            rfp.set_url(robots_url)
            try:
                rfp.read()
                ROBOTS_CACHE[domain] = rfp
            except Exception:
                # if robots.txt does not load, default to that the site allows us to crawl
                ROBOTS_CACHE[domain] = None
            ROBOTS_CACHE[domain] = rfp

        # return permission check using cached RobotFileParser
        if ROBOTS_CACHE[domain] is not None:
            return ROBOTS_CACHE[domain].can_fetch(user_agent, url)
        return True
    except Exception:
        # If there is an error, default to true to avoid blocking valid URLs
        return True


def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return False

        hostname = parsed.hostname

        if hostname is None:
            return False

        allowed_domains = [
            "ics.uci.edu",
            "cs.uci.edu",
            "informatics.uci.edu",
            "stat.uci.edu"
        ]

        # If robots.txt doesn't allow us
        if not is_allowed_by_bots(url):
            return False

        # Checks if URL's domain belongs to the specified allowed_domains
        if not any(hostname == domain or (hostname or "").endswith("." + domain) for domain in allowed_domains):
            return False

        path = parsed.path.lower()

        # Handles infinite folder recursion traps (/a/b/a/b/a/b)
        path_segments = [seg for seg in path.split('/') if seg]
        if len(path_segments) != len(set(path_segments)):
            # If directory names repeat
            return False

        # Handles extremely deep paths
        if len(path_segments) > 10:
            return False

        query = parsed.query.lower()
        full_url = url.lower()
        trap_keywords = [
            'calendar', 'event', 'date', 'action=edit', 'action=download', 'replytocom',
            'share=', 'login', 'auth', 'filter', 'sort='
        ]
        if any(keyword in full_url for keyword in trap_keywords):
            # Stop long query parameters or infinite calendar loops
            if len(query) > 100 or 'date=' in query or 'day=' in query:
                return False

        # Excludes non-HTML files, data formats, archives, and also media files
        if re.match(
            r".*\.(css|js|bmp|gif|jpe?g|ico"
            + r"|png|tiff?|mid|mp2|mp3|mp4"
            + r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
            + r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
            + r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
            + r"|epub|dll|cnf|tgz|sha1|apk|sql|json|xml|war|py"
            + r"|thmx|mso|arff|rtf|jar|csv|cpp|c|java|ics"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$",
            path
        ):
            return False

        return True

    except TypeError:
        print("TypeError for ", url)
        return False


# functions for simHash, might move to a separate file later
def get_8bit_hash(word: str) -> str:
    """
    Grabs the 8bit hash of a certain word, and returns a string containing the 8-bit binary
    string representing the word.
    """
    # returns the word as binary data
    hash_bytes = hashlib.md5(word.encode("utf-8")).digest()
    # takes first byte out of the 16 byte digest
    byte_value = hash_bytes[0]
    # 08b converts the value into 8-bit binary string
    return f'{byte_value:08b}'
def hash_text(text: str) -> dict[str, str]:
    """ Hashes the full text, and returns a dictionary containing each word's unique hash"""
    punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    # translate strips out unwanted punctuation in O(n) time
    cleaned_text = text.lower().translate(str.maketrans("", "", punctuation))
    words = cleaned_text.split()

    hashed_words = {}

    for word in words:
        if word in hashed_words:
            pass
        else:
            hashed_words[word] = get_8bit_hash(word)
    return hashed_words

def count_raw_words(text: str) -> dict[str, int]:
    """
    Counts the frequency of each words in a text, and returns a dictionary containing the counts.
    """
    punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    # translate strips out unwanted punctuation in O(n) time
    cleaned_text = text.lower().translate(str.maketrans("","", punctuation))
    words = cleaned_text.split()

    word_counts = {}

    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1

    return word_counts

def compute_bitwise_vector(word_counts: dict[str, int], hashed_words: dict[str, str]):
    """
    Computes the bitwise vector for simHashing in O(n * B) time, where n is the
    number of unique words and B is the bit length (8)
    """

    v = [0] * 8

    for word, weight in word_counts.items():
        # Integer hash, since hashed_words is a string
        h = int(hashed_words[word], 2)

        for i in range(8):
            # Checking if the ith bit from the right is 1, if it is then increment weight
            if (h >> (7 - i)) & 1:
                v[i] += weight
            else:
                v[i] -= weight
    return v