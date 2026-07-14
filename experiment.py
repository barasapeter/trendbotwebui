import asyncio
import logging
import os
from dotenv import load_dotenv
from auth import get_ws_url
from client import DerivClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load configuration from environment
load_dotenv()
API_TOKEN = os.getenv("DERIV_API_TOKEN") or os.getenv("TOKEN")
APP_ID = os.getenv("DERIV_APP_ID") or os.getenv("APP_ID") or "1089"
SYMBOL = "R_100"

async def handle_ticks(tick_client, trade_client):
    """
    Subscribes to market ticks via the tick client and executes trades 
    using the separate trade client when conditions are met.
    """
    logger.info(f"Subscribing to tick stream for {SYMBOL}...")
    
    # Subscribe to market ticks
    subscription_payload = {"ticks": SYMBOL, "subscribe": 1}
    await tick_client.send(subscription_payload)
    
    # Continuously read incoming messages from the streaming connection
    async for message_str in tick_client.ws:
        import json
        message = json.loads(message_str)
        
        if message.get("msg_type") == "tick":
            tick_data = message.get("tick", {})
            price = tick_data.get("quote")
            epoch = tick_data.get("epoch")
            logger.info(f"Tick received | Time: {epoch} | Price: {price}")
            
            # --- Place your trading strategy condition here ---
            if price and float(price) > 0:  
                logger.info("Trading criteria met. Placing trade...")
                
                buy_payload = {
                    "buy": 1,
                    "price": 10,
                    "parameters": {
                        "amount": 10,
                        "basis": "stake",
                        "contract_type": "CALL",
                        "currency": "USD",
                        "duration": 5,
                        "duration_unit": "t",
                        "symbol": SYMBOL
                    }
                }
                
                # Send trade payload through the pre-authenticated trade client
                trade_response = await trade_client.send(buy_payload)
                logger.info(f"Trade Execution Response: {trade_response}")
                break  # Stop loop after executing the trade for demonstration purposes

async def main():
    if not API_TOKEN:
        logger.error("Execution halted: Missing API Token in environment variables.")
        return

    logger.info("Retrieving pre-authenticated WebSocket URLs...")
    # We generate two distinct URLs. If get_ws_url uses single-use OTPs, 
    # generating two separate endpoints ensures neither connection steps on the other.
    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    ws_url_trades = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)

    # Initialize our functional clients
    tick_client = DerivClient(ws_url_ticks)
    trade_client = DerivClient(ws_url_trades)

    try:
        logger.info("Opening Tick Client connection...")
        await tick_client.connect()
        
        logger.info("Opening Trade Client connection...")
        await trade_client.connect()

        # Kickoff the trading handler
        await handle_ticks(tick_client, trade_client)

    except Exception as e:
        logger.error(f"An operational error occurred: {e}", exc_info=True)
    finally:
        # Clean up both client sockets gracefully
        if tick_client.ws:
            await tick_client.ws.close()
        if trade_client.ws:
            await trade_client.ws.close()
        logger.info("Connections closed. Bot execution ended.")

if __name__ == "__main__":
    asyncio.run(main())