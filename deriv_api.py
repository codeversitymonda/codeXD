import json
import websockets
import asyncio
from typing import Callable, Optional, Dict, Any
import uuid
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DerivAPI:
    def __init__(self):
        self.connection = None
        self.connected = False
        self._message_handlers = []
        self._listening_task = None
        self._pending_requests = {}
        self._connection_lock = asyncio.Lock()
        self.account_info = None
        self.current_balance = 0.0
        self.initial_balance = 0.0
        
        # FIXED: Proper P&L tracking based on actual trade outcomes
        self.session_profit_loss = 0.0  # Sum of all completed trade profits/losses
        self.completed_trades = []  # Track completed trades with their outcomes
        self.pending_stakes = 0.0  # Track stakes currently in pending trades

        # Use Deriv's official WebSocket URL
        self.DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

    def _generate_req_id(self) -> int:
        """Generate a unique request ID"""
        return int(time.time() * 1000000) % 1000000000

    async def connect(self, token: str = None):
        """Establish connection to Deriv API"""
        async with self._connection_lock:
            try:
                logger.info(f"Connecting to Deriv API at: {self.DERIV_WS_URL}")

                # Clean shutdown of existing connection
                await self._cleanup_connection()

                # Create new connection
                self.connection = await websockets.connect(
                    self.DERIV_WS_URL,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                )
                self.connected = True

                # Start the message listener
                self._listening_task = asyncio.create_task(self._listen_loop())

                # Small delay to ensure listener is ready
                await asyncio.sleep(0.1)

                # Authorize if token is provided
                if token:
                    logger.info("Attempting authorization...")
                    auth_response = await self.send_request({
                        "authorize": token
                    }, timeout=15.0)

                    if "error" in auth_response:
                        error_msg = auth_response['error'].get('message', 'Unknown error')
                        logger.error(f"Authorization failed: {error_msg}")
                        await self._cleanup_connection()
                        return {"error": {"message": error_msg}}

                    # Store account information
                    if "authorize" in auth_response:
                        self.account_info = auth_response["authorize"]
                        logger.info(f"Authorization successful for account: {self.account_info.get('loginid')}")

                        # Get initial balance and reset P&L tracking
                        balance_response = await self.get_balance()
                        if "balance" in balance_response:
                            self.current_balance = float(balance_response["balance"]["balance"])
                            self.initial_balance = self.current_balance
                            # FIXED: Reset P&L tracking properly
                            self.session_profit_loss = 0.0
                            self.pending_stakes = 0.0
                            self.completed_trades = []
                            logger.info(f"Current balance: ${self.current_balance}")

                    return auth_response

                return {"success": True}

            except Exception as e:
                logger.error(f"Connection error: {e}")
                await self._cleanup_connection()
                return {"error": {"message": str(e)}}

    async def _cleanup_connection(self):
        """Clean up existing connection and tasks"""
        self.connected = False

        # Cancel listening task
        if self._listening_task and not self._listening_task.done():
            self._listening_task.cancel()
            try:
                await asyncio.wait_for(self._listening_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Cancel all pending requests
        for future in list(self._pending_requests.values()):
            if not future.done():
                future.cancel()
        self._pending_requests.clear()

        # Close WebSocket connection
        if self.connection and not self.connection.closed:
            try:
                await asyncio.wait_for(self.connection.close(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            self.connection = None

    async def send_request(self, request_data: dict, timeout: float = 10.0):
        """Send request to Deriv API and get response"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")

        try:
            # Generate unique request ID
            req_id = self._generate_req_id()
            request_data["req_id"] = req_id

            # Create a future to wait for the response
            response_future = asyncio.get_event_loop().create_future()
            self._pending_requests[str(req_id)] = response_future

            # Send request
            message = json.dumps(request_data)
            logger.info(f"Sending request: {message}")
            await self.connection.send(message)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=timeout)
                logger.info(f"Received response: {json.dumps(response)}")
                return response
            except asyncio.TimeoutError:
                # Clean up on timeout
                self._pending_requests.pop(str(req_id), None)
                raise ConnectionError(f"Request timed out after {timeout} seconds")

        except websockets.exceptions.ConnectionClosed:
            self.connected = False
            raise ConnectionError("WebSocket connection closed")
        except Exception as e:
            # Clean up on error
            if 'req_id' in locals():
                self._pending_requests.pop(str(req_id), None)
            logger.error(f"Send request error: {e}")
            raise

    async def _listen_loop(self):
        """Message listener that dispatches to appropriate handlers"""
        try:
            while self.connected and self.connection and not self.connection.closed:
                try:
                    message = await asyncio.wait_for(
                        self.connection.recv(),
                        timeout=30.0
                    )
                    data = json.loads(message)
                    logger.debug(f"Received message: {message}")

                    # Handle request-response pairs
                    req_id = data.get("req_id")
                    if req_id is not None:
                        req_id_str = str(req_id)
                        if req_id_str in self._pending_requests:
                            future = self._pending_requests.pop(req_id_str)
                            if not future.done():
                                future.set_result(data)
                            continue

                    # Handle subscription messages
                    asyncio.create_task(self._route_message(data))

                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed in listener")
                    self.connected = False
                    break
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error in message listener: {e}")
                    continue

        except asyncio.CancelledError:
            logger.info("Message listener cancelled")
            self.connected = False
        except Exception as e:
            logger.error(f"Fatal error in listening loop: {e}")
            self.connected = False
        finally:
            # Cancel all pending requests
            for future in list(self._pending_requests.values()):
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()

    async def _route_message(self, data: Dict[str, Any]):
        """Route incoming subscription messages to appropriate handlers"""
        try:
            if "tick" in data:
                tick_symbol = data["tick"].get("symbol")
                for msg_type, symbol, callback in list(self._message_handlers):
                    if msg_type == 'ticks' and tick_symbol == symbol:
                        # safe-call each callback
                        try:
                            await callback(data["tick"])
                        except Exception as cb_err:
                            logger.error(f"Tick callback error for {symbol}: {cb_err}")

            elif "proposal_open_contract" in data:
                # route proposal_open_contract messages to handlers that care (if any)
                contract = data["proposal_open_contract"]
                contract_id = contract.get("contract_id")
                for msg_type, symbol, callback in list(self._message_handlers):
                    if msg_type == 'contract' and (symbol is None or symbol == contract_id):
                        try:
                            await callback(contract)
                        except Exception as cb_err:
                            logger.error(f"Contract callback error for {contract_id}: {cb_err}")

            elif "error" in data:
                logger.error(f"API Error: {data['error'].get('message', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Error routing message: {e}")

    async def subscribe_ticks(self, symbol: str, callback: Callable):
        """Subscribe to tick stream for a symbol"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")

        # Store the callback for this symbol
        self._message_handlers.append(('ticks', symbol, callback))

        # Send subscription request
        subscription_request = {
            "ticks": symbol,
            "subscribe": 1
        }

        try:
            message = json.dumps(subscription_request)
            logger.info(f"Sending subscription: {message}")
            await self.connection.send(message)
            return {"status": "subscribed"}
        except Exception as e:
            logger.error(f"Failed to subscribe to ticks: {e}")
            # Remove the handler if subscription failed
            self._message_handlers = [
                (msg_type, sym, cb) for msg_type, sym, cb in self._message_handlers
                if not (msg_type == 'ticks' and sym == symbol and cb == callback)
            ]
            raise

    async def get_proposal(self, contract_params: dict):
        """Get a proposal for a contract"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        # Extract and validate parameters
        symbol = contract_params.get("symbol", "R_100")
        contract_type = contract_params.get("contract_type", "DIGITDIFF")
        amount = float(contract_params.get("amount", 1.0))
        barrier = str(contract_params.get("barrier", "0"))
        duration = int(contract_params.get("duration", 5))
        duration_unit = contract_params.get("duration_unit", "t")
        currency = contract_params.get("currency", "USD")
        basis = contract_params.get("basis", "stake")

        proposal_request = {
            "proposal": 1,
            "amount": amount,
            "basis": basis,
            "contract_type": contract_type,
            "symbol": symbol,
            "barrier": barrier,
            "duration": duration,
            "duration_unit": duration_unit,
            "currency": currency
        }

        logger.info(f"Getting proposal: {proposal_request}")
        response = await self.send_request(proposal_request, timeout=15.0)

        if "error" in response:
            logger.error(f"Proposal error: {response['error'].get('message', response['error'])}")
        elif "proposal" in response:
            # some responses return 'proposal' as dict or nested
            try:
                pid = response['proposal']['id']
                disp = response['proposal'].get('display_value')
                logger.info(f"Proposal received: ID={pid}, Price={disp}")
            except Exception:
                pass

        return response

    async def buy_proposal(self, proposal_id: str, price: float):
        """Buy a specific proposal - track stake as pending"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        buy_request = {
            "buy": proposal_id,
            "price": float(price)
        }

        logger.info(f"Buying proposal: {buy_request}")
        response = await self.send_request(buy_request, timeout=15.0)

        if "error" in response:
            logger.error(f"Buy error: {response['error'].get('message', response['error'])}")
        elif "buy" in response:
            contract_id = response["buy"].get("contract_id")
            logger.info(f"Contract purchased successfully! Contract ID: {contract_id}")
            
            # FIXED: Track pending stake - this money is "in play" but not lost yet
            self.pending_stakes += float(price)
            logger.info(f"Added ${price} to pending stakes. Total pending: ${self.pending_stakes}")
        
        return response

    async def _wait_for_contract_settlement(self, contract_id: str, stake_amount: float, timeout: float = 90.0, poll_interval: float = 3.0):
        """
        Poll get_contract_status until the contract is sold/settled or timeout.
        Returns a dict with result, profit, balance, and raw contract payload.
        FIXED: Properly handles P&L tracking based on actual trade outcomes.
        """
        start = time.time()
        last_exception = None

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                logger.warning(f"Timeout waiting for contract {contract_id} settlement after {timeout} seconds")
                # Return timeout result; keep stake as pending
                return {
                    "result": "TIMEOUT",
                    "profit": 0.0,
                    "balance": self.current_balance,
                    "contract_id": contract_id,
                    "contract": None
                }

            try:
                status_resp = await self.get_contract_status(contract_id)
            except Exception as e:
                last_exception = e
                logger.debug(f"Error fetching contract status for {contract_id}: {e}")
                await asyncio.sleep(poll_interval)
                continue

            # Check status response
            if status_resp and "proposal_open_contract" in status_resp:
                contract = status_resp["proposal_open_contract"]
                # Determine if contract is settled/sold
                is_sold = bool(contract.get("is_sold")) or bool(contract.get("is_expired"))
                status_field = str(contract.get("status", "")).lower()
                if is_sold or status_field in ("sold", "settled"):
                    profit = float(contract.get("profit", 0.0))
                    result = "WIN" if profit > 0 else "LOSS"

                    # FIXED: Remove the stake from pending and add the actual profit/loss to session P&L
                    if self.pending_stakes >= stake_amount:
                        self.pending_stakes -= stake_amount
                        logger.info(f"Removed ${stake_amount} from pending stakes. Remaining pending: ${self.pending_stakes}")
                    
                    # Add the actual trade outcome (profit/loss) to session P&L
                    self.session_profit_loss += profit
                    logger.info(f"Trade outcome: ${profit:.2f}. Session P&L now: ${self.session_profit_loss:.2f}")

                    # Update balance from API
                    try:
                        balance_resp = await self.get_balance()
                        if "balance" in balance_resp:
                            self.current_balance = float(balance_resp["balance"]["balance"])
                        else:
                            # If we can't get updated balance, estimate it
                            self.current_balance = self.initial_balance + self.session_profit_loss
                    except Exception as e:
                        logger.warning(f"Could not fetch updated balance after settlement: {e}")
                        # Estimate balance based on session P&L
                        self.current_balance = self.initial_balance + self.session_profit_loss
                    
                    # Record the completed trade
                    self.completed_trades.append({
                        "contract_id": contract_id,
                        "stake": stake_amount,
                        "profit": profit,
                        "result": result,
                        "settlement_time": time.time()
                    })

                    logger.info(f"Contract {contract_id} settled -> {result} profit={profit:.2f}, session_pnl={self.session_profit_loss:.2f}, balance={self.current_balance:.2f}")
                    return {
                        "result": result,
                        "profit": profit,
                        "balance": self.current_balance,
                        "contract_id": contract_id,
                        "contract": contract
                    }
                else:
                    logger.debug(f"Contract {contract_id} still active: status={status_field}, is_sold={contract.get('is_sold')}")
            else:
                # If response contains error, log and continue
                if status_resp and "error" in status_resp:
                    logger.warning(f"get_contract_status returned error for {contract_id}: {status_resp['error']}")
            await asyncio.sleep(poll_interval)

    async def buy_contract(self, contract_params: dict):
        """Two-step process: Get proposal then buy it, then wait for settlement."""
        try:
            stake_amount = float(contract_params.get("amount", 1.0))
            
            # Step 1: Get proposal
            proposal_response = await self.get_proposal(contract_params)

            if "error" in proposal_response:
                return proposal_response

            if "proposal" not in proposal_response:
                return {"error": {"message": "No proposal received"}}

            proposal = proposal_response["proposal"]
            proposal_id = proposal.get("id") or proposal.get("proposal_id") or proposal.get("proposal", {}).get("id")
            if not proposal_id:
                # Some responses may nest differently; attempt to find id
                try:
                    proposal_id = list(proposal.values())[0].get("id")
                except Exception:
                    pass

            if not proposal_id:
                return {"error": {"message": "Could not determine proposal id"}}

            # Step 2: Buy the proposal (this adds stake to pending_stakes)
            buy_response = await self.buy_proposal(proposal_id, stake_amount)

            if "error" in buy_response:
                return buy_response

            # Get contract id from buy response
            contract_id = None
            if "buy" in buy_response and isinstance(buy_response["buy"], dict):
                contract_id = buy_response["buy"].get("contract_id")
            elif isinstance(buy_response, dict) and "contract_id" in buy_response:
                contract_id = buy_response.get("contract_id")

            if not contract_id:
                # If no contract id returned, return buy_response so caller can inspect
                return {"error": {"message": "Buy succeeded but no contract_id returned", "buy_response": buy_response}}

            # Step 3: Wait for settlement and return final outcome
            # Choose a timeout based on duration if provided
            duration = int(contract_params.get("duration", 5)) if contract_params.get("duration") else 5
            # Allow some cushion: duration * tick_time + extra (here we use seconds heuristic)
            timeout_seconds = max(30.0, float(duration) * 6.0 + 30.0)

            outcome = await self._wait_for_contract_settlement(contract_id, stake_amount, timeout=timeout_seconds, poll_interval=3.0)
            return outcome

        except Exception as e:
            logger.error(f"Buy contract error: {e}")
            return {"error": {"message": str(e)}}

    async def get_contract_status(self, contract_id: str):
        """Get the status of a contract"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        request = {
            "proposal_open_contract": 1,
            "contract_id": contract_id
        }

        return await self.send_request(request)

    async def get_balance(self):
        """Get account balance"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        response = await self.send_request({
            "balance": 1,
            "subscribe": 0
        })

        # Update local balance but don't modify P&L calculations
        if "balance" in response:
            try:
                new_balance = float(response["balance"]["balance"])
                logger.debug(f"Balance updated from API: ${new_balance}")
                self.current_balance = new_balance
            except Exception:
                pass

        return response

    async def get_account_limits(self):
        """Get account limits"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        return await self.send_request({
            "get_limits": 1
        })

    async def ping(self):
        """Send a ping to test connection"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")

        return await self.send_request({
            "ping": 1
        })

    async def disconnect(self):
        """Close connection and cleanup"""
        logger.info("Disconnecting from Deriv API...")
        await self._cleanup_connection()
        self._message_handlers = []
        logger.info("Disconnected from Deriv API")

    def get_session_pl(self):
        """Get the current session profit/loss based on completed trades only"""
        return self.session_profit_loss

    def get_available_balance(self):
        """Get balance minus pending stakes (what's actually available to trade)"""
        return max(0.0, self.current_balance - self.pending_stakes)

    def get_pending_stakes(self):
        """Get total amount currently in pending trades"""
        return self.pending_stakes

    def reset_session_pl(self):
        """Reset the session profit/loss tracking"""
        self.initial_balance = self.current_balance
        self.session_profit_loss = 0.0
        self.pending_stakes = 0.0
        self.completed_trades = []

    def get_trade_history(self):
        """Get the history of completed trades"""
        return self.completed_trades

# Global API instance
deriv_api = DerivAPI()