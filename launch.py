from configparser import ConfigParser
from argparse import ArgumentParser

from utils.server_registration import get_cache_server
from utils.config import Config
from crawler import Crawler
from scraper import print_crawl_analytics, load_analytics, save_analytics

def main(config_file, restart):
    cparser = ConfigParser()
    cparser.read(config_file)
    config = Config(cparser)
    # DEBUG
    print("DEBUG: Starting server registration", flush=True)

    config.cache_server = get_cache_server(config, restart)

    print("DEBUG: Server registration completed", flush=True)

    # restore the previous crawl statistics before starting the workers
    load_analytics(restart)
    crawler = Crawler(config, restart)

    print("DEBUG: Frontier initialized", flush=True)
    try:
        print("DEBUG: Starting crawler workers", flush=True)
        crawler.start()
        print("DEBUG: Crawler workers finished", flush=True)
    finally:
        # Prints deliverable data when crawling is done or stopped by Ctrl + C
        save_analytics()
        print_crawl_analytics()

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--restart", action="store_true", default=False)
    parser.add_argument("--config_file", type=str, default="config.ini")
    args = parser.parse_args()
    main(args.config_file, args.restart)
