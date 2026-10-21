"""Download September 2025 hourly tick files from the Dukascopy public datafeed into data/<SYMBOL>/<DD>/<HH>.bi5.
Dukascopy months are zero-based (08 = September). The feed throttles heavy use: requests are serial with a pause,
and on HTTP 503 the script waits 10 minutes and retries. Files already present and valid are skipped."""
import lzma
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
URL = "https://datafeed.dukascopy.com/datafeed/{s}/2025/08/{d:02d}/{h:02d}h_ticks.bi5"


def valid(f):
    if not f.exists():
        return False
    b = f.read_bytes()
    if not b:
        return True
    try:
        lzma.decompress(b)
        return True
    except lzma.LZMAError:
        return False


def main():
    for s in ("EURUSD", "USDCHF", "XAUUSD"):
        for d in range(1, 31):
            for h in range(24):
                f = DATA / s / f"{d:02d}" / f"{h:02d}.bi5"
                if valid(f):
                    continue
                f.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(URL.format(s=s, d=d, h=h), headers={"User-Agent": "Mozilla/5.0"})
                while True:
                    try:
                        f.write_bytes(urllib.request.urlopen(req, timeout=120).read())
                        break
                    except urllib.error.HTTPError as e:
                        if e.code == 404:
                            f.write_bytes(b"")
                            break
                        time.sleep(600)
                time.sleep(2)


if __name__ == "__main__":
    main()
