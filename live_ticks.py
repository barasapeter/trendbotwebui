#!/usr/bin/env python3
"""
live_ticks.py - Script to subscribe and print live ticks from Deriv in batches.

Each batch consists of:
  - 1 "assumed entry" tick (the reference point, like the dashed line marker)
  - 5 numbered ticks (1-5) measured relative to that entry

After tick #5, a batch summary is printed (entry -> exit) and a new
batch starts with the next incoming tick as the new assumed entry.
"""

import asyncio
import os
import sys
from datetime import datetime
from client_experiment2 import DerivClient
from auth import get_ws_url
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")

WS_URL = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
SYMBOL = "R_100"  # Default symbol - change as needed

BATCH_SIZE = 5  # number of numbered ticks per batch (excludes the assumed entry)


class TickPrinter:
    def __init__(self, symbol=SYMBOL, batch_size=BATCH_SIZE):
        self.client = DerivClient(WS_URL)
        self.symbol = symbol
        self.tick_count = 0
        self.running = True
        self.batch_size = batch_size

        # Batch state
        self.batch_number = 0
        self.batch_entry = None  # (price, timestamp) - the assumed entry tick
        self.batch_ticks = []  # list of (price, timestamp) for ticks 1..batch_size

    async def subscribe_ticks(self):
        """Subscribe to ticks for the specified symbol"""
        try:
            subscribe_payload = {"ticks": self.symbol, "subscribe": 1}
            await self.client.subscribe(subscribe_payload)
            print(f"📊 Subscribed to {self.symbol} ticks")
            print(f"   Batch mode: 1 assumed entry + {self.batch_size} ticks per batch")
            print("=" * 60)

        except Exception as e:
            print(f"❌ Subscription error: {e}")
            raise

    @staticmethod
    def _fmt_time(epoch):
        if epoch:
            return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")
        return datetime.now().strftime("%H:%M:%S")

    def _print_entry(self, price, epoch, chained=False):
        ts = self._fmt_time(epoch)
        label = (
            "Entry (carried over from previous exit)" if chained else "Assumed entry"
        )
        print()
        print("=" * 60)
        print(f"Batch #{self.batch_number + 1}  |  {label}")
        print(f"  ⏱ {ts}    entry price: {price:.5f}")
        print("-" * 60)

    def _print_batch_tick(self, idx, price, epoch):
        entry_price = self.batch_entry[0]
        diff = price - entry_price
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "─")
        ts = self._fmt_time(epoch)
        tag = "  <-- EXIT" if idx == self.batch_size else ""
        print(f"  [{idx}] ⏱ {ts}   {price:<12.5f} {arrow} {diff:+.5f}{tag}")

    def _print_batch_summary(self):
        entry_price = self.batch_entry[0]
        exit_price = self.batch_ticks[-1][0]
        total_diff = exit_price - entry_price
        if total_diff > 0:
            result = "UP ▲"
        elif total_diff < 0:
            result = "DOWN ▼"
        else:
            result = "FLAT ─"
        print("-" * 60)
        print(
            f"Batch #{self.batch_number + 1} result: "
            f"{entry_price:.5f} -> {exit_price:.5f}  "
            f"({total_diff:+.5f})  [{result}]"
        )
        print("=" * 60)

    def process_tick(self, price, epoch):
        """Feed a single tick into the current batch."""
        if self.batch_entry is None:
            # First tick of a new batch = assumed entry
            self.batch_entry = (price, epoch)
            self._print_entry(price, epoch)
            return

        self.batch_ticks.append((price, epoch))
        idx = len(self.batch_ticks)
        self._print_batch_tick(idx, price, epoch)

        if idx == self.batch_size:
            self._print_batch_summary()
            self.batch_number += 1
            # Chain: this batch's exit becomes the next batch's entry
            # (no fresh tick consumed just to seed the new entry)
            self.batch_entry = self.batch_ticks[-1]
            self.batch_ticks = []
            self._print_entry(self.batch_entry[0], self.batch_entry[1], chained=True)

    async def stream_history_then_live(self, n_batches):
        """
        Fetch n_batches worth of history AND subscribe to live ticks in a
        single combined request (ticks_history with subscribe=1). This
        avoids the gap you get from doing two separate calls (history,
        then a separate subscribe) - the live stream continues from the
        exact same subscription, right where history left off.
        """
        total_needed = n_batches * self.batch_size + 1
        print(
            f"📜 Requesting {total_needed} historical ticks "
            f"({n_batches} batch{'es' if n_batches != 1 else ''}) "
            f"+ live subscription in one call..."
        )

        payload = {
            "ticks_history": self.symbol,
            "adjust_start_time": 1,
            "count": total_needed,
            "end": "latest",
            "style": "ticks",
            "subscribe": 1,
        }

        # subscribe() just sends the request; responses are read via
        # recv_streaming() below (same as the live tick loop uses).
        await self.client.subscribe(payload)

        # First message on this subscription is the historical batch.
        data = await self.client.recv_streaming()

        if "error" in data:
            msg = data["error"].get("message", "Unknown error")
            print(f"❌ History fetch error: {msg}")
            return

        history = data.get("history", {})
        prices = history.get("prices", [])
        times = history.get("times", [])

        if not prices:
            print("⚠️  No historical ticks returned.")
            return

        print(f"✅ Got {len(prices)} historical ticks — replaying as batches:")

        for price, epoch in zip(prices, times):
            self.tick_count += 1
            self.process_tick(price, epoch)

        print(
            "\n📡 History replayed — live stream continuing on the SAME "
            "subscription (no reconnect, no gap)...\n"
        )
        sys.stdout.flush()  # guarantee everything above is on screen now,
        # before we start waiting on live ticks

    async def fetch_and_replay_history(self, n_batches):
        """
        Fetch enough historical ticks to fill n_batches worth of batches,
        then replay them through the same process_tick() logic used for
        live ticks (so chaining/batch numbering is identical).

        Total ticks needed = n_batches * batch_size + 1
        (+1 only for the very first entry; every batch after that chains
        off the previous exit, same as in live mode).
        """
        total_needed = n_batches * self.batch_size + 1
        print(
            f"📜 Fetching {total_needed} historical ticks "
            f"({n_batches} batch{'es' if n_batches != 1 else ''})..."
        )

        payload = {
            "ticks_history": self.symbol,
            "adjust_start_time": 1,
            "count": total_needed,
            "end": "latest",
            "style": "ticks",
        }

        response = await self.client.send(payload)

        if "error" in response:
            msg = response["error"].get("message", "Unknown error")
            print(f"❌ History fetch error: {msg}")
            return

        history = response.get("history", {})
        prices = history.get("prices", [])
        times = history.get("times", [])

        if not prices:
            print("⚠️  No historical ticks returned.")
            return

        print(f"✅ Got {len(prices)} historical ticks — replaying as batches:")

        for price, epoch in zip(prices, times):
            self.tick_count += 1
            self.process_tick(price, epoch)

        print("\n📡 History replay complete — switching to live stream...\n")

    async def print_ticks(self):
        """Continuously receive ticks and feed them into the batch printer"""
        while self.running:
            try:
                data = await self.client.recv_streaming()

                if "tick" in data:
                    tick = data["tick"]
                    price = tick.get("quote", 0)
                    epoch = tick.get("epoch", 0)

                    if price != 0:
                        self.tick_count += 1
                        self.process_tick(price, epoch)

                elif "error" in data:
                    error = data["error"]
                    print(f"❌ Error: {error.get('message', 'Unknown error')}")
                    if error.get("code") == "RateLimit":
                        print("⏳ Rate limit hit. Waiting...")
                        await asyncio.sleep(1)

            except Exception as e:
                if "recv timeout" in str(e):
                    continue
                else:
                    print(f"❌ Receive error: {e}")
                    await self.handle_connection_error()

    async def handle_connection_error(self):
        """Handle connection errors and attempt to reconnect"""
        print("🔄 Connection lost. Attempting to reconnect...")
        try:
            if self.client.is_connected:
                await self.client.close()

            await self.client.connect()
            await self.subscribe_ticks()
            print("✅ Reconnected successfully")

        except Exception as e:
            print(f"❌ Reconnection failed: {e}")
            await asyncio.sleep(5)

    async def run(self):
        """Main run loop"""
        try:
            print("🔗 Connecting to Deriv...")
            await self.client.connect()
            await self.subscribe_ticks()
            await self.print_ticks()

        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        self.running = False
        if self.client.is_connected:
            await self.client.close()
        print(f"📊 Total ticks received: {self.tick_count}")
        print(f"📦 Total batches completed: {self.batch_number}")


async def main():
    """Main entry point"""
    symbol = SYMBOL
    batch_size = BATCH_SIZE

    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    if len(sys.argv) > 2:
        batch_size = int(sys.argv[2])

    printer = TickPrinter(symbol, batch_size)
    await printer.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
