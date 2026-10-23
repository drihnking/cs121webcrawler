
from threading import Thread, Lock
from inspect import getsource

from utils.download import download
from utils import get_logger
import scraper


_scraper_lock = Lock()


class Worker(Thread):
    """repeatedly fetch queued URls  and hand extracted links to the frontier"""

    def __init__(self, worker_id, config, frontier):
        self.logger = get_logger(f"Worker-{worker_id}", "Worker")
        self.config = config
        self.frontier = frontier

        # scraper can't fetch directly via requests or urllib
        assert {getsource(scraper).find(req) for req in
                {"from requests import", "import requests"}} == {-1}
        assert {getsource(scraper).find(req) for req in
                {"from urllib.request import", "import urllib.request"}} == {-1}

        super().__init__(daemon=True)

    def run(self):
        """main worker loop where it always mark a URL finished even after logged errors"""
        while True:
            # threads would pull unique work from the shared frontier, safely
            url = self.frontier.get_tbd_url()

            if url is None:
                self.logger.info("Frontier is empty. Worker is stopping.")
                return

            try:
                # enforce spacing between requests before using the course downloader
                self.frontier.wait_for_domain(url)
                resp = download(url, self.config, self.logger)
                self.logger.info("Downloaded %s, status <%s>", url, resp.status)

                # since shared scraper stats & fingerprint dupes are global
                # it'll serialize the entire scraper call to avoid mutations happening simultaneously
                with _scraper_lock:
                    found = scraper.scraper(url, resp)

                # add_url would delete dupes of discovered links while holding its lock
                for link in found:
                    self.frontier.add_url(link)

            except Exception:
                self.logger.exception("Failed to process %s", url)

            finally:
                # oustanding must reach 0 for a clean shutdown
                self.frontier.mark_url_complete(url)
