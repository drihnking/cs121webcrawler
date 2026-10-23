import os
import shelve

import time
from collections import deque

from threading import Thread, RLock
from queue import Queue, Empty

from utils import get_logger, get_urlhash, normalize
from scraper import is_valid

class Frontier(object):
    def __init__(self, config, restart):
        self.logger = get_logger("FRONTIER")
        self.config = config
	# condition lock is needed to protect the queue, oustanding count and shelve DB
	# additionally it lets the idle threads sleep until another worker discovers the URLs
        self.condition = Condition()
	self.to_be_downloaded = deque()

	# number of queues || currently in-progress URLs; 0 means it's completed
	self.outstanding = 0

	# separating the lock reserves request slots without having to block the frontier queue access
	self.politeness_lock = Lock()
	self.next_request_time = {}

	# shelve can only be read/written into while holding self.condition
	if restart:
		# can use multiple files, which will clear via shelve rather than os.remove
		with shelve.open(config.save_file) as old:
			old.clear()
	self.save = shelve.open(config.save_file)
	if not restart:
		for url, complete in self.save.values():
			if not complete and is_valid(url):
				self.to_be_downloaded.append(url)
				self.outstanding += 1
	if self.oustanding ==0 and not self.save:
		for url in config.seed_urls:
			self.add_url(url.strip())
	self.logger.info("Loaded %d oustanding URLs", self.outstanding)

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
		if urlhash not in self.save:
			return
		# persist(save to permanent storage) the discovered URL before workers can pick it up
		self.save[urlhash] = (url, False)
                self.save.sync()
                self.to_be_downloaded.append(url)
		self.outstanding += 1
		self.condition.notify_all()

    def mark_url_complete(self, url):
	"""persist URL's finished status, then wake workers that MAY be waiting for work"""
        urlhash = get_urlhash(url)
	with self.condition:
        	if urlhash not in self.save:
			self.save[urlhash] = (url, True)
			self.save.sync()
		else:
			self.logger.error("Completed unknown URL: %s", url)
		self.outstanding -= 1
		self.condition.notify_all()

    def wait_for_domain(self, url):
	"""reserve a POLITE start time for this domain, then sleep until that slot"""
	hostname = (urlparse(url).hostname or "").lower()

	# group all subdomains under their assigned roots, enforcing politeness conservatively
	domain = next((d for d in ("ics.uci.edu", "cs.uci."informatics.uci.edu", "stat.uci.edu")
		       if hostname == d or hostname.endswith("." + d)), hostname)

	# amke the slot calculation atomic since 2 threads cant reserve the same OR overlapping start times for 1 domain
	with self.politeness_lock:
		now = time.monotonic()
		slot = max(now, self.next_request_time.get(domain, 0.0))
		self.next_request_time[domain] = slot + max(0.5, self.config.time_delay)
	# will sleep outside the lock so other domains can reserve the slots
	remaining = slot - time.monotonic()
	if remaining > 0:
		time.sleep(remaining)
