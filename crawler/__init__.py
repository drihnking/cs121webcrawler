from utils import get_logger
from crawler.frontier import Frontier
from crawler.worker import Worker

from urllib.parse import urldefrag
from hashlib import sha256

class Crawler(object):
    def __init__(self, config, restart, frontier_factory=Frontier, worker_factory=Worker):
        self.config = config
        self.logger = get_logger("CRAWLER")
        self.frontier = frontier_factory(config, restart)
        self.workers = list()
        self.worker_factory = worker_factory

    def start_async(self):
        print("DEBUG: Creating workers", flush=True)

        self.workers = [
            self.worker_factory(worker_id, self.config, self.frontier)
            for worker_id in range(self.config.threads_count)
        ]

        print("DEBUG: Workers created", flush=True)

        for worker in self.workers:
            worker.start()

        print("DEBUG: Workers started", flush=True)

    def start(self):
        self.start_async()
        self.join()

    def join(self):
        for worker in self.workers:
            worker.join()

    def normalize(url):
        return urldefrag(url)[0]

    def get_urlhash(url):
        return sha256(normalize(url).encode("utf-8")).hexdigest()
