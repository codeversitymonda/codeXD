import json
import websockets
import asyncio
from typing import Callable, Optional, Dict, Any
from config import settings
import uuid
import time

class DerivAPI:
    def __init__(self):
        self.connection = None
        self.connected = False
        self._message_handlers = []
        self._listening_task = None
        self._pending_requests = {}  # Store pending requests by ID
        self._req_id_counter = 1  # Simple counter for request IDs
        self._connection_lock = asyncio.Lock()  # Prevent concurrent connections
        
    def _generate_req_id(self) -> str:
        """Generate a simple numeric request ID"""
        req_id = str(self._req_id_counter)
        self._req_id_counter += 1
        return req_id
        
    async def connect(self, token: str = None):
        """Establish connection to Deriv API"""
        async with self._connection_lock:
            try:
                print(f"Connecting to Deriv API at: {settings.DERIV_WS_URL}")
                
                # Clean shutdown of existing connection
                await self._cleanup_connection()
                
                # Create new connection
                self.connection = await websockets.connect(
                    settings.DERIV_WS_URL,
                    ping_interval=20,  # Send ping every 20 seconds
                    ping_timeout=10,   # Wait 10 seconds for pong
                    close_timeout=10   # Wait 10 seconds when closing
                )
                self.connected = True
                
                # Start the message listener FIRST
                self._listening_task = asyncio.create_task(self._listen_loop())
                
                # Small delay to ensure listener is ready
                await asyncio.sleep(0.1)
                
                # Authorize if token is provided
                if token:
                    auth_response = await self.send_request({
                        "authorize": token
                    }, timeout=15.0)  # Longer timeout for auth
                    
                    if "error" in auth_response:
                        error_msg = auth_response['error'].get('message', 'Unknown error')
                        print(f"Authorization failed: {error_msg}")
                        await self._cleanup_connection()
                        return {"error": {"message": error_msg}}
                        
                    print("Authorization successful")
                    return auth_response
                    
                return {"success": True}
                
            except Exception as e:
                print(f"Connection error: {e}")
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
        for future in self._pending_requests.values():
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
        """Send request to Deriv API and get response using request ID system"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")
        
        try:
            # Generate simple numeric request ID
            req_id = self._generate_req_id()
            request_data["req_id"] = int(req_id)  # Ensure it's an integer
            
            # Create a future to wait for the response
            response_future = asyncio.Future()
            self._pending_requests[req_id] = response_future
            
            # Send request
            message = json.dumps(request_data)
            print(f"Sending request: {message}")
            await self.connection.send(message)
            
            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=timeout)
                return response
            except asyncio.TimeoutError:
                # Clean up on timeout
                self._pending_requests.pop(req_id, None)
                raise ConnectionError(f"Request timed out after {timeout} seconds")
            
        except websockets.exceptions.ConnectionClosed:
            self.connected = False
            raise ConnectionError("WebSocket connection closed")
        except Exception as e:
            # Clean up on error
            if 'req_id' in locals():
                self._pending_requests.pop(req_id, None)
            print(f"Send request error: {e}")
            raise
    
    async def _listen_loop(self):
        """Single message listener that dispatches to appropriate handlers"""
        try:
            while self.connected and self.connection and not self.connection.closed:
                try:
                    # Use asyncio.wait_for to add timeout protection
                    message = await asyncio.wait_for(
                        self.connection.recv(), 
                        timeout=30.0
                    )
                    data = json.loads(message)
                    print(f"Received message: {message}")
                    
                    # Handle request-response pairs
                    req_id = data.get("req_id")
                    if req_id is not None:
                        req_id_str = str(req_id)  # Convert to string for lookup
                        if req_id_str in self._pending_requests:
                            future = self._pending_requests.pop(req_id_str)
                            if not future.done():
                                future.set_result(data)
                            continue
                    
                    # Handle subscription messages (ticks, etc.) in a separate task
                    # This prevents blocking the main listener
                    asyncio.create_task(self._route_message(data))
                    
                except asyncio.TimeoutError:
                    # Timeout is normal, just continue listening
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("WebSocket connection closed in listener")
                    self.connected = False
                    break
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}")
                    continue
                except Exception as e:
                    print(f"Error in message listener: {e}")
                    # Don't break on individual message errors
                    continue
                    
        except asyncio.CancelledError:
            print("Message listener cancelled")
            self.connected = False
        except Exception as e:
            print(f"Fatal error in listening loop: {e}")
            self.connected = False
        finally:
            # Cancel all pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.cancel()
            self._pending_requests.clear()
    
    async def _route_message(self, data: Dict[str, Any]):
        """Route incoming subscription messages to appropriate handlers"""
        try:
            if "tick" in data:
                # Route tick messages to handlers
                tick_symbol = data["tick"].get("symbol")
                for msg_type, symbol, callback in self._message_handlers:
                    if msg_type == 'ticks' and tick_symbol == symbol:
                        await callback(data["tick"])
                        
            elif "error" in data:
                print(f"API Error: {data['error'].get('message', 'Unknown error')}")
                
        except Exception as e:
            print(f"Error routing message: {e}")
    
    async def subscribe_ticks(self, symbol: str, callback: Callable):
        """Subscribe to tick stream for a symbol"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")
            
        # Store the callback for this symbol
        self._message_handlers.append(('ticks', symbol, callback))
        
        # Send subscription request (without req_id for subscriptions)
        subscription_request = {
            "ticks": symbol,
            "subscribe": 1
        }
        
        try:
            # Send directly without waiting for response (subscriptions don't need response handling)
            message = json.dumps(subscription_request)
            print(f"Sending subscription: {message}")
            await self.connection.send(message)
            return {"status": "subscribed"}
        except Exception as e:
            print(f"Failed to subscribe to ticks: {e}")
            # Remove the handler if subscription failed
            self._message_handlers = [
                (msg_type, sym, cb) for msg_type, sym, cb in self._message_handlers 
                if not (msg_type == 'ticks' and sym == symbol and cb == callback)
            ]
            raise
    
    async def start_listening(self):
        """Start listening task (already started in connect, this is for compatibility)"""
        if not self._listening_task or self._listening_task.done():
            self._listening_task = asyncio.create_task(self._listen_loop())
        return self._listening_task
    
    async def buy_contract(self, contract_params: dict):
        """Buy a contract using proper Deriv API format"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")
        
        # Extract parameters from the input
        params = contract_params.get("parameters", contract_params)
        
        # Build the buy request in the correct format
        buy_request = {
            "buy": 1,
            "price": float(params.get("amount", 1.0)),
            "parameters": {
                "contract_type": params.get("contract_type", "DIGITDIFF"),
                "symbol": params.get("symbol", "R_100"),
                "barrier": str(params.get("barrier", "0")),
                "amount": float(params.get("amount", 1.0)),
                "basis": params.get("basis", "stake"),
                "duration": int(params.get("duration", 5)),
                "duration_unit": params.get("duration_unit", "t"),
                "currency": params.get("currency", "USD")
            }
        }
        
        return await self.send_request(buy_request)
    
    async def get_proposal(self, contract_params: dict):
        """Get a proposal for a contract"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")
        
        params = contract_params.get("parameters", contract_params)
        
        proposal_request = {
            "proposal": 1,
            "amount": float(params.get("amount", 1.0)),
            "basis": params.get("basis", "stake"),
            "contract_type": params.get("contract_type", "DIGITDIFF"),
            "symbol": params.get("symbol", "R_100"),
            "barrier": str(params.get("barrier", "0")),
            "duration": int(params.get("duration", 5)),
            "duration_unit": params.get("duration_unit", "t"),
            "currency": params.get("currency", "USD")
        }
        
        return await self.send_request(proposal_request)
    
    async def buy_proposal(self, proposal_id: str, price: float):
        """Buy a specific proposal"""
        if not self.connected:
            raise ConnectionError("Not connected to Deriv API")
        
        buy_request = {
            "buy": proposal_id,
            "price": float(price)
        }
        
        return await self.send_request(buy_request)
    
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
        
        return await self.send_request({
            "balance": 1,
            "subscribe": 0
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
        print("Disconnecting from Deriv API...")
        await self._cleanup_connection()
        # Clear handlers
        self._message_handlers = []
        print("Disconnected from Deriv API")

# Global API instance
deriv_api = DerivAPI()