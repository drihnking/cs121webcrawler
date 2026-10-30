
from collections import deque
from threading import Lock
from urllib.parse import urlparse, urljoin, urldefrag
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET
import gzip
import io

from utils.download import download
from utils import get_logger
from scraper import is_valid


class RobotsManager:
    def __init__(self, config, frontier):
        self.config = config
        self.frontier = frontier
        self.logger = get_logger("ROBOTS")
        self.lock = Lock()

        # store robots rules so we don't fetch them for every url
        self.policies = {}

        # keep track of robots and sitemap activity for the report
        self.blocked = 0
        self.sitemap_urls = 0

    @staticmethod
    def origin(url):
        # get the base website for its robots.txt file
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc.lower()}"

    def fetch(self, url, delay=0):
        # use the assignment's cache instead of requesting sites directly
        for _ in range(4):
            self.frontier.wait_for_domain(url, delay)
            response = download(url, self.config, self.logger)

            if response.status not in {301, 302, 303, 307, 308}:
                return response

            # some sites redirect their robots or sitemap files
            headers = getattr(response.raw_response, "headers", {}) or {}
            location = headers.get("Location") or headers.get("location")

            if not location:
                return response

            target = urldefrag(urljoin(url, location))[0]
            parsed = urlparse(target)
            host = (parsed.hostname or "").lower()

            roots = (
                "ics.uci.edu",
                "cs.uci.edu",
                "informatics.uci.edu",
                "stat.uci.edu"
            )

            # don't follow redirects outside the allowed domains
            if parsed.scheme not in ("http", "https"):
                return response

            if not any(host == d or host.endswith("." + d) for d in roots):
                return response

            url = target

        return response

    def policy(self, url):
        origin = self.origin(url)

        # lock this section so two workers don't fetch the same rules
        with self.lock:
            if origin in self.policies:
                return self.policies[origin]

            resp = self.fetch(origin + "/robots.txt")
            rules, delay, maps = None, 0, []

            if resp.status == 200:
                content = getattr(resp.raw_response, "content", b"") or b""

                # ignore unusually large robots files
                if 0 < len(content) <= 512 * 1024:
                    rules = RobotFileParser()
                    rules.parse(
                        content.decode("utf-8-sig", "replace").splitlines()
                    )

                    delay = rules.crawl_delay(self.config.user_agent) or 0
                    maps = rules.site_maps() or []

            # a missing robots file means there are no published restrictions
            missing = resp.status in {404, 410}

            self.policies[origin] = (rules, delay, missing)

            self.logger.info(
                "robots.txt %s status=%s", origin, resp.status
            )

            # check the listed sitemaps and the usual sitemap location
            if rules is not None or missing:
                self.load_sitemaps(origin, maps, rules, delay)

            return self.policies[origin]

    def allowed(self, url):
        rules, _, missing = self.policy(url)

        # a missing robots.txt file has no published restrictions
        if missing:
            return True

        # if the cache couldn't retrieve robots.txt, don't assume
        # the site explicitly allowed or disallowed the page
        if rules is None:
            return None

        # check whether this url is allowed by the site's rules
        permitted = rules.can_fetch(self.config.user_agent, url)

        if not permitted:
            self.blocked += 1

        return permitted

    def crawl_delay(self, url):
        # some sites ask crawlers to wait longer between requests
        return self.policy(url)[1]

    def load_sitemaps(self, origin, declared, rules, delay):
        # start with the sitemaps listed in robots.txt
        # also try the default sitemap.xml location
        queue = deque(list(declared) + [origin + "/sitemap.xml"])
        seen = set()
        files = pages = 0

        # limit how many sitemap files and links we process per site
        while queue and files < 5 and pages < 200:
            candidate = urldefrag(
                urljoin(origin + "/", queue.popleft())
            )[0]

            if candidate in seen or self.origin(candidate) != origin:
                continue

            seen.add(candidate)

            # don't fetch a sitemap if robots.txt disallows it
            if rules and not rules.can_fetch(
                self.config.user_agent, candidate
            ):
                continue

            files += 1
            resp = self.fetch(candidate, delay)

            if resp.status != 200 or resp.raw_response is None:
                continue

            content = getattr(resp.raw_response, "content", b"") or b""

            # skip empty or oversized sitemap responses
            if not content or len(content) > 2 * 1024 * 1024:
                continue

            # some sitemaps are compressed to save space
            if content.startswith(b"\x1f\x8b"):
                try:
                    with gzip.GzipFile(
                        fileobj=io.BytesIO(content)
                    ) as stream:
                        content = stream.read(2 * 1024 * 1024 + 1)
                except (OSError, EOFError):
                    continue

            if len(content) > 2 * 1024 * 1024:
                continue

            try:
                root = ET.fromstring(content)
            except ET.ParseError:
                continue

            # sitemap indexes link to other sitemap files
            # regular sitemaps contain actual page urls
            kind = root.tag.split("}")[-1].lower()

            if kind not in ("sitemapindex", "urlset"):
                continue

            for entry in root:
                expected = "sitemap" if kind == "sitemapindex" else "url"

                if entry.tag.split("}")[-1].lower() != expected:
                    continue

                loc = next(
                    (el.text.strip() for el in entry
                     if el.tag.split("}")[-1].lower() == "loc" and el.text),
                    None
                )

                if not loc:
                    continue

                target = urldefrag(urljoin(candidate, loc))[0]

                if kind == "sitemapindex":
                    # add nested sitemap files to the queue
                    if self.origin(target) == origin:
                        queue.append(target)

                elif (
                    pages < 200
                    and is_valid(target)
                    and (
                        not rules
                        or self.origin(target) != origin
                        or rules.can_fetch(self.config.user_agent, target)
                    )
                ):
                    # send valid page urls to the existing frontier
                    self.frontier.add_url(target)
                    pages += 1

        self.sitemap_urls += pages

        self.logger.info(
            "Sitemaps %s: %d files checked, %d URLs submitted",
            origin, files, pages
        )

