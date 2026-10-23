import re
import hashlib

from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, urljoin, urldefrag, urlsplit, parse_qsl
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from collections import Counter, defaultdict

# Global set to store seen 8-bit fingerprints across the crawl
SIMHASHES = set()
# Cache dictionary to store rfp instances per domain
ROBOTS_CACHE = {}
# 1. Unique URLs found
UNIQUE_URLS = set()
# 2. Longest page tracking
LONGEST_PAGE = ("", 0)
# 3. Frequency counter for overall words
WORD_FREQUENCIES = Counter()
# 4. Dictionary mapping subdomains to sets of unique pages
SUBDOMAIN_PAGE_MAP = {}
# English stop words
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
    "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't",
    "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}

# URL patterns and pattern limit
# URL_PATTERN_URLS = defaultdict(set)
# URL_PATTERN_LIMIT = 3

URL_PATTERN_VARIANTS = defaultdict(set)

# One meaningful query variant is allowed for each host/path.
MAX_QUERY_VARIANTS = 1

# Generic parameters commonly used for UI, media, navigation,
# sorting, filtering, and session state.
UI_QUERY_KEYS = {
    "action",
    "cmd",
    "do",
    "edit",
    "filter",
    "image",
    "idx",
    "login",
    "mode",
    "namespace",
    "ns",
    "page",
    "replytocom",
    "search",
    "sort",
    "tab",
    "tab_details",
    "tab_files",
    "view",
}


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
    
    # updates the overall longest-page tupe, so therefore can't be a local variable
    global LONGEST_PAGE
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
        clean_url = urldefrag(base_url)[0]

        # Tracking for Q1 in deliverables
        UNIQUE_URLS.add(clean_url)
        # Subdomain tracking for ics.uci.edu for Q4 in deliverables
        parsed_url = urlparse(clean_url)
        hostname = parsed_url.hostname or ""
        if hostname.endswith(".ics.uci.edu") or hostname == "ics.uci.edu":
            subdomain_key = f'{parsed_url.scheme}://{hostname}'
            # Not in the map yet, create a set to keep track of unique subdomains.
            if subdomain_key not in SUBDOMAIN_PAGE_MAP:
                SUBDOMAIN_PAGE_MAP[subdomain_key] = set()
            SUBDOMAIN_PAGE_MAP[subdomain_key].add(clean_url)


        # Parse HTML body content using BeautifulSoup and Python's build-in html.parser function
        html_parser = BeautifulSoup(raw_response.content, "html.parser")

        # Get plain text from HTML and check if fingerprint matches a previously seen page
        page_text = html_parser.get_text()
        if is_duplicate_page(page_text):
            return []

        # Clean text to extract words in O(n) time
        punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
        cleaned_text = page_text.lower().translate(str.maketrans("","",punctuation))
        words = [w for w in cleaned_text.split() if len(w) > 1]

        # Check for longest page for Q2 in deliverables
        word_count = len(words)
        if word_count > LONGEST_PAGE[1]:
            LONGEST_PAGE = (clean_url, word_count)

        # Filter stop words and record frequencies across pages for Q3 in deliverables
        non_stop_words = [w for w in words if w not in STOP_WORDS]
        WORD_FREQUENCIES.update(non_stop_words)

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
            # Specifically catches web request timeouts, HTTP failures, connection issues, or URL parsing errors
            except (URLError, HTTPError, OSError, ValueError):
                # if robots.txt does not load, default to that the site allows us to crawl
                ROBOTS_CACHE[domain] = None

        # return permission check using cached RobotFileParser
        if ROBOTS_CACHE[domain] is not None:
            return ROBOTS_CACHE[domain].can_fetch(user_agent, url)
        return True
    except (URLError, HTTPError, OSError, ValueError):
        # If there is an error, default to true to avoid blocking valid URLs
        return True

