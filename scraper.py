import re
import hashlib

import os
import pickle

from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, urljoin, urldefrag, urlsplit
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse, parse_qsl
from bs4 import BeautifulSoup
from collections import Counter



MAX_BYTES = 5_000_000
COUNTED_TEXT_URLS = set()
# Global set to store seen 8-bit fingerprints across the crawl
SIMHASHES = set()
# Cache dictionary to store rfp instances per domain
ROBOTS_CACHE = dict()
# 1. Unique URLs found
UNIQUE_URLS = set()
# 2. Longest page tracking
LONGEST_PAGE = ("", 0)
# 3. Frequency counter for overall words
WORD_FREQUENCIES = Counter()
# 4. Dictionary mapping subdomains to sets of unique pages
SUBDOMAIN_PAGE_MAP = dict()
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



def scraper(url, resp) -> list:
    """
    Processes the page the URL links to
    """
    if resp is None:
        return []

    return extract_next_links(url, resp)

def extract_next_links(url, resp) -> list:
    """
    Returns a list of URLS found in the given page
    """
    # Implementation required.
    # url: the URL that was used to get the page
    # resp.url: the actual url of the page
    # resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
    # resp.error: when status is not 200, you can check the error here, if needed.
    # resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
    #         resp.raw_response.url: the url, again
    #         resp.raw_response.content: the content of the page!
    # Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content

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

        # Check the final URL in case the request was redirected
        if not is_valid(clean_url):
            return []

        # Only process HTML pages
        ctype = raw_response.headers.get("Content-Type", "").lower()
        if ctype and "html" not in ctype:
            return []

        content_start = raw_response.content[:1024].lstrip().lower()

        if content_start.startswith((b"%pdf-", b"pk\x03\x04", b"\x89png",b"\xff\xd8\xff")): return[]
        if b"\x00" in raw_response.content[:4096]: return[]

        # Skip unusually large responses
        if len(raw_response.content) > MAX_BYTES:
            return []

        # stop expanding duplicate paginated pages
        if is_duplicate and re.search(r"/page/\d+(?:/|$)", urlparse(clean_url).path):
            return []
          
        # Parse HTML body content using BeautifulSoup and Python's build-in html.parser function
        html_parser = BeautifulSoup(raw_response.content, "html.parser")

        if html_parser.find(["html", "head", "body"]) is None:
            return []

        track_unique_pages(clean_url) # Handles Q1
        track_longest_page_and_common_words(clean_url, html_parser) # Handles Q2 & Q3
        track_subdomains(clean_url) # Handles Q4
        
        return _extract_from_html(base_url, html_parser) # Returns 

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

def track_unique_pages(clean_url) -> None:
    """
    Stores unique urls in a set
    """

    # Tracking for Q1 in deliverables
    UNIQUE_URLS.add(clean_url)

def track_longest_page_and_common_words(clean_url, html_parser) -> None:
    """
    Updates longest page and records frequencies of 50 most common words
    """

    # updates the overall longest-page tuple, so therefore can't be a local variable
    global LONGEST_PAGE

    # Get plain text from HTML and check if fingerprint matches a previously seen page
    for element in html_parser(["script", "style", "noscript", "template"]): element.decompose()
    page_text = html_parser.get_text(separator=" ", strip=True)
    is_duplicate = _is_duplicate_page(page_text)

    # Clean text to extract words in O(n) time
    punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"

    words = [
        w
        for w in re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", page_text.lower())
        if w
    ]

    word_count = len(words)

    if word_count > LONGEST_PAGE[1]:
        LONGEST_PAGE = (clean_url, word_count)

    if clean_url not in COUNTED_TEXT_URLS:
        non_stop_words = [w for w in words if w not in STOP_WORDS]
        WORD_FREQUENCIES.update(non_stop_words)
        COUNTED_TEXT_URLS.add(clean_url)

def track_subdomains(clean_url) -> None:
    """
    Stores the number of subdomains paired with the number of unique pages in each one in a dict
    """
    
    # Subdomain tracking for ics.uci.edu for Q4 in deliverables
    parsed_url = urlparse(clean_url)
    hostname = parsed_url.hostname or ""
    
    if hostname.endswith(".ics.uci.edu"): # can't include the root domain, since the assignment asked for subdomains
        subdomain_key = hostname

        # Not in the map yet, create a set to keep track of unique subdomains.
        if subdomain_key not in SUBDOMAIN_PAGE_MAP:
            SUBDOMAIN_PAGE_MAP[subdomain_key] = set()
        SUBDOMAIN_PAGE_MAP[subdomain_key].add(clean_url)

