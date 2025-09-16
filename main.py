from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio

# Import your actual trading components
try:
    from enhanced_trading_bot import DigitDiffersBot
    from deriv_api import deriv_api
    
    # Create global instances
    trading_bot = DigitDiffersBot()
    
    print("✓ Enhanced trading bot loaded successfully")
except ImportError as e:
    print(f"⚠️ Import error: {e}")
    print("Using mock implementations for testing...")
    
    # Fallback mock classes if imports fail
    class MockTradingBot:
        def __init__(self):
            self.is_running = False
            self.mock_stats = {
                "is_running": False,
                "symbol": None,
                "total_trades": 0,
                "successful_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "daily_pnl": 0.0,
                "current_balance": 1000.0,
                "rarest_digits": [3, 7, 9],
                "tick_analysis": {
                    "total_ticks_analyzed": 0,
                    "digit_frequencies": {str(i): 0 for i in range(10)},
                    "recent_ticks": []
                },
                "uptime_minutes": 0
            }

        async def start(self, symbol, token, **kwargs):
            self.is_running = True
            self.mock_stats["is_running"] = True
            self.mock_stats["symbol"] = symbol
            return {"status": "started", "symbol": symbol, "strategy": "digit_differs"}

        async def stop(self):
            self.is_running = False
            self.mock_stats["is_running"] = False
            return {"status": "stopped"}

        async def get_statistics(self):
            if self.is_running:
                # Simulate some activity
                self.mock_stats["total_trades"] = min(self.mock_stats["total_trades"] + 1, 50)
                self.mock_stats["tick_analysis"]["total_ticks_analyzed"] += 5
                self.mock_stats["uptime_minutes"] += 0.5
            return self.mock_stats

        async def force_trade(self):
            if not self.is_running:
                return {"status": "error", "message": "Bot not running"}
            return {"status": "success", "target_digit": 3, "message": "Mock trade executed"}

        async def update_settings(self, **kwargs):
            return {"status": "settings_updated"}

    class MockDerivAPI:
        connected = False
        
        @staticmethod
        async def connect(token: str):
            MockDerivAPI.connected = True
            return {"message": "Mock connection successful"}

    trading_bot = MockTradingBot()
    deriv_api = MockDerivAPI()

# FastAPI app
app = FastAPI(title="Enhanced Deriv Trading Bot API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
class BotStartRequest(BaseModel):
    symbol: Optional[str] = "R_100"
    strategy: str = "digit_differs"
    token: str
    stake: Optional[float] = 1.0

class TradeRequest(BaseModel):
    symbol: str
    amount: float
    contract_type: str
    duration: int
    duration_unit: str = "minutes"
    token: str

class SettingsRequest(BaseModel):
    stake: Optional[float] = None
    trade_cooldown: Optional[int] = None
    daily_loss_limit: Optional[float] = None

# Routes
@app.get("/")
async def root():
    return {
        "message": "Enhanced Deriv Trading Bot API", 
        "status": "running",
        "version": "2.0",
        "bot_type": "Digit Differs Strategy"
    }

@app.post("/api/connect")
async def connect(request: dict):
    token = request.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")
    
    try:
        result = await deriv_api.connect(token)
        return {"status": "connected", "details": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")

@app.post("/api/start-bot")
async def start_bot(request: BotStartRequest):
    try:
        result = await trading_bot.start(
            symbol=request.symbol,
            token=request.token,
            stake=request.stake or 1.0
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {str(e)}")

@app.post("/api/stop-bot")
async def stop_bot():
    try:
        result = await trading_bot.stop()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop bot: {str(e)}")

@app.get("/api/status")
async def get_status():
    """Legacy endpoint for backward compatibility"""
    try:
        stats = await trading_bot.get_statistics()
        return {
            "bot_running": stats.get("is_running", False),
            "api_connected": getattr(deriv_api, 'connected', False),
            "active_symbol": stats.get("symbol"),
            "active_strategy": "digit_differs"
        }
    except Exception as e:
        return {
            "bot_running": False,
            "api_connected": False,
            "active_symbol": None,
            "active_strategy": None,
            "error": str(e)
        }

@app.get("/api/bot-stats")
async def get_bot_statistics():
    """New enhanced statistics endpoint"""
    try:
        return await trading_bot.get_statistics()
    except Exception as e:
        # Return default stats if bot not available
        return {
            "is_running": False,
            "symbol": None,
            "total_trades": 0,
            "successful_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "daily_pnl": 0.0,
            "current_balance": 0.0,
            "rarest_digits": [],
            "tick_analysis": {
                "total_ticks_analyzed": 0,
                "digit_frequencies": {},
                "recent_ticks": []
            },
            "uptime_minutes": 0,
            "error": str(e)
        }

@app.post("/api/force-trade")
async def execute_force_trade():
    """Execute manual trade"""
    try:
        return await trading_bot.force_trade()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute trade: {str(e)}")

@app.post("/api/update-settings")
async def update_bot_settings(settings: SettingsRequest):
    """Update bot settings"""
    try:
        settings_dict = settings.dict(exclude_none=True)
        await trading_bot.update_settings(**settings_dict)
        return {"status": "settings_updated", "updated": settings_dict}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

@app.post("/api/trade")
async def place_trade(request: TradeRequest):
    """Place individual trade"""
    try:
        await deriv_api.connect(request.token)
        contract_data = {
            "symbol": request.symbol,
            "amount": request.amount,
            "contract_type": request.contract_type,
            "duration": request.duration,
            "duration_unit": request.duration_unit
        }
        result = await deriv_api.buy_contract(contract_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trade failed: {str(e)}")

@app.get("/api/balance")
async def get_balance(token: str):
    """Get account balance"""
    try:
        await deriv_api.connect(token)
        return await deriv_api.get_balance()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")

@app.get("/api/market-analysis")
async def market_analysis():
    """Market analysis endpoint"""
    return {
        "market": "neutral", 
        "analysis": "Digit frequency analysis in progress.",
        "strategy": "DIGITDIFF on rarest digits",
        "recommendation": "Monitor digit distribution patterns"
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "bot_available": hasattr(trading_bot, 'get_statistics'),
        "api_available": hasattr(deriv_api, 'connect')
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Enhanced Deriv Trading Bot API...")
    print("📊 Strategy: Digit Differs (DIGITDIFF contracts)")
    print("🔗 Frontend: http://localhost:8000")
    print("📋 API Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")