#!/usr/bin/env python3
"""
history_and_live_ticks.py - Fetch N batches of historical ticks, print them
as batches (entry + numbered ticks, chained), then seamlessly continue with
live streamed batches, picking up the batch numbering and chaining where
history left off.

Usage:
    python history_and_live_ticks.py [symbol] [n_history_batches] [batch_size]

Examples:
    python history_and_live_ticks.py                # R_100, 3 history batches, size 5
    python history_and_live_ticks.py R_50 5          # R_50, 5 history batches, size 5
    python history_and_live_ticks.py R_50 5 10       # R_50, 5 history batches, size 10
"""

import asyncio
import sys

from live_ticks import TickPrinter, SYMBOL, BATCH_SIZE


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else SYMBOL
    n_history_batches = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else BATCH_SIZE

    printer = TickPrinter(symbol, batch_size)

    try:
        print("🔗 Connecting to Deriv...")
        await printer.client.connect()

        # Step 1: fetch + replay historical batches
        await printer.fetch_and_replay_history(n_history_batches)

        # Step 2: subscribe and continue live, chaining off the last
        # historical exit (printer.batch_entry / batch_number already
        # carry over automatically since it's the same object/state).
        await printer.subscribe_ticks()
        await printer.print_ticks()

    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await printer.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