def _extract_from_html(base_url, html_parser) -> list:
    """
    Helper function for extract_next_links. Finds and parses links found in HTML
    """
    # Use set to eliminate dupes
    url_set = set()

    # extract links and skip malformed URLs w/o stopping the page
    for link in html_parser.find_all('a'):
        href = link.get('href')

        if not isinstance(href, str):
            continue

        href = href.strip()

        if not href or href.lower().startswith(('javascript:', 'mailto:', 'tel:')): continue

        try:
            absolute_url = urljoin(base_url, href)
            absolute_url = urldefrag(absolute_url)[0]

            if is_valid(absolute_url):
                url_list.append(absolute_url)

        except(ValueError, TypeError):
            #ignore malformed links and continue processing the page
            continue
    # Convert to list
    return list(url_set)
    # Otherwise, return empty list



def is_valid(url) -> bool:
    """
    Decide whether to crawl this url or not.
    """

    # If you decide to crawl it, return True; otherwise return False.
    # There are already some conditions that return False.
    try:
        #Ensure the URL has only valid ASCII characters
        if not url.isascii():
            return False

        if len(url) > 200 or "<html" in url.lower() or "<body" in url.lower():
            return False

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        # block non-content DokuWiki actions on any allowed subdomain
        path = parsed.path.lower()
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_keys = {name.lower() for name, _ in query_pairs}

        if path.startswith("/doku.php"):
            blocked_params = {
                "do", "rev", "rev2", "oldid", "idx",
                "tab_files", "tab_details", "image", "difftype"
            }

            if query_keys & blocked_params:
                return False

            if any(name.startswith("rev2[") for name in query_keys):
                return False

        # block URL parameters used for non-content actions
        if query_keys & {"action", "replytocom", "sessionid", "phpsessid"}:
            return False

        # AVOID combinatorial filter URLs on ICS listing pages
        if parsed.hostname == "ics.uci.edu":
            if parsed.path.rstrip("/") in (
                "/happening/news",
                "/people"
            ):
                if any(
                    name.startswith("filter[")
                    for name, value in parse_qsl(parsed.query)
                ):
                    return False
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

        # skip calendar pages that keep generating different dates
        if _is_calendar_trap(url):
            return False

        # reject calendar exports and generated daily calendar pages
        query_keys = {
            key.lower()
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        }

        if query_keys & {"ical", "outlook-ical", "google-calendar"}:
            return False

        path = parsed.path.lower()

        if re.search(r"/(?:events|calendar)(?:/[^?#]*)?/\d{4}-\d{2}-\d{2}(?:/|$)", path): return False

        path = parsed.path.lower()

        # Handles infinite folder recursion traps (/a/b/a/b/a/b)
        path_segments = [seg for seg in path.split('/') if seg]
        # Allow a segment to appear twice, but block excessive repetition
        if path_segments and max(Counter(path_segments).values()) >= 3:
            return False
        # Handles extremely deep paths
        if len(path_segments) > 10:
            return False

        query = parsed.query.lower()
        full_url = url.lower()
        # Keywords that are commonly associated in traps
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
            + r"|ova|vmdk|vdi|qcow2|img"
            + r"|rm|smil|wmv|swf|wma|zip|rar|gz)$",
            path
        ):
            return False

        return True

    except TypeError:
        print("TypeError for ", url)
        return False

def _is_allowed_by_bots(url, user_agent = '*') -> bool:
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

def _is_calendar_trap(url) -> bool:
    """
    Helper function to check if url is a calendar trap
    """

    # get the url path and split it into separated parts
    parsed = urlparse(url)
    path = parsed.path.lower().rstrip("/")
    segments = [s for s in path.split("/") if s]

    #check for calendar export links
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}

    if query_keys & {"ical", "outlook-ical", "google-calendar"}: return True
    # on check dates if the url looks like a calendar page
    if not any(s in {"events", "calendar", "calendars"} for s in segments): return False

    #check for dates like 2025-10-10
    for segment in segments:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", segment): return True

    #check for dates after day or week in the url
    for i, segment in enumerate(segments):
        if segment in {"day", "week"} and i + 1 < len(segments):
            if re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", segments[i + 1]):
                return True
    
    # no calendar trap found
    return False

def _is_duplicate_page(page_text: str) -> bool:
    """
    Helper function to detect webpage duplicates using SimHash fingerprinting
    Exact and near-duplicates will produce identical or nearly identical fingerprints.
    Threshold: Hamming distance <= 1 (will be 0 for exact matches)
    """
    # If the page is empty or missing, it is a duplicate and we can safely skip it.
    if not page_text or not page_text.strip():
        return True
    # Use the below helper functions to calculate the vector and create the fingerprint.
    hashed_words = _hash_text(page_text)
    word_counts = _count_raw_words(page_text)
    vector = _compute_bitwise_vector(word_counts, hashed_words)

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



