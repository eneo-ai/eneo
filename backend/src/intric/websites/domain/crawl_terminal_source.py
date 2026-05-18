from enum import Enum


class CrawlTerminalSource(str, Enum):
    ADMIN = "admin"
    CRAWLER = "crawler"
    QUEUE = "queue"
    WATCHDOG = "watchdog"
