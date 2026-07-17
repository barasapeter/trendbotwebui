#!/usr/bin/env python3
"""
history_and_live_ticks.py - Fetch N batches of historical ticks, print them
as batches (entry + numbered ticks, chained), then seamlessly continue with
live streamed batches, picking up the batch numbering and chaining where
history left off.

Usage:
    python history_and_live_ticks.py [symbol] [n_history_batches] [batch_size] [output_file]

    output_file:
        "auto" (default) -> writes to ticks_log_<symbol>_<timestamp>.txt
        "none"           -> disables file logging, console only
        any other value  -> used as the exact filename to append to

Examples:
    python history_and_live_ticks.py                       # R_100, 3 batches, size 5, auto-logged
    python history_and_live_ticks.py R_50 5                # R_50, 5 batches, size 5, auto-logged
    python history_and_live_ticks.py R_50 5 10              # R_50, 5 batches, size 10, auto-logged
    python history_and_live_ticks.py R_50 5 5 mylog.txt      # custom log filename
    python history_and_live_ticks.py R_50 5 5 none           # console only, no file
"""

import asyncio
import sys
from datetime import datetime

from live_ticks import TickPrinter, SYMBOL, BATCH_SIZE, Tee


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else SYMBOL
    n_history_batches = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else BATCH_SIZE
    output_arg = sys.argv[4] if len(sys.argv) > 4 else "auto"

    output_file = None
    if output_arg.lower() != "none":
        if output_arg.lower() == "auto":
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"ticks_log_{symbol}_{ts}.txt"
        else:
            output_file = output_arg

    original_stdout = sys.stdout
    file_handle = None
    if output_file:
        file_handle = open(output_file, "a", encoding="utf-8")
        sys.stdout = Tee(original_stdout, file_handle)
        print(f"📝 Logging output to {output_file}")

    printer = TickPrinter(symbol, batch_size)

    try:
        print("🔗 Connecting to Deriv...")
        await printer.client.connect()

        # Fetch history and subscribe to live ticks in ONE combined call
        # (no gap between the last historical tick and the first live one).
        await printer.stream_history_then_live(n_history_batches)

        # Continue reading from the same subscription - this loop just
        # keeps consuming "tick" messages, no new subscribe needed.
        await printer.print_ticks()

    except KeyboardInterrupt:
        print("\n🛑 Stopping...")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await printer.cleanup()
        sys.stdout = original_stdout
        if file_handle:
            file_handle.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