def get_url_pattern(url):
    """
    Groups URLs with the same host, path structure,
    and query parameter names.
    """
    parsed = urlparse(url)

    # Replace numeric path components with a placeholder
    path_pattern = re.sub(r"/\d+(?=/|$)", "/<id>", parsed.path.lower())

    # Extract and normalize query parameter names from URL
    # query_keys = tuple(sorted(
    #     key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    # ))

    return (
        (parsed.hostname or "").lower(),
        path_pattern
    )

def is_valid(url):
    # Decide whether to crawl this url or not. 
    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        #Ensure the URL has only valid ASCII characters
        if not url.isascii():
            return False

        if len(url) > 200 or "<html" in url.lower() or "<body" in url.lower():
            return False

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

        # Trap detection based on repeated/similar URL patterns
                # Apply query-based trap detection.
        query_pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        # Base paths without a query are allowed.
        if not query_pairs:
            return True

        query_keys = {
            key.lower()
            for key, _ in query_pairs
            if key
        }

        # Reject queries made entirely of generic UI/media/navigation
        # parameters. This catches combinations such as:
        # ?do=media&tab_files=files&tab_details=view&image=...
        if query_keys and query_keys.issubset(UI_QUERY_KEYS):
            return False

        pattern = get_url_pattern(url)
        normalized_url = urldefrag(url)[0]
        variants = URL_PATTERN_VARIANTS[pattern]

        # Do not count the same URL repeatedly.
        if normalized_url in variants:
            return False

        # Allow one meaningful query variant, then reject later variants.
        if len(variants) >= MAX_QUERY_VARIANTS:
            return False

        variants.add(normalized_url)
        # if parsed.query:
        #     pattern = get_url_pattern(url)
        #     normalized_url = urldefrag(url)[0]

        #     URL_PATTERN_URLS[pattern].add(normalized_url)
            
        #     if len(URL_PATTERN_URLS[pattern]) > URL_PATTERN_LIMIT:
        #         return False

        return True

    except TypeError:
        print("TypeError for ", url)
        return False

def is_duplicate_page(page_text: str) -> bool:
    """
    Detects webpage duplicates using SimHash fingerprinting
    Exact and near-duplicates will produce identical or nearly identical fingerprints.
    Threshold: Hamming distance <= 1 (will be 0 for exact matches)
    """

    if not page_text or not page_text.strip():
        return True
    hashed_words = hash_text(page_text)
    word_counts = count_raw_words(page_text)
    vector = compute_bitwise_vector(word_counts, hashed_words)

    # Convert the bitwise vector to binary string fingerprint
    fingerprint = "".join("1" if x > 0 else "0" for x in vector)

    # Check Hamming distance against previously seen fingerprints
    for seen_fp in SIMHASHES:
        hamming_distance = sum(b1 != b2 for b1, b2 in zip(fingerprint, seen_fp))
        # Distance = 0 if exact duplicate, <= 1 is near-duplicate
        if hamming_distance <= 1:
            return True

    # If unique fingerprint, then store it and return false.
    SIMHASHES.add(fingerprint)
    return False

def print_crawl_analytics():
    print("=" * 50)
    print("CRAWL SUMMARY & ANSWERS")
    print("=" * 50)

    # Q1: Total Unique Pages
    print(f"\n1. Total Unique Pages Found: {len(UNIQUE_URLS)}")

    # Q2: Longest Page
    print(f"\n2. Longest Page: {LONGEST_PAGE[0]} with {LONGEST_PAGE[1]} words")

    # Q3: 50 Most Common Words
    print("\n3. Top 50 Most Common Words (excluding stop words):")
    for rank, (word, freq) in enumerate(WORD_FREQUENCIES.most_common(50), 1):
        print(f"   {rank}. {word}: {freq}")

    # Q4: Subdomains in ics.uci.edu
    print("\n4. Subdomains in ics.uci.edu (alphabetical):")
    for subdomain in sorted(SUBDOMAIN_PAGE_MAP.keys()):
        count = len(SUBDOMAIN_PAGE_MAP[subdomain])
        print(f"   {subdomain}, {count}")

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
