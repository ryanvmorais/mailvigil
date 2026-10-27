"""MailVigil — reads DMARC aggregate reports and says if it is safe to move to p=reject."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mailvigil")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
