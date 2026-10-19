import re
from urllib.parse import urlparse

def scraper(url, resp):
    links = extract_next_links(url, resp)

    return [link for link in links if is_valid(link)]

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
    return list()

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

        if not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in allowed_domains
        ):
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
