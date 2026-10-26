
import shelve
import time
from collections import Counter, deque
from threading import Condition, Lock
from urllib.parse import urlparse, parse_qsl

from utils import get_logger, get_urlhash, normalize
from scraper import is_valid


class Frontier:
    """Coordinate URLs, persistent progress, and polite request timing across workers."""

    def __init__(self, config, restart):
        self.logger = get_logger("FRONTIER")
        self.config = config

        # A condition lock protects the queue, outstanding count, and shelve DB.
        # It also lets idle threads sleep until another worker discovers URLs.
        self.condition = Condition()
        self.to_be_downloaded = deque()

        # Number of queued OR currently in-progress URLs, used to detect completion.
        self.outstanding = 0

        # track how many URLs have been accepted for each query pattern
        self.query_pattern_counts = Counter()

        # Separate lock reserves request slots without blocking frontier queue access.
        self.politeness_lock = Lock()
        self.next_request_time = {}

        # Shelve must only be read/written while holding self.condition.
        if restart:
            # shelve may use multiple files; clear it via shelve rather than os.remove.
            with shelve.open(config.save_file) as old:
                old.clear()

        self.save = shelve.open(config.save_file)

        # restore saved URL patterns and unfinished crawl work
        for url, complete in self.save.values():
            pattern = self.query_pattern(url)

            if pattern is not None:
                self.query_pattern_counts[pattern] += 1

            if not restart and not complete and is_valid(url):
                self.to_be_downloaded.append(url)
                self.outstanding += 1

        if self.outstanding == 0 and not self.save:
            for url in config.seed_urls:
                self.add_url(url.strip())

        self.logger.info("Loaded %d outstanding URLs", self.outstanding)

    def get_tbd_url(self):
        """returns the next URL, waits for the new work, OR return NONE when done"""
        with self.condition:
            while not self.to_be_downloaded and self.outstanding > 0:
                self.condition.wait()

            if self.outstanding == 0:
                return None

            return self.to_be_downloaded.popleft()

    @staticmethod
    def query_pattern(url):
        # group urls by hostname, path & query parameter names
        parsed = urlparse(url)

        if not parsed.query:
            return None

        keys = tuple(sorted({key.lower()
                             for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}))

        return((parsed.hostname or "").lower(), parsed.path.lower(), keys)

    @staticmethod
    def query_budget(pattern):
        #give content identifiers more room than generic query pages
        keys = set(pattern[2])

        if keys and keys.issubset({"id", "p", "article", "post", "newsid"}): return 1000

        return 80

    def add_url(self, url):
        """validate, deduplicate and enqueue URLs withint the pattern budget"""
        url = normalize(url)

        if not is_valid(url):
            return

        urlhash = get_urlhash(url)

        with self.condition:
            # skip urls that's already stored in frontier
            if urlhash in self.save:
                return

            #prevent excessive variations of the same URL structure
            pattern = self.query_pattern(url)

            if pattern is not None:
                budget = self.query_budget(pattern)

                if self.query_pattern_counts[pattern] >= budget:
                    return

            # persist the discovered url before workers can retrieve it
            self.save[urlhash] = (url, False)
            self.save.sync()

            # count only URLs that were successfully accepted into the frontier
            if pattern is not None:
                self.query_pattern_counts[pattern] += 1

            self.to_be_downloaded.append(url)
            self.outstanding += 1
            self.condition.notify_all()

    def mark_url_complete(self, url):
        """persist completion and wake workers that MAY be waiting for work."""
        urlhash = get_urlhash(url)

        with self.condition:
            if urlhash in self.save:
                self.save[urlhash] = (url, True)
                self.save.sync()
            else:
                self.logger.error("Completed unknown URL: %s", url)

            self.outstanding -= 1
            self.condition.notify_all()

    def wait_for_domain(self, url):
        """reserve a polite start time for this domain; sleep until that slot."""
        hostname = (urlparse(url).hostname or "").lower()

        # Group subdomains under their assignment roots; conservative politeness.
        domain = next(
            (
                d for d in (
                    "ics.uci.edu",
                    "cs.uci.edu",
                    "informatics.uci.edu",
                    "stat.uci.edu"
                )
                if hostname == d or hostname.endswith("." + d)
            ),
            hostname
        )

        # make the slot calculation atomic: two threads cannot reserve
        # the same or overlapping start times for a domain.
        with self.politeness_lock:
            now = time.monotonic()
            slot = max(now, self.next_request_time.get(domain, 0.0))
            self.next_request_time[domain] = (
                slot + max(0.5, self.config.time_delay)
            )

        # sleep outside the lock so other domains can reserve slots
        remaining = slot - time.monotonic()

        if remaining > 0:
            time.sleep(remaining)
