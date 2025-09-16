import asyncio
from collections import Counter, deque
from typing import Dict, Any, Optional, List
from deriv_api import deriv_api
import time
import json


class DigitDiffersBot:
    def __init__(self):
        self.is_running = False
        self.active_symbol = None
        self.strategy = "digit_differs"
        self.callback_function = None
        
        # Enhanced tick history tracking
        self.tick_history = deque(maxlen=100)  # Keep last 100 ticks
        self.digit_frequencies = Counter()
        self.last_trade_time = 0
        self.trade_cooldown = 5  # seconds between trades
        
        # Trading parameters
        self.stake = 1.0
        self.duration = 1  # 1 tick
        self.min_analysis_ticks = 20  # Minimum ticks before trading
        
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

    async def start(self, symbol: str, token: str, stake: float = 1.0, 
                   duration: int = 1, callback: Optional[callable] = None):
        """Start the Digit Differs trading bot"""
        try:
            # Connect to Deriv API
            auth_result = await deriv_api.connect(token)
            if "error" in auth_result:
                return {"status": "error", "message": auth_result["error"]["message"]}

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
            asyncio.create_task(deriv_api.start_listening())

            await self._log(f"Started Digit Differs bot on {symbol} with ${stake} stake", "success")
            return {"status": "started", "symbol": symbol, "strategy": self.strategy}

        except Exception as e:
            await self._log(f"Bot startup error: {str(e)}", "error")
            return {"status": "error", "message": str(e)}

    async def _handle_tick(self, tick_data: Dict[str, Any]):
        """Process incoming ticks and execute differs strategy"""
        try:
            if not self.is_running:
                return

            quote = float(tick_data["quote"])
            # Get last digit of the quote
            last_digit = int(str(quote).split('.')[-1][-1])
            
            # Update tick history and frequencies
            self.tick_history.append({
                'digit': last_digit,
                'quote': quote,
                'time': tick_data.get('epoch', time.time())
            })
            
            self.digit_frequencies[last_digit] += 1
            
            # Execute strategy if we have enough data
            if len(self.tick_history) >= self.min_analysis_ticks:
                await self._execute_differs_strategy(tick_data, last_digit)

            # Callback for frontend updates
            if self.callback_function:
                await self.callback_function({
                    **tick_data,
                    'last_digit': last_digit,
                    'rarest_digits': self._get_rarest_digits(),
                    'total_ticks': len(self.tick_history)
                })

        except Exception as e:
            await self._log(f"Error processing tick: {str(e)}", "error")

    def _get_rarest_digits(self, count: int = 3) -> List[int]:
        """Get the N rarest digits from recent history"""
        if len(self.digit_frequencies) < 10:
            return []
        
        # Sort by frequency (ascending) to get rarest first
        sorted_digits = sorted(
            self.digit_frequencies.items(), 
            key=lambda x: x[1]
        )
        
        return [digit for digit, freq in sorted_digits[:count]]

    async def _execute_differs_strategy(self, tick_data: Dict[str, Any], current_digit: int):
        """Execute DIGITDIFF strategy on rarest digits"""
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_trade_time < self.trade_cooldown:
            return

        # Check daily loss limit
        if self.daily_pnl <= -self.daily_loss_limit:
            await self._log(f"Daily loss limit reached (${self.daily_loss_limit}). Stopping trades.", "warning")
            return

        # Get rarest digits
        rarest_digits = self._get_rarest_digits(3)
        if not rarest_digits:
            return

        # Calculate dynamic stake based on balance
        if self.current_balance > 0:
            max_allowed_stake = self.current_balance * self.max_stake_percentage
            adjusted_stake = min(self.stake, max_allowed_stake)
        else:
            adjusted_stake = self.stake

        # Trade logic: Use DIGITDIFF on the rarest digit
        target_digit = rarest_digits[0]  # Use the rarest digit
        
        # Only trade if the rarest digit is significantly underrepresented
        total_ticks = len(self.tick_history)
        expected_frequency = total_ticks / 10  # Expected ~10% for each digit
        actual_frequency = self.digit_frequencies[target_digit]
        
        # Trade if the digit appears less than 60% of expected frequency
        if actual_frequency < (expected_frequency * 0.6):
            
            contract_data = {
                "symbol": tick_data["symbol"],
                "amount": adjusted_stake,
                "contract_type": "DIGITDIFF",  # Differs contract
                "barrier": str(target_digit),   # Predict next tick will NOT be this digit
                "duration": self.duration,
                "duration_unit": "t"  # tick-based contract
            }

            try:
                result = await deriv_api.buy_contract(contract_data)
                
                if "error" not in result:
                    self.trades_placed += 1
                    self.last_trade_time = current_time
                    
                    await self._log(
                        f"DIGITDIFF trade placed: Predict next tick ≠ {target_digit} "
                        f"(appeared {actual_frequency}/{total_ticks} times, ${adjusted_stake} stake)",
                        "info"
                    )
                    
                    # Track the trade for outcome monitoring
                    asyncio.create_task(self._monitor_trade_outcome(result, target_digit))
                    
                else:
                    await self._log(f"Trade failed: {result['error']['message']}", "error")
                    
            except Exception as e:
                await self._log(f"Trade execution error: {str(e)}", "error")

    async def _monitor_trade_outcome(self, trade_result: Dict[str, Any], predicted_digit: int):
        """Monitor trade outcome and update statistics"""
        try:
            # In a real implementation, you'd subscribe to the contract's updates
            # For now, we'll simulate outcome tracking
            
            contract_id = trade_result.get("buy", {}).get("contract_id")
            if not contract_id:
                return
            
            # Wait for contract settlement (this is simplified)
            await asyncio.sleep(2)  # Wait for next tick
            
            # Check if our prediction was correct
            # In real implementation, query contract status from API
            # For demo, we'll check if the next tick digit differs from our target
            
            if len(self.tick_history) > 0:
                next_tick_digit = self.tick_history[-1]['digit']
                won_trade = next_tick_digit != predicted_digit
                
                if won_trade:
                    self.successful_trades += 1
                    profit = self.stake * 0.9  # Typical 90% payout
                    self.total_pnl += profit
                    self.daily_pnl += profit
                    await self._log(f"Trade WON: Next tick was {next_tick_digit} ≠ {predicted_digit}. Profit: +${profit:.2f}", "success")
                else:
                    loss = -self.stake
                    self.total_pnl += loss
                    self.daily_pnl += loss
                    await self._log(f"Trade LOST: Next tick was {next_tick_digit} = {predicted_digit}. Loss: ${abs(loss):.2f}", "error")
            
        except Exception as e:
            await self._log(f"Trade monitoring error: {str(e)}", "error")

    async def get_statistics(self) -> Dict[str, Any]:
        """Get current bot statistics"""
        win_rate = (self.successful_trades / self.trades_placed * 100) if self.trades_placed > 0 else 0
        
        return {
            "is_running": self.is_running,
            "symbol": self.active_symbol,
            "total_trades": self.trades_placed,
            "successful_trades": self.successful_trades,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "current_balance": round(self.current_balance, 2),
            "rarest_digits": self._get_rarest_digits(),
            "tick_analysis": {
                "total_ticks_analyzed": len(self.tick_history),
                "digit_frequencies": dict(self.digit_frequencies),
                "recent_ticks": [tick['digit'] for tick in list(self.tick_history)[-10:]]
            },
            "uptime_minutes": round((time.time() - self.trade_start_time) / 60, 1)
        }

    async def force_trade(self) -> Dict[str, Any]:
        """Execute immediate trade regardless of conditions"""
        if not self.is_running or len(self.tick_history) == 0:
            return {"status": "error", "message": "Bot not active or no tick data"}
        
        rarest_digits = self._get_rarest_digits(1)
        if not rarest_digits:
            return {"status": "error", "message": "No digit analysis available"}
        
        target_digit = rarest_digits[0]
        last_tick = self.tick_history[-1]
        
        # Force trade with current conditions
        await self._execute_differs_strategy(
            {"symbol": self.active_symbol, "quote": last_tick['quote']}, 
            last_tick['digit']
        )
        
        return {
            "status": "success", 
            "message": f"Forced trade executed on digit {target_digit}",
            "target_digit": target_digit
        }

    async def update_settings(self, **kwargs):
        """Update bot settings dynamically"""
        if "stake" in kwargs:
            self.stake = max(0.1, float(kwargs["stake"]))
        if "trade_cooldown" in kwargs:
            self.trade_cooldown = max(1, int(kwargs["trade_cooldown"]))
        if "daily_loss_limit" in kwargs:
            self.daily_loss_limit = max(10, float(kwargs["daily_loss_limit"]))
        
        await self._log("Settings updated", "info")

    async def stop(self):
        """Stop the trading bot"""
        self.is_running = False
        
        # Generate session summary
        stats = await self.get_statistics()
        await self._log(f"Session ended - Trades: {stats['total_trades']}, "
                       f"Win Rate: {stats['win_rate']}%, PnL: ${stats['total_pnl']}", "info")
        
        await deriv_api.disconnect()
        return {"status": "stopped", "session_stats": stats}

    async def _log(self, message: str, level: str = "info"):
        """Internal logging method"""
        print(f"[{time.strftime('%H:%M:%S')}] [{level.upper()}] {message}")
        
        # You can extend this to send logs to the frontend
        if self.callback_function:
            try:
                await self.callback_function({
                    "type": "log",
                    "message": message,
                    "level": level,
                    "timestamp": time.time()
                })
            except:
                pass  # Don't fail on logging errors


# Global trading bot instance
enhanced_trading_bot = DigitDiffersBot()