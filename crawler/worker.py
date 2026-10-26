
from threading import Thread, Lock
from inspect import getsource

from utils.download import download
from utils import get_logger
import scraper

import resource


_scraper_lock = Lock()

def log_memory(stage):
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"MEMORY [{stage}]: {usage:.1f} MB", flush=True)

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
        """process URLs while monitoring memory usage"""
        while True:
            url = self.frontier.get_tbd_url()

            if url is None:
                self.logger.info("Frontier is empty. Worker is stopping.")
                return

            try:
                self.logger.info("DEBUG: About to download %s", url)
                log_memory("before download")

                self.frontier.wait_for_domain(url)

                self.logger.info("DEBUG: Calling download() for %s", url)
                resp = download(url, self.config, self.logger)

                log_memory("after download")

                self.logger.info("Downloaded %s, status <%s>", url, resp.status)

                with _scraper_lock:
                    log_memory("before scraper")
                    found = scraper.scraper(url, resp)
                    log_memory("after scraper")

                for link in found:
                    self.frontier.add_url(link)

            except Exception:
                self.logger.exception("Failed to process %s", url)

            finally:
                self.frontier.mark_url_complete(url)