# functions for simHash, might move to a separate file later
def _get_64bit_hash(word: str) -> str:
    """Helper function to get the hash in bits so that we have a unique code """
    hash_bytes = hashlib.md5(word.encode("utf-8")).digest()
    hash_value = int.from_bytes(hash_bytes[:8], byteorder="big")
    return f"{hash_value:064b}"

def _hash_text(text: str) -> dict[str, str]:
    """
    Helper function that hashes the full text and returns a dictionary containing each word's unique hash
    """
    punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    # translate strips out unwanted punctuation in O(n) time
    cleaned_text = text.lower().translate(str.maketrans("", "", punctuation))
    words = cleaned_text.split()

    hashed_words = {}

    for word in words:
        if word in hashed_words:
            pass
        else:
            hashed_words[word] = _get_64bit_hash(word)
    return hashed_words

def _count_raw_words(text: str) -> dict[str, int]:
    """
    Helper function to count the frequency of each words in a text, and returns a dictionary containing the counts.
    """
    punctuation = "'!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    # translate strips out unwanted punctuation in O(n) time
    cleaned_text = text.lower().translate(str.maketrans("","", punctuation))
    words = cleaned_text.split()

    word_counts = {}

    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1

    return word_counts

def _compute_bitwise_vector(word_counts: dict[str, int], hashed_words: dict[str, str]):
    """
    Computes the bitwise vector for simHashing in O(n * B) time, where n is the
    number of unique words and B is the bit length (8)
    """

    v = [0] * 64

    for word, weight in word_counts.items():
        # Integer hash, since hashed_words is a string
        h = int(hashed_words[word], 2)

        for i in range(64):
            # Checking if the ith bit from the right is 1, if it is then increment weight
            if (h >> (63 - i)) & 1:
                v[i] += weight
            else:
                v[i] -= weight
    return v



def print_crawl_analytics():
    """
    Prints out the results of the crawl
    """

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

ANALYTICS_FILE = "crawl_analytics.pkl"

def save_analytics():
    """
    Write all data into a .log file
    """

    # keep all the crawl statistics together so we can save them in one file
    data = {
        "UNIQUE_URLS": UNIQUE_URLS,
        "LONGEST_PAGE": LONGEST_PAGE,
        "WORD_FREQUENCIES": WORD_FREQUENCIES,
        "SUBDOMAIN_PAGE_MAP": SUBDOMAIN_PAGE_MAP,
        "SIMHASHES": SIMHASHES,
        "COUNTED_TEXT_URLS": COUNTED_TEXT_URLS,
    }

    # write to a temporary file first so an interrupted save
    # doesn't leave us with a partially written analytics file
    temp_file = ANALYTICS_FILE + ".tmp"

    with open(temp_file, "wb") as file:
        pickle.dump(data, file)
        file.flush()
        os.fsync(file.fileno())

    # replace the old file only after the new data has been saved
    os.replace(temp_file, ANALYTICS_FILE)


def load_analytics(restart=False):
    global LONGEST_PAGE

    # a fresh crawl should start with empty statistics
    if restart:
        UNIQUE_URLS.clear()
        LONGEST_PAGE = ("", 0)
        WORD_FREQUENCIES.clear()
        SUBDOMAIN_PAGE_MAP.clear()
        SIMHASHES.clear()
        COUNTED_TEXT_URLS.clear()
        return

    # If this is the first run, there won't be anything to load yet
    if not os.path.exists(ANALYTICS_FILE):
        return

    # Load the saved statistics from the previous run
    with open(ANALYTICS_FILE, "rb") as file:
        data = pickle.load(file)

    # Restore the unique URLs we already counted
    UNIQUE_URLS.clear()
    UNIQUE_URLS.update(data["UNIQUE_URLS"])

    # Restore the longest page found so far
    LONGEST_PAGE = data["LONGEST_PAGE"]

    # introduced a new function that prevent counting the same URL's text more than once
    COUNTED_TEXT_URLS.clear()
    COUNTED_TEXT_URLS.update(data.get("COUNTED_TEXT_URLS", data["UNIQUE_URLS"]))

    # Restore the word frequencies
    WORD_FREQUENCIES.clear()
    WORD_FREQUENCIES.update(data["WORD_FREQUENCIES"])

    # Restore the subdomain page counts
    SUBDOMAIN_PAGE_MAP.clear()

    #merge http and https entries while still retaining unique urls
    for old_key, urls in data["SUBDOMAIN_PAGE_MAP"].items():
        hostname = urlparse(old_key).hostname or old_key
        if hostname.endswith(".ics.uci.edu"):
            SUBDOMAIN_PAGE_MAP.setdefault(hostname, set()).update(urls)

    # Restore the fingerprints used to detect similar pages
    SIMHASHES.clear()
    SIMHASHES.update(data["SIMHASHES"])