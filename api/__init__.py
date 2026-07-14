"""api package — exports the goodID fallback client."""

from .goodid_client import GoodIDResult, query_goodid

__all__ = ["GoodIDResult", "query_goodid"]
