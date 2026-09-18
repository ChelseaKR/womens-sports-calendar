# Test cases for .semgrep/wsc-credential-in-output.yml. Never executed.
import logging
import sys

log = logging.getLogger(__name__)


class Example:
    def bad(self, api_key: str) -> None:
        # ruleid: wsc-credential-in-output
        print(f"using {api_key}")
        # ruleid: wsc-credential-in-output
        log.error("key was %s", api_key)
        # ruleid: wsc-credential-in-output
        sys.stderr.write(f"token={self._token}")
        # ruleid: wsc-credential-in-output
        raise RuntimeError(f"failed with {self._api_key}")

    def good(self, keyword: str) -> None:
        # ok: wsc-credential-in-output
        print("TICKETMASTER_API_KEY is not set")
        # ok: wsc-credential-in-output
        log.error("failed for keyword=%s", keyword)
        # ok: wsc-credential-in-output
        raise RuntimeError(self._redact(f"failed for keyword={keyword!r}"))
