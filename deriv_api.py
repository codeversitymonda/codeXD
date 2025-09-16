import json
import websockets
import asyncio
from typing import Callable, Optional, Dict, Any
from config import settings

class DerivAPI:
    def __init__(self):
        self.connection = None
        self.connected = False
        self._receive_lock = asyncio.Lock()  # Lock to prevent concurrent receives
        self._message_handlers = []
        
    async def connect(self, token: str = None):
        """Establish connection to Deriv API"""
        try:
            print(f"Connecting to Deriv API at: {settings.DERIV_WS_URL}")
            self.connection = await websockets.connect(settings.DERIV_WS_URL)
            self.connected = True
            
            # Authorize if token is provided
            if token:
                auth_response = await self.send_request({
                    "authorize": token
                })
                if "error" in auth_response:
                    error_msg = auth_response['error'].get('message', 'Unknown error')
                    print(f"Authorization failed: {error_msg}")
                    raise ConnectionError(f"Authorization failed: {error_msg}")
                print("Authorization successful")
                return auth_response
            return {"success": True}
        except Exception as e:
            print(f"Connection error: {e}")
            self.connected = False
            raise
    
    async def send_request(self, request_data: dict):
        """Send request to Deriv API"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")
            
        await self.connection.send(json.dumps(request_data))
        
        # Use lock to prevent concurrent receive operations
        async with self._receive_lock:
            response = await self.connection.recv()
            
        return json.loads(response)
    
    async def subscribe_ticks(self, symbol: str, callback: Callable):
        """Subscribe to tick stream for a symbol"""
        # Store the callback for this symbol
        self._message_handlers.append(('ticks', symbol, callback))
        
        # Send subscription request
        return await self.send_request({
            "ticks": symbol,
            "subscribe": 1
        })
    
    async def start_listening(self):
        """Start listening for incoming messages and route them to handlers"""
        if not self.connected or not self.connection:
            raise ConnectionError("Not connected to Deriv API")
            
        try:
            while self.connected:
                # Use lock to prevent concurrent receive operations
                async with self._receive_lock:
                    message = await self.connection.recv()
                    
                data = json.loads(message)
                
                # Route message to appropriate handlers
                await self._route_message(data)
                
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed")
            self.connected = False
        except Exception as e:
            print(f"Error in message listening: {e}")
            self.connected = False
    
    async def _route_message(self, data: Dict[str, Any]):
        """Route incoming message to appropriate handlers"""
        if "tick" in data:
            # This is a tick message
            for msg_type, symbol, callback in self._message_handlers:
                if msg_type == 'ticks' and data.get("tick", {}).get("symbol") == symbol:
                    try:
                        await callback(data["tick"])
                    except Exception as e:
                        print(f"Error in tick handler: {e}")
        
        elif "error" in data:
            print(f"API Error: {data['error']['message']}")
        
        # Add handling for other message types as needed
    
    async def buy_contract(self, contract_data: dict):
        """Buy a contract"""
        return await self.send_request({
            "buy": 1,
            "price": contract_data.get("amount", 10),
            "parameters": {
                "amount": contract_data.get("amount", 10),
                "basis": contract_data.get("basis", "stake"),
                "contract_type": contract_data.get("contract_type", "CALL"),
                "currency": contract_data.get("currency", "USD"),
                "duration": contract_data.get("duration", 5),
                "duration_unit": contract_data.get("duration_unit", "minutes"),
                "symbol": contract_data.get("symbol", "R_100")
            }
        })
    
    async def get_balance(self):
        """Get account balance"""
        return await self.send_request({
            "balance": 1,
            "subscribe": 0
        })
    
    async def disconnect(self):
        """Close connection"""
        if self.connection:
            await self.connection.close()
            self.connected = False
        self._message_handlers = []

# Global API instance
deriv_api = DerivAPI()