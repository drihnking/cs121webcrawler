
import shelve
import time
from collections import deque
from threading import Condition, Lock
from urllib.parse import urlparse

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

        # Separate lock reserves request slots without blocking frontier queue access.
        self.politeness_lock = Lock()
        self.next_request_time = {}

        # Shelve must only be read/written while holding self.condition.
        if restart:
            # shelve may use multiple files; clear it via shelve rather than os.remove.
            with shelve.open(config.save_file) as old:
                old.clear()

        self.save = shelve.open(config.save_file)

        if not restart:
            for url, complete in self.save.values():
                if not complete and is_valid(url):
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

    def add_url(self, url):
        """validate and enqueue a URL only if it has NEVER been recorded"""
        if not is_valid(url):
            return

        url = normalize(url)
        urlhash = get_urlhash(url)

        with self.condition:
            if urlhash in self.save:
                return

            # persist(save to permanent storage) the discovered URL before workers can pick it up
            self.save[urlhash] = (url, False)
            self.save.sync()

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
