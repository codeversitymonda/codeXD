import asyncio
from collections import Counter, deque
from typing import Dict, Any, Optional, List
from deriv_api import deriv_api
import time
import json
import uuid


class DigitDiffersBot:
    def __init__(self, user_id: str = None):
        # User-specific identifier
        self.user_id = user_id or str(uuid.uuid4())
        
        self.is_running = False
        self.is_connected = False
        self.active_symbol = None
        self.strategy = "digit_differs_average"
        self.callback_function = None
        self.auth_token = None
        
        # Enhanced tick history tracking
        self.tick_history = deque(maxlen=100)
        self.digit_frequencies = Counter()
        self.last_trade_time = 0
        self.trade_cooldown = 5  # seconds between trades
        
        # New strategy-specific tracking
        self.last_5_digits = deque(maxlen=5)  # Store last 5 digits for averaging
        self.current_target_digit = None
        self.trade_cycle_count = 0
        
        # Trading parameters
        self.stake = max(0.35, 1.0)  # Ensure minimum stake requirement
        self.duration = 1  # 5 ticks duration
        self.min_analysis_ticks = 5  # Need at least 5 ticks for new strategy
        
        # Performance tracking
        self.trades_placed = 0
        self.successful_trades = 0
        self.total_pnl = 0.0
        self.current_balance = 0.0
        
        # Risk management
        self.max_stake_percentage = 0.02  # Max 2% of balance per trade
        self.daily_loss_limit = 50.0  # Stop if daily loss exceeds this
        self.daily_pnl = 0.0
        self.trade_start_time = time.time()
        
        # Connection management
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.reconnect_delay = 5  # seconds

    def reset_data(self):
        """Reset all tick data and analysis"""
        self.tick_history.clear()
        self.digit_frequencies.clear()
        self.last_5_digits.clear()  # Clear the averaging queue
        self.current_target_digit = None
        self.trade_cycle_count = 0
        self.trades_placed = 0
        self.successful_trades = 0
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.trade_start_time = time.time()
        self.last_trade_time = 0
        
        return {
            "status": "success",
            "message": "All tick data and statistics have been reset",
            "user_id": self.user_id
        }

    async def ensure_connection(self) -> bool:
        """Ensure we have a valid connection to Deriv API"""
        if deriv_api.connected:
            try:
                # Test connection with a simple ping - use shorter timeout
                ping_response = await deriv_api.ping()
                if "error" not in ping_response:
                    self.is_connected = True
                    return True
                else:
                    await self._log(f"Connection test failed: {ping_response.get('error', {}).get('message', 'Unknown error')}", "warning")
                    self.is_connected = False
            except Exception as e:
                await self._log(f"Connection test error: {str(e)}", "warning")
                self.is_connected = False
        
        # If not connected, attempt to reconnect
        if not self.is_connected and self.auth_token:
            return await self._reconnect()
        
        return False

    async def _reconnect(self) -> bool:
        """Attempt to reconnect to Deriv API"""
        if self.connection_attempts >= self.max_connection_attempts:
            await self._log("Max reconnection attempts reached", "error")
            return False
            
        self.connection_attempts += 1
        await self._log(f"Attempting to reconnect... (Attempt {self.connection_attempts}/{self.max_connection_attempts})", "info")
        
        try:
            # Properly disconnect first
            await deriv_api.disconnect()
            
            # Wait before reconnecting
            await asyncio.sleep(self.reconnect_delay)
            
            # Attempt connection
            auth_result = await deriv_api.connect(self.auth_token)
            if "error" in auth_result:
                await self._log(f"Reconnection failed: {auth_result['error']['message']}", "error")
                return False
            
            self.is_connected = True
            self.connection_attempts = 0
            await self._log("Successfully reconnected to Deriv API", "success")
            
            # Resubscribe to ticks if we were running
            if self.is_running and self.active_symbol:
                await deriv_api.subscribe_ticks(self.active_symbol, self._handle_tick)
                await self._log(f"Resubscribed to {self.active_symbol} ticks", "info")
            
            return True
            
        except Exception as e:
            await self._log(f"Reconnection error: {str(e)}", "error")
            return False

    async def start(self, symbol: str, token: str, stake: float = 1.0, 
                   duration: int = 1, callback: Optional[callable] = None):
        """Start the Digit Differs trading bot with new averaging strategy"""
        try:
            self.auth_token = token
            self.connection_attempts = 0
            
            # Connect to Deriv API
            auth_result = await deriv_api.connect(token)
            if "error" in auth_result:
                return {"status": "error", "message": auth_result["error"]["message"]}

            self.is_connected = True
            self.is_running = True
            self.active_symbol = symbol
            self.callback_function = callback
            self.stake = stake
            self.duration = duration
            self.trade_start_time = time.time()

            # Get initial balance
            balance_response = await deriv_api.get_balance()
            if "balance" in balance_response:
                self.current_balance = float(balance_response["balance"]["balance"])

            # Subscribe to tick stream
            await deriv_api.subscribe_ticks(symbol, self._handle_tick)
            
            # Start listening for API messages
            await deriv_api.start_listening()

            await self._log(f"Started Average Last 5 Digits strategy on {symbol} with ${stake} stake (User: {self.user_id})", "success")
            await self._log("Strategy: Calculate average of last 5 digits, use as DIGITDIFF target", "info")
            return {"status": "started", "symbol": symbol, "strategy": self.strategy, "user_id": self.user_id}

        except Exception as e:
            await self._log(f"Bot startup error: {str(e)}", "error")
            return {"status": "error", "message": str(e)}

    async def _handle_tick(self, tick_data: Dict[str, Any]):
        """Process incoming ticks and execute new averaging strategy"""
        try:
            if not self.is_running:
                return

            quote = float(tick_data["quote"])
            # Get last digit of the quote
            last_digit = int(str(quote).split('.')[-1][-1])
            
            # Update tick history and frequencies (for general tracking)
            self.tick_history.append({
                'digit': last_digit,
                'quote': quote,
                'time': tick_data.get('epoch', time.time())
            })
            
            self.digit_frequencies[last_digit] += 1
            
            # Add to our averaging queue
            self.last_5_digits.append(last_digit)
            
            # Execute strategy if we have enough data
            if len(self.last_5_digits) >= 5:
                await self._execute_average_strategy(tick_data, last_digit)

            # Callback for frontend updates (user-specific)
            if self.callback_function:
                await self.callback_function({
                    **tick_data,
                    'last_digit': last_digit,
                    'last_5_digits': list(self.last_5_digits),
                    'current_target': self.current_target_digit,
                    'total_ticks': len(self.tick_history),
                    'user_id': self.user_id
                })

        except Exception as e:
            await self._log(f"Error processing tick: {str(e)}", "error")

    def _calculate_target_digit(self) -> int:
        """Calculate target digit from average of last 5 digits (SYNCHRONOUS VERSION)"""
        if len(self.last_5_digits) < 5:
            return None
            
        # Sum the last 5 digits
        digit_sum = sum(self.last_5_digits)
        
        # Calculate average and take the integer part
        average = digit_sum / 5
        target_digit = int(average)
        
        # Ensure digit is in range 0-9
        target_digit = max(0, min(9, target_digit))
        
        return target_digit

    async def _execute_average_strategy(self, tick_data: Dict[str, Any], current_digit: int):
        """Execute DIGITDIFF strategy based on average of last 5 digits"""
        
        # CHECK CONNECTION FIRST
        if not await self.ensure_connection():
            await self._log("Cannot execute trade: Not connected to Deriv API", "error")
            
            # Try to reconnect if within attempt limits
            if self.connection_attempts < self.max_connection_attempts:
                if not await self._reconnect():
                    return
            else:
                await self._log("Max reconnection attempts reached. Stopping bot.", "error")
                await self.stop()
                return
        
        # Ensure we have an active symbol
        if not self.active_symbol:
            await self._log("No active symbol set", "error")
            return
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_trade_time < self.trade_cooldown:
            return

        # Check daily loss limit
        if self.daily_pnl <= -self.daily_loss_limit:
            await self._log(f"Daily loss limit reached (${self.daily_loss_limit}). Stopping trades.", "warning")
            return

        # Calculate target digit from last 5 digits average (FIXED: removed await)
        target_digit = self._calculate_target_digit()
        if target_digit is None:
            return
            
        # Update current target
        self.current_target_digit = target_digit

        # Log the calculation details
        await self._log(f"Last 5 digits: {list(self.last_5_digits)} → Sum: {sum(self.last_5_digits)} → Average: {sum(self.last_5_digits)/5:.1f} → Target: {target_digit}", "info")

        # Calculate dynamic stake based on balance with minimum requirement
        if self.current_balance > 0:
            max_allowed_stake = self.current_balance * self.max_stake_percentage
            adjusted_stake = min(self.stake, max_allowed_stake)
        else:
            adjusted_stake = self.stake
        
        # Ensure minimum stake requirement (Deriv minimum is $0.35)
        MINIMUM_STAKE = 0.35
        if adjusted_stake < MINIMUM_STAKE:
            await self._log(f"Stake ${adjusted_stake:.2f} is below minimum ${MINIMUM_STAKE}. Using minimum stake.", "warning")
            adjusted_stake = MINIMUM_STAKE

        # Execute DIGITDIFF trade
        try:
            # Prepare contract parameters
            contract_params = {
                "contract_type": "DIGITDIFF",
                "symbol": self.active_symbol,
                "barrier": str(target_digit),  # FIXED: Convert to string
                "amount": round(adjusted_stake, 2),
                "basis": "stake",
                "duration": self.duration,
                "duration_unit": "t",
                "currency": "USD"
            }
            
            await self._log(f"Executing DIGITDIFF trade: Predict next tick ≠ {target_digit} (${adjusted_stake} stake)", "info")
            
            # Try different trading methods
            result = await self._try_multiple_trade_methods(contract_params)
            
            # Check if trade was successful
            if result and "error" not in result:
                self.trades_placed += 1
                self.trade_cycle_count += 1
                self.last_trade_time = current_time
                
                await self._log(
                    f"DIGITDIFF trade #{self.trade_cycle_count} placed: Predict next tick ≠ {target_digit} "
                    f"(${adjusted_stake} stake)",
                    "success"
                )
                
                # Track the trade for outcome monitoring
                asyncio.create_task(self._monitor_trade_outcome(result, target_digit))
                
            elif result and "error" in result:
                await self._log(f"Trade failed: {result['error']['message']}", "error")
            else:
                await self._log("Trade failed: No response from API", "error")
                    
        except Exception as e:
            await self._log(f"Trade execution error: {str(e)}", "error")

    async def _try_multiple_trade_methods(self, contract_params: dict):
        """Try different methods to place a trade"""
        result = None
        
        # Method 1: Direct buy_contract
        try:
            await self._log("Trying direct buy_contract method...", "debug")
            result = await deriv_api.buy_contract(contract_params)
            
            if result and "error" not in result:
                await self._log("Direct buy_contract succeeded", "debug")
                return result
            else:
                await self._log(f"Direct buy_contract failed: {result.get('error', {}).get('message', 'Unknown error') if result else 'No response'}", "warning")
                
        except Exception as e:
            await self._log(f"Direct buy_contract error: {str(e)}", "warning")
        
        # Method 2: Proposal + Buy
        try:
            await self._log("Trying proposal + buy method...", "debug")
            
            # Get proposal first
            proposal_result = await deriv_api.get_proposal(contract_params)
            
            if proposal_result and "proposal" in proposal_result:
                proposal_id = proposal_result["proposal"]["id"]
                price = contract_params["amount"]
                
                await self._log(f"Got proposal {proposal_id}, now buying...", "debug")
                
                # Buy the proposal
                result = await deriv_api.buy_proposal(proposal_id, price)
                
                if result and "error" not in result:
                    await self._log("Proposal + buy succeeded", "debug")
                    return result
                else:
                    await self._log(f"Proposal buy failed: {result.get('error', {}).get('message', 'Unknown error') if result else 'No response'}", "warning")
            else:
                await self._log(f"Proposal failed: {proposal_result.get('error', {}).get('message', 'Unknown error') if proposal_result else 'No response'}", "warning")
                
        except Exception as e:
            await self._log(f"Proposal + buy error: {str(e)}", "warning")
        
        # Method 3: Raw send_request
        try:
            await self._log("Trying raw send_request method...", "debug")
            
            raw_request = {
                "buy": 1,
                "price": contract_params["amount"],
                "parameters": contract_params
            }
            
            result = await deriv_api.send_request(raw_request)
            
            if result and "error" not in result:
                await self._log("Raw send_request succeeded", "debug")
                return result
            else:
                await self._log(f"Raw send_request failed: {result.get('error', {}).get('message', 'Unknown error') if result else 'No response'}", "warning")
                
        except Exception as e:
            await self._log(f"Raw send_request error: {str(e)}", "warning")
        
        return result

    async def _monitor_trade_outcome(self, trade_result: Dict[str, Any], predicted_digit: int):
        """Monitor REAL trade outcome using Deriv API"""
        try:
            contract_id = None
            
            # Try different ways to get contract ID from the response
            if "buy" in trade_result:
                if isinstance(trade_result["buy"], dict):
                    contract_id = trade_result["buy"].get("contract_id")
                elif isinstance(trade_result["buy"], str):
                    contract_id = trade_result["buy"]
            
            if not contract_id:
                await self._log("No contract ID found in trade result", "warning")
                return
            
            await self._log(f"Monitoring contract {contract_id}", "info")
            
            # Wait for contract to settle (5 ticks + buffer)
            await asyncio.sleep(15)
            
            # Check connection before monitoring
            if not await self.ensure_connection():
                await self._log("Cannot monitor trade: Connection lost", "error")
                return
            
            try:
                # Get contract status
                contract_status = await deriv_api.get_contract_status(contract_id)
                
                if contract_status and "proposal_open_contract" in contract_status:
                    contract = contract_status["proposal_open_contract"]
                    
                    if contract.get("is_sold"):
                        # Contract is finished
                        profit_loss = float(contract.get("profit", 0))
                        
                        if profit_loss > 0:
                            self.successful_trades += 1
                            self.total_pnl += profit_loss
                            self.daily_pnl += profit_loss
                            await self._log(f"Trade WON: Contract {contract_id}. Profit: +${profit_loss:.2f}", "success")
                            await self._log(f"Cycle #{self.trade_cycle_count} completed successfully! Starting new cycle...", "info")
                            
                            # Reset for new cycle after win
                            self.last_5_digits.clear()
                            self.current_target_digit = None
                            
                        else:
                            loss = abs(profit_loss)
                            self.total_pnl += profit_loss  # Already negative
                            self.daily_pnl += profit_loss
                            await self._log(f"Trade LOST: Contract {contract_id}. Loss: -${loss:.2f}", "error")
                            await self._log(f"Continuing with current cycle #{self.trade_cycle_count}...", "info")
                        
                        # Update balance
                        balance_response = await deriv_api.get_balance()
                        if "balance" in balance_response:
                            self.current_balance = float(balance_response["balance"]["balance"])
                            
                    else:
                        await self._log(f"Contract {contract_id} still active", "info")
                        
            except Exception as api_error:
                await self._log(f"Could not get contract status: {str(api_error)}", "warning")
            
        except Exception as e:
            await self._log(f"Trade monitoring error: {str(e)}", "error")

    async def get_statistics(self) -> Dict[str, Any]:
        """Get current bot statistics"""
        win_rate = (self.successful_trades / self.trades_placed * 100) if self.trades_placed > 0 else 0
        
        return {
            "user_id": self.user_id,
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "symbol": self.active_symbol,
            "strategy": "Average Last 5 Digits",
            "total_trades": self.trades_placed,
            "successful_trades": self.successful_trades,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "current_balance": round(self.current_balance, 2),
            "current_target_digit": self.current_target_digit,
            "trade_cycle_count": self.trade_cycle_count,
            "tick_analysis": {
                "total_ticks_analyzed": len(self.tick_history),
                "digit_frequencies": dict(self.digit_frequencies),
                "recent_ticks": [tick['digit'] for tick in list(self.tick_history)[-10:]],
                "last_5_digits": list(self.last_5_digits),
                "last_5_calculation": self._get_last_5_calculation()
            },
            "uptime_minutes": round((time.time() - self.trade_start_time) / 60, 1),
            "connection_status": {
                "connected": self.is_connected,
                "connection_attempts": self.connection_attempts,
                "max_attempts": self.max_connection_attempts
            }
        }

    def _get_last_5_calculation(self) -> Dict[str, Any]:
        """Get details of the last 5 digits calculation"""
        if len(self.last_5_digits) < 5:
            return {
                "digits_collected": len(self.last_5_digits),
                "digits": list(self.last_5_digits),
                "ready_to_trade": False
            }
        
        digit_sum = sum(self.last_5_digits)
        average = digit_sum / 5
        target = int(average)
        
        return {
            "digits_collected": len(self.last_5_digits),
            "digits": list(self.last_5_digits),
            "sum": digit_sum,
            "average": round(average, 2),
            "target_digit": target,
            "ready_to_trade": True
        }

    async def force_trade(self) -> Dict[str, Any]:
        """Execute immediate trade regardless of conditions"""
        if not self.is_running:
            return {"status": "error", "message": "Bot not running"}
        
        if not await self.ensure_connection():
            return {"status": "error", "message": "Not connected to Deriv API"}
        
        if len(self.last_5_digits) < 5:
            return {"status": "error", "message": f"Need 5 digits for calculation, only have {len(self.last_5_digits)}"}
        
        target_digit = self._calculate_target_digit()  # FIXED: removed await
        if target_digit is None:
            return {"status": "error", "message": "Cannot calculate target digit"}
        
        last_tick = self.tick_history[-1] if self.tick_history else None
        if not last_tick:
            return {"status": "error", "message": "No tick data available"}
        
        # Force trade by temporarily setting last trade time to 0
        original_trade_time = self.last_trade_time
        self.last_trade_time = 0
        
        try:
            await self._execute_average_strategy(
                {"symbol": self.active_symbol, "quote": last_tick['quote']}, 
                last_tick['digit']
            )
            
            return {
                "status": "success", 
                "message": f"Force trade executed on digit {target_digit}",
                "target_digit": target_digit,
                "calculation": self._get_last_5_calculation(),
                "user_id": self.user_id
            }
        finally:
            # Restore original trade time if force trade failed
            if self.last_trade_time == 0:
                self.last_trade_time = original_trade_time

    async def update_settings(self, **kwargs):
        """Update bot settings dynamically"""
        if "stake" in kwargs:
            new_stake = max(0.35, float(kwargs["stake"]))  # Ensure minimum stake
            self.stake = new_stake
        if "trade_cooldown" in kwargs:
            self.trade_cooldown = max(1, int(kwargs["trade_cooldown"]))
        if "daily_loss_limit" in kwargs:
            self.daily_loss_limit = max(10, float(kwargs["daily_loss_limit"]))
        if "duration" in kwargs:
            self.duration = max(1, int(kwargs["duration"]))
        
        await self._log(f"Settings updated for user {self.user_id}", "info")

    async def stop(self):
        """Stop the trading bot"""
        self.is_running = False
        self.is_connected = False
        
        # Generate session summary
        stats = await self.get_statistics()
        await self._log(f"Session ended - Trades: {stats['total_trades']}, "
                       f"Win Rate: {stats['win_rate']}%, PnL: ${stats['total_pnl']}", "info")
        
        try:
            await deriv_api.disconnect()
        except:
            pass
            
        return {"status": "stopped", "session_stats": stats, "user_id": self.user_id}

    async def _log(self, message: str, level: str = "info"):
        """Internal logging method"""
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] [{self.user_id}] [{level.upper()}] {message}")
        
        # Send logs to frontend (user-specific)
        if self.callback_function:
            try:
                await self.callback_function({
                    "type": "log",
                    "message": message,
                    "level": level,
                    "timestamp": time.time(),
                    "user_id": self.user_id
                })
            except:
                pass


# User-specific bot instances storage
user_bots = {}

def get_user_bot(user_id: str) -> DigitDiffersBot:
    """Get or create a bot instance for a specific user"""
    if user_id not in user_bots:
        user_bots[user_id] = DigitDiffersBot(user_id)
    return user_bots[user_id]

def cleanup_inactive_bots():
    """Clean up inactive bot instances (call this periodically)"""
    inactive_users = []
    for user_id, bot in user_bots.items():
        # Remove bots that haven't been running for more than 1 hour
        if not bot.is_running and (time.time() - bot.trade_start_time) > 3600:
            inactive_users.append(user_id)
    
    for user_id in inactive_users:
        del user_bots[user_id]
        print(f"Cleaned up inactive bot for user: {user_id}")