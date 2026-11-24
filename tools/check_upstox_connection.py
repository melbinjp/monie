"""Check Upstox authentication and quotes without submitting orders."""

from config import Config


def main():
    if not Config.UPSTOX_ACCESS_TOKEN:
        print("Set UPSTOX_ACCESS_TOKEN before running this check.")
        return 1

    from core.brokers.upstox import UpstoxBroker

    broker = UpstoxBroker(Config)
    if not broker.authenticate():
        print("Upstox authentication failed.")
        return 1

    for name, instrument in (("NIFTY 50", "NSE|Nifty 50"), ("INDIA VIX", "NSE|INDIA VIX")):
        print(f"{name}: {broker.get_quote(instrument)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
