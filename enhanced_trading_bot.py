import asyncio
from collections import Counter, deque
from typing import Dict, Any, Optional, List
import time
import json
import uuid
import logging

# Import the fixed Deriv API
from deriv_api import deriv_api

logger = logging.getLogger(__name__)

class RealTradingBot:
    def __init__(self, user_id: str = None):
        # User-specific identifier
        self.user_id = user_id or str(uuid.uuid4())
        
        self.is_running = False
        self.is_connected = False
        self.active_symbol = None
        self.strategy = "digit_differs_average_enhanced"
        self.callback_function = None
        self.auth_token = None
        
        # Enhanced tick history tracking
        self.tick_history = deque(maxlen=100)
        self.digit_frequencies = Counter()
        self.last_trade_time = 0
        self.trade_cooldown = 5  # seconds between trades
        
        # Strategy-specific tracking
        self.last_5_digits = deque(maxlen=5)
        self.current_target_digit = None
        self.trade_cycle_count = 0
        
        # Enhanced trading parameters
        self.base_stake = 1.79  # Base stake amount
        self.current_stake = 1.79  # Current stake (modified by martingale)
        self.duration = 5  # Duration in ticks
        self.min_analysis_ticks = 5
        
        # MARTINGALE SYSTEM
        self.martingale_enabled = False
        self.martingale_multiplier = 2.0
        self.martingale_max_steps = 5
        self.martingale_current_step = 0
        self.consecutive_losses = 0
        self.last_trade_result = None
        
        # TAKE PROFIT & STOP LOSS
        self.take_profit_enabled = False
        self.take_profit_amount = 50.0
        self.stop_loss_enabled = False
        self.stop_loss_amount = -25.0
        self.session_start_balance = 0.0
        
        # MARKET ROTATION SYSTEM
        self.market_rotation_enabled = False
        self.trades_per_market = 3
        self.trades_on_current_market = 0
        self.available_markets = ['R_10', 'R_25', 'R_50', 'R_75', 'R_100']
        self.current_market_index = 0
        
        # FIXED: Performance tracking using proper P&L from API
        self.trades_placed = 0
        self.successful_trades = 0
        
        # Enhanced risk management
        self.max_stake_percentage = 0.05  # Max 5% of balance per trade
        self.daily_loss_limit = 100.0
        self.daily_pnl = 0.0
        self.trade_start_time = time.time()
        
        # Connection management
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.reconnect_delay = 5

    def reset_data(self):
        """Reset all tick data and analysis"""
        self.tick_history.clear()
        self.digit_frequencies.clear()
        self.last_5_digits.clear()
        self.current_target_digit = None
        self.trade_cycle_count = 0
        self.trades_placed = 0
        self.successful_trades = 0
        self.daily_pnl = 0.0
        self.trade_start_time = time.time()
        self.last_trade_time = 0
        
        # Reset martingale
        self.current_stake = self.base_stake
        self.martingale_current_step = 0
        self.consecutive_losses = 0
        self.last_trade_result = None
        
        # Reset market rotation
        self.trades_on_current_market = 0
        self.current_market_index = 0
        
        # FIXED: Reset API-level P&L tracking
        deriv_api.reset_session_pl()
        
        return {
            "status": "success",
            "message": "All data and systems have been reset",
            "user_id": self.user_id
        }

    async def ensure_connection(self) -> bool:
        """Ensure we have a valid connection to Deriv API"""
        if deriv_api.connected:
            try:
                ping_response = await deriv_api.ping()
                if "error" not in ping_response:
                    self.is_connected = True
                    return True
                else:
                    logger.warning(f"Connection test failed: {ping_response.get('error', {}).get('message', 'Unknown error')}")
                    self.is_connected = False
            except Exception as e:
                logger.warning(f"Connection test error: {str(e)}")
                self.is_connected = False
        
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
            await deriv_api.disconnect()
            await asyncio.sleep(self.reconnect_delay)
            
            auth_result = await deriv_api.connect(self.auth_token)
            if "error" in auth_result:
                await self._log(f"Reconnection failed: {auth_result['error']['message']}", "error")
                return False
            
            self.is_connected = True
            self.connection_attempts = 0
            await self._log("Successfully reconnected to Deriv API", "success")
            
            if self.is_running and self.active_symbol:
                await deriv_api.subscribe_ticks(self.active_symbol, self._handle_tick)
                await self._log(f"Resubscribed to {self.active_symbol} ticks", "info")
            
            return True
            
        except Exception as e:
            await self._log(f"Reconnection error: {str(e)}", "error")
            return False

    async def start(self, symbol: str, token: str, base_stake: float = 1.79, 
                   duration: int = 5, callback: Optional[callable] = None, **kwargs):
        """Start the enhanced trading bot"""
        try:
            self.auth_token = token
            self.connection_attempts = 0
            
            # Connect to Deriv API with detailed logging
            await self._log("Connecting to Deriv API for REAL TRADING...", "info")
            auth_result = await deriv_api.connect(token)
            
            if "error" in auth_result:
                await self._log(f"Connection failed: {auth_result['error']['message']}", "error")
                return {"status": "error", "message": auth_result["error"]["message"]}

            # Verify we have account info
            if not deriv_api.account_info:
                await self._log("WARNING: No account information received", "warning")
                return {"status": "error", "message": "Failed to retrieve account information"}

            # Check account limits and permissions
            try:
                limits_response = await deriv_api.get_account_limits()
                if "get_limits" in limits_response:
                    limits = limits_response["get_limits"]
                    await self._log(f"Account verified. Max payout: ${limits.get('max_payout', 'N/A')}", "info")
                    
                    # Check if trading is allowed
                    if limits.get('open_positions') == 0:
                        await self._log("WARNING: Account may not be authorized for trading", "warning")
                        
            except Exception as e:
                await self._log(f"Could not retrieve account limits: {str(e)}", "warning")

            self.is_connected = True
            self.is_running = True
            self.active_symbol = symbol
            self.callback_function = callback
            self.base_stake = base_stake
            self.current_stake = base_stake
            self.duration = duration
            self.trade_start_time = time.time()

            # Configure enhanced features from kwargs
            self.martingale_enabled = kwargs.get('martingale_enabled', False)
            self.martingale_multiplier = kwargs.get('martingale_multiplier', 2.0)
            self.martingale_max_steps = kwargs.get('martingale_max_steps', 5)
            
            self.take_profit_enabled = kwargs.get('take_profit_enabled', False)
            self.take_profit_amount = kwargs.get('take_profit_amount', 50.0)
            self.stop_loss_enabled = kwargs.get('stop_loss_enabled', False)
            self.stop_loss_amount = kwargs.get('stop_loss_amount', -25.0)
            
            # Configure market rotation
            self.market_rotation_enabled = kwargs.get('auto_market_rotation', False)
            self.trades_per_market = kwargs.get('trades_per_market', 3)
            
            # Set initial market - find index of requested symbol
            if symbol in self.available_markets:
                self.current_market_index = self.available_markets.index(symbol)
            else:
                self.current_market_index = 0
                await self._log(f"Symbol {symbol} not in rotation list, using {self.available_markets[0]}", "warning")

            # FIXED: Store initial balance for session tracking
            self.session_start_balance = deriv_api.current_balance
            
            await self._log(f"REAL TRADING STARTED on {symbol}", "success")
            await self._log(f"Account: {deriv_api.account_info.get('loginid', 'Unknown')}", "info")
            await self._log(f"Balance: ${deriv_api.current_balance:.2f}", "info")
            await self._log(f"Base stake: ${base_stake}", "info")
            await self._log(f"WARNING: THIS WILL USE REAL MONEY!", "warning")

            # Subscribe to tick stream
            await deriv_api.subscribe_ticks(symbol, self._handle_tick)

            await self._log(f"Subscribed to {symbol} tick stream", "info")
            
            return {
                "status": "started", 
                "symbol": symbol, 
                "strategy": self.strategy, 
                "user_id": self.user_id,
                "account": deriv_api.account_info.get('loginid'),
                "balance": deriv_api.current_balance,
                "features": {
                    "martingale": self.martingale_enabled,
                    "take_profit": self.take_profit_enabled,
                    "stop_loss": self.stop_loss_enabled,
                    "market_rotation": self.market_rotation_enabled
                }
            }

        except Exception as e:
            await self._log(f"Bot startup error: {str(e)}", "error")
            return {"status": "error", "message": str(e)}

    async def _handle_tick(self, tick_data: Dict[str, Any]):
        """Process incoming ticks with enhanced features"""
        try:
            if not self.is_running:
                return

            quote = float(tick_data["quote"])
            last_digit = int(str(quote).split('.')[-1][-1])
            
            # Update tick history
            self.tick_history.append({
                'digit': last_digit,
                'quote': quote,
                'time': tick_data.get('epoch', time.time())
            })
            
            self.digit_frequencies[last_digit] += 1
            self.last_5_digits.append(last_digit)
            
            await self._log(f"Tick: {quote} (digit: {last_digit})", "info")
            
            # Check take profit and stop loss
            if await self._check_profit_loss_conditions():
                return
            
            # Execute enhanced strategy
            if len(self.last_5_digits) >= 5:
                await self._execute_enhanced_strategy(tick_data, last_digit)

            # Callback for frontend updates
            if self.callback_function:
                await self.callback_function({
                    **tick_data,
                    'last_digit': last_digit,
                    'last_5_digits': list(self.last_5_digits),
                    'current_target': self.current_target_digit,
                    'current_stake': self.current_stake,
                    'martingale_step': self.martingale_current_step,
                    'session_pnl': deriv_api.get_session_pl(),  # FIXED: Use API's session P&L
                    'pending_stakes': deriv_api.get_pending_stakes(),  # FIXED: Show pending stakes
                    'total_ticks': len(self.tick_history),
                    'user_id': self.user_id
                })

        except Exception as e:
            await self._log(f"Error processing tick: {str(e)}", "error")

    async def _check_profit_loss_conditions(self) -> bool:
        """Check if take profit or stop loss conditions are met"""
        # FIXED: Use actual session P&L from API instead of balance difference
        session_pnl = deriv_api.get_session_pl()
        
        # Take Profit
        if self.take_profit_enabled and session_pnl >= self.take_profit_amount:
            await self._log(f"TAKE PROFIT REACHED: ${session_pnl:.2f} >= ${self.take_profit_amount}", "success")
            await self.stop()
            return True
        
        # Stop Loss
        if self.stop_loss_enabled and session_pnl <= self.stop_loss_amount:
            await self._log(f"STOP LOSS REACHED: ${session_pnl:.2f} <= ${self.stop_loss_amount}", "warning")
            await self.stop()
            return True
        
        return False

    def _calculate_martingale_stake(self) -> float:
        """Calculate stake based on martingale system"""
        if not self.martingale_enabled:
            return self.base_stake
        
        if self.martingale_current_step == 0:
            return self.base_stake
        
        # Calculate martingale stake
        martingale_stake = self.base_stake * (self.martingale_multiplier ** self.martingale_current_step)
        
        # FIXED: Use available balance (excluding pending stakes) for limit calculation
        available_balance = deriv_api.get_available_balance()
        max_allowed = available_balance * self.max_stake_percentage
        
        if martingale_stake > max_allowed:
            martingale_stake = max_allowed
        
        return round(martingale_stake, 2)

    def _calculate_target_digit(self) -> int:
        """Calculate target digit from average of last 5 digits"""
        if len(self.last_5_digits) < 5:
            return None
        
        digit_sum = sum(self.last_5_digits)
        average = digit_sum / 5
        target_digit = int(average)
        return max(0, min(9, target_digit))

    async def _execute_enhanced_strategy(self, tick_data: Dict[str, Any], current_digit: int):
        """Execute enhanced DIGITDIFF strategy with real trades"""
        
        # Check connection
        if not await self.ensure_connection():
            await self._log("Cannot execute REAL TRADE: Not connected to Deriv API", "error")
            return
        
        if not self.active_symbol:
            await self._log("No active symbol set", "error")
            return
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_trade_time < self.trade_cooldown:
            return

        # FIXED: Check daily loss limit using actual P&L
        session_pnl = deriv_api.get_session_pl()
        if session_pnl <= -self.daily_loss_limit:
            await self._log(f"Daily loss limit reached (${self.daily_loss_limit}). Stopping trades.", "warning")
            return

        # Only trade if we're ready for a new cycle
        if self.current_target_digit is not None and self.martingale_current_step == 0:
            return

        # Calculate target digit
        target_digit = self._calculate_target_digit()
        if target_digit is None:
            return
        
        # Update current target
        self.current_target_digit = target_digit

        # Calculate stake (with martingale if enabled)
        calculated_stake = self._calculate_martingale_stake()
        
        # FIXED: Check if we have enough available balance
        available_balance = deriv_api.get_available_balance()
        if calculated_stake > available_balance:
            await self._log(f"Insufficient available balance: ${available_balance:.2f} < ${calculated_stake:.2f}", "error")
            await self._log(f"(Pending stakes: ${deriv_api.get_pending_stakes():.2f})", "info")
            return
        
        self.current_stake = calculated_stake

        # Log calculation details
        digits_str = " + ".join(str(d) for d in self.last_5_digits)
        await self._log(f"Last 5 digits: {list(self.last_5_digits)} → Sum: {sum(self.last_5_digits)} → Average: {sum(self.last_5_digits)/5:.1f} → Target: {target_digit}", "info")
        
        if self.martingale_enabled and self.martingale_current_step > 0:
            await self._log(f"MARTINGALE Step {self.martingale_current_step}: Stake increased to ${calculated_stake} (x{self.martingale_multiplier ** self.martingale_current_step:.1f})", "warning")

        # Ensure minimum stake
        MINIMUM_STAKE = 0.35  # Deriv minimum
        if calculated_stake < MINIMUM_STAKE:
            await self._log(f"Stake ${calculated_stake:.2f} below minimum ${MINIMUM_STAKE}. Using minimum.", "warning")
            calculated_stake = MINIMUM_STAKE

        # Execute REAL trade
        try:
            contract_params = {
                "contract_type": "DIGITDIFF",
                "symbol": self.active_symbol,
                "barrier": str(target_digit),
                "amount": round(calculated_stake, 2),
                "basis": "stake",
                "duration": self.duration,
                "duration_unit": "t",
                "currency": "USD"
            }
            
            await self._log(f"🔥 EXECUTING REAL TRADE: DIGITDIFF ≠ {target_digit} with ${calculated_stake} stake", "trade")
            await self._log(f"⚠️ THIS IS A REAL TRADE USING REAL MONEY!", "warning")
            
            # Place the real trade
            result = await deriv_api.buy_contract(contract_params)
            
            if result and "error" not in result:
                self.trades_placed += 1
                self.trade_cycle_count += 1
                self.last_trade_time = current_time
                
                # Track trades on current market for rotation
                self.trades_on_current_market += 1
                
                # Extract contract information
                contract_id = result.get("contract_id")
                
                await self._log(f"✅ REAL TRADE PLACED: #{self.trade_cycle_count} - Contract ID: {contract_id}", "success")
                await self._log(f"💰 Available Balance: ${deriv_api.get_available_balance():.2f} (Pending: ${deriv_api.get_pending_stakes():.2f})", "info")
                
                # Check for market rotation after trade placement
                if self.market_rotation_enabled and self.trades_on_current_market >= self.trades_per_market:
                    await self._rotate_market()
                
                # Process the outcome from the result
                if contract_id and "result" in result:
                    await self._process_trade_outcome(result, target_digit, calculated_stake)
                
            elif result and "error" in result:
                error_msg = result['error']['message']
                await self._log(f"❌ REAL TRADE FAILED: {error_msg}", "error")
                
                # Handle specific errors
                if "insufficient balance" in error_msg.lower():
                    await self._log("⚠️ INSUFFICIENT BALANCE - Stopping trading", "error")
                    await self.stop()
                elif "market closed" in error_msg.lower():
                    await self._log("⚠️ Market is closed", "warning")
                elif "invalid barrier" in error_msg.lower():
                    await self._log(f"⚠️ Invalid barrier {target_digit} for {self.active_symbol}", "warning")
                    
            else:
                await self._log("❌ REAL TRADE FAILED: No response from API", "error")
                    
        except Exception as e:
            await self._log(f"❌ REAL TRADE ERROR: {str(e)}", "error")

    async def _process_trade_outcome(self, trade_result: Dict[str, Any], predicted_digit: int, stake_amount: float):
        """Process the outcome of a completed trade"""
        try:
            result_type = trade_result.get("result", "UNKNOWN")
            profit = trade_result.get("profit", 0.0)
            contract_id = trade_result.get("contract_id", "Unknown")
            
            if result_type == "WIN":
                # TRADE WON
                self.successful_trades += 1
                self.last_trade_result = "WIN"
                
                await self._log(f"🎉 REAL TRADE WON: Contract {contract_id}. Profit: +${profit:.2f}", "success")
                await self._log(f"💰 Session P&L: ${deriv_api.get_session_pl():.2f}", "success")
                
                if self.martingale_enabled and self.martingale_current_step > 0:
                    total_recovered = stake_amount + profit
                    await self._log(f"🚀 MARTINGALE SUCCESS: Recovered ${total_recovered:.2f} after {self.martingale_current_step} losses!", "success")
                
                # Reset martingale on win
                self.martingale_current_step = 0
                self.consecutive_losses = 0
                self.current_target_digit = None  # Allow new trades
                
            elif result_type == "LOSS":
                # TRADE LOST
                loss = abs(profit)
                self.last_trade_result = "LOSS"
                self.consecutive_losses += 1
                
                await self._log(f"💸 REAL TRADE LOST: Contract {contract_id}. Loss: -${loss:.2f}", "error")
                await self._log(f"💰 Session P&L: ${deriv_api.get_session_pl():.2f}", "info")
                
                # Handle martingale on loss
                if self.martingale_enabled:
                    if self.martingale_current_step < self.martingale_max_steps:
                        self.martingale_current_step += 1
                        next_stake = self._calculate_martingale_stake()
                        await self._log(f"📈 MARTINGALE: Step {self.martingale_current_step}/{self.martingale_max_steps}. Next stake: ${next_stake}", "warning")
                        # Keep same target for martingale
                    else:
                        await self._log(f"⚠️ MARTINGALE MAX REACHED: Resetting after {self.martingale_max_steps} consecutive losses", "error")
                        self.martingale_current_step = 0
                        self.consecutive_losses = 0
                        self.current_target_digit = None
                else:
                    # No martingale, start fresh
                    self.current_target_digit = None
            
            else:
                await self._log(f"⏰ Trade result: {result_type} for contract {contract_id}", "info")
                        
        except Exception as e:
            await self._log(f"❌ Trade outcome processing error: {str(e)}", "error")

    async def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive bot statistics with fixed P&L calculations"""
        win_rate = (self.successful_trades / self.trades_placed * 100) if self.trades_placed > 0 else 0
        
        # FIXED: Use API's session P&L and balance information
        session_pnl = deriv_api.get_session_pl()
        current_balance = deriv_api.current_balance
        available_balance = deriv_api.get_available_balance()
        pending_stakes = deriv_api.get_pending_stakes()
        
        return {
            "user_id": self.user_id,
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "symbol": self.active_symbol,
            "strategy": "Enhanced Average Last 5 Digits (REAL TRADING)",
            "account_id": deriv_api.account_info.get('loginid') if deriv_api.account_info else None,
            "total_trades": self.trades_placed,
            "successful_trades": self.successful_trades,
            "win_rate": round(win_rate, 1),
            
            # FIXED: Proper P&L and balance reporting
            "session_pnl": round(session_pnl, 2),
            "current_balance": round(current_balance, 2),
            "available_balance": round(available_balance, 2),
            "pending_stakes": round(pending_stakes, 2),
            "session_start_balance": round(self.session_start_balance, 2),
            
            "current_target_digit": self.current_target_digit,
            "trade_cycle_count": self.trade_cycle_count,
            
            # Enhanced features
            "base_stake": self.base_stake,
            "current_stake": self.current_stake,
            "martingale": {
                "enabled": self.martingale_enabled,
                "multiplier": self.martingale_multiplier,
                "current_step": self.martingale_current_step,
                "max_steps": self.martingale_max_steps,
                "consecutive_losses": self.consecutive_losses
            },
            "take_profit": {
                "enabled": self.take_profit_enabled,
                "amount": self.take_profit_amount,
                "current_session": round(session_pnl, 2)
            },
            "stop_loss": {
                "enabled": self.stop_loss_enabled,
                "amount": self.stop_loss_amount,
                "current_session": round(session_pnl, 2)
            },
            
            # Market rotation info
            "market_rotation": {
                "enabled": self.market_rotation_enabled,
                "current_market": self.active_symbol,
                "trades_on_current": self.trades_on_current_market,
                "trades_per_market": self.trades_per_market,
                "available_markets": self.available_markets,
                "current_market_index": self.current_market_index,
                "next_market": self.available_markets[(self.current_market_index + 1) % len(self.available_markets)] if self.market_rotation_enabled else None
            },
            
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
            },
            "real_trading_warning": "⚠️ THIS BOT USES REAL MONEY - MONITOR CLOSELY!"
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

    async def _log(self, message: str, level: str = "info"):
        """Enhanced logging with console output for real trading"""
        timestamp = time.strftime("%H:%M:%S")
        prefix = {
            "info": "ℹ️",
            "success": "✅",
            "error": "❌",
            "warning": "⚠️",
            "trade": "💱"
        }.get(level, "")
        
        log_message = f"[{timestamp}] {prefix} {message}"
        
        # Print to console for real trading monitoring
        print(log_message)
        
        # Also log using Python logging
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "success" or level == "trade":
            logger.info(f"SUCCESS: {message}" if level == "success" else f"TRADE: {message}")
        else:
            logger.info(message)

    async def stop(self):
        """Stop the trading bot"""
        self.is_running = False
        await self._log("🛑 STOPPING REAL TRADING BOT", "warning")
        
        try:
            # Get final session stats
            session_pnl = deriv_api.get_session_pl()
            current_balance = deriv_api.current_balance
            pending_stakes = deriv_api.get_pending_stakes()
            
            await self._log("📊 FINAL SESSION SUMMARY:", "info")
            await self._log(f"   Total Trades: {self.trades_placed}", "info")
            await self._log(f"   Successful: {self.successful_trades}", "info")
            await self._log(f"   Win Rate: {(self.successful_trades/self.trades_placed*100) if self.trades_placed > 0 else 0:.1f}%", "info")
            await self._log(f"   Session P&L: ${session_pnl:.2f}", "success" if session_pnl >= 0 else "error")
            await self._log(f"   Final Balance: ${current_balance:.2f}", "info")
            
            if pending_stakes > 0:
                await self._log(f"   Pending Stakes: ${pending_stakes:.2f} (trades still active)", "warning")
                
            if self.martingale_enabled:
                await self._log(f"   Final Martingale Step: {self.martingale_current_step}/{self.martingale_max_steps}", "info")
                
        except Exception as e:
            await self._log(f"Error getting final stats: {str(e)}", "error")
        
        # Clean disconnect
        await deriv_api.disconnect()
        self.is_connected = False
        
        await self._log("✅ Real trading bot stopped successfully", "success")
        
        return {
            "status": "stopped", 
            "user_id": self.user_id,
            "final_balance": deriv_api.current_balance,
            "session_pnl": deriv_api.get_session_pl(),
            "pending_stakes": deriv_api.get_pending_stakes(),
            "trades_placed": self.trades_placed,
            "successful_trades": self.successful_trades
        }

    async def force_trade(self):
        """Force execute a trade immediately (for testing)"""
        if not self.is_running:
            return {"status": "error", "message": "Bot not running"}
        
        if len(self.last_5_digits) < 5:
            return {"status": "error", "message": "Need at least 5 digits collected"}
        
        await self._log("🔥 FORCING REAL TRADE EXECUTION", "trade")
        
        # Get the latest tick data
        if self.tick_history:
            latest_tick = self.tick_history[-1]
            await self._execute_enhanced_strategy(
                {"quote": latest_tick['quote'], "epoch": latest_tick['time']}, 
                latest_tick['digit']
            )
            
            return {
                "status": "success",
                "message": "Real force trade executed",
                "target_digit": self.current_target_digit,
                "stake_amount": self.current_stake,
                "user_id": self.user_id
            }
        
        return {"status": "error", "message": "No tick data available"}

    async def update_settings(self, **kwargs):
        """Update bot settings"""
        await self._log("🔧 Updating bot settings", "info")
        
        if "base_stake" in kwargs:
            new_stake = max(0.35, float(kwargs["base_stake"]))  # Deriv minimum
            self.base_stake = new_stake
            if self.martingale_current_step == 0:
                self.current_stake = new_stake
            await self._log(f"Base stake updated to ${new_stake}", "info")
                
        if "martingale_enabled" in kwargs:
            self.martingale_enabled = kwargs["martingale_enabled"]
            await self._log(f"Martingale {'enabled' if self.martingale_enabled else 'disabled'}", "warning" if self.martingale_enabled else "info")
            
        if "martingale_multiplier" in kwargs:
            self.martingale_multiplier = max(1.1, float(kwargs["martingale_multiplier"]))
            
        if "martingale_max_steps" in kwargs:
            self.martingale_max_steps = max(1, min(10, int(kwargs["martingale_max_steps"])))
            
        if "take_profit_enabled" in kwargs:
            self.take_profit_enabled = kwargs["take_profit_enabled"]
            
        if "take_profit_amount" in kwargs:
            self.take_profit_amount = float(kwargs["take_profit_amount"])
            
        if "stop_loss_enabled" in kwargs:
            self.stop_loss_enabled = kwargs["stop_loss_enabled"]
            
        if "stop_loss_amount" in kwargs:
            self.stop_loss_amount = float(kwargs["stop_loss_amount"])
            
        # Market rotation settings
        if "market_rotation_enabled" in kwargs:
            self.market_rotation_enabled = kwargs["market_rotation_enabled"]
            await self._log(f"Market rotation {'enabled' if self.market_rotation_enabled else 'disabled'}", "info")
            
        if "trades_per_market" in kwargs:
            self.trades_per_market = max(1, min(20, int(kwargs["trades_per_market"])))
            await self._log(f"Trades per market updated to {self.trades_per_market}", "info")
            
        if "available_markets" in kwargs:
            new_markets = kwargs["available_markets"]
            if isinstance(new_markets, list) and all(isinstance(m, str) for m in new_markets):
                self.available_markets = new_markets
                # Reset to first market if current market not in new list
                if self.active_symbol not in self.available_markets:
                    self.current_market_index = 0
                else:
                    self.current_market_index = self.available_markets.index(self.active_symbol)
                await self._log(f"Available markets updated: {', '.join(new_markets)}", "info")
            
        await self._log("✅ Settings updated successfully", "success")
        
        return {"status": "settings_updated"}

# User bot management
user_bots = {}

def get_user_bot(user_id: str) -> RealTradingBot:
    """Get or create user-specific bot instance"""
    if user_id not in user_bots:
        user_bots[user_id] = RealTradingBot(user_id)
    return user_bots[user_id]

def cleanup_inactive_bots():
    """Clean up inactive bot instances"""
    inactive_users = [uid for uid, bot in user_bots.items() if not bot.is_running]
    for uid in inactive_users:
        del user_bots[uid]

def validate_martingale_settings(multiplier: float, max_steps: int, base_stake: float, balance: float) -> Dict[str, Any]:
    """Validate martingale settings and calculate risk"""
    total_loss = sum(base_stake * (multiplier ** i) for i in range(max_steps + 1))
    loss_percentage = (total_loss / balance * 100) if balance > 0 else 100
    
    return {
        "valid": loss_percentage <= 50,  # Don't allow more than 50% risk
        "max_loss": total_loss,
        "loss_percentage": loss_percentage,
        "message": f"Max potential loss: ${total_loss:.2f} ({loss_percentage:.1f}% of balance)"
    }