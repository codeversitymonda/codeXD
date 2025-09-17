from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from typing import Optional
import asyncio
import uuid
import hashlib

# Import enhanced trading components
try:
    from enhanced_trading_bot import get_user_bot, cleanup_inactive_bots, validate_martingale_settings
    from deriv_api import deriv_api
    
    print("✅ Enhanced trading bot loaded successfully")
except ImportError as e:
    print(f"⚠️ Import error: {e}")
    print("Using mock implementations for testing...")
    
    # Enhanced mock classes
    class MockEnhancedTradingBot:
        def __init__(self, user_id=None):
            self.user_id = user_id or str(uuid.uuid4())
            self.is_running = False
            self.mock_stats = {
                "user_id": self.user_id,
                "is_running": False,
                "is_connected": False,
                "symbol": None,
                "strategy": "Enhanced Average Last 5 Digits",
                "total_trades": 0,
                "successful_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "daily_pnl": 0.0,
                "session_pnl": 0.0,
                "current_balance": 1000.0,
                "current_target_digit": None,
                "trade_cycle_count": 0,
                "base_stake": 1.79,
                "current_stake": 1.79,
                "martingale": {
                    "enabled": False,
                    "multiplier": 2.0,
                    "current_step": 0,
                    "max_steps": 5,
                    "consecutive_losses": 0
                },
                "take_profit": {
                    "enabled": False,
                    "amount": 50.0,
                    "current_session": 0.0
                },
                "stop_loss": {
                    "enabled": False,
                    "amount": -25.0,
                    "current_session": 0.0
                },
                "market_rotation": {
                    "enabled": False,
                    "current_market": "R_100",
                    "trades_on_current": 0,
                    "trades_per_market": 3,
                    "available_markets": ['R_10', 'R_25', 'R_50', 'R_75', 'R_100']
                },
                "tick_analysis": {
                    "total_ticks_analyzed": 0,
                    "digit_frequencies": {str(i): 0 for i in range(10)},
                    "recent_ticks": [],
                    "last_5_digits": [],
                    "last_5_calculation": {
                        "digits_collected": 0,
                        "digits": [],
                        "ready_to_trade": False
                    }
                },
                "uptime_minutes": 0,
                "connection_status": {
                    "connected": False,
                    "connection_attempts": 0,
                    "max_attempts": 3
                }
            }

        async def start(self, symbol, token, **kwargs):
            self.is_running = True
            self.mock_stats["is_running"] = True
            self.mock_stats["is_connected"] = True
            self.mock_stats["symbol"] = symbol
            
            # Update enhanced features
            self.mock_stats["martingale"]["enabled"] = kwargs.get('martingale_enabled', False)
            self.mock_stats["take_profit"]["enabled"] = kwargs.get('take_profit_enabled', False)
            self.mock_stats["stop_loss"]["enabled"] = kwargs.get('stop_loss_enabled', False)
            self.mock_stats["market_rotation"]["enabled"] = kwargs.get('auto_market_rotation', False)
            
            return {
                "status": "started", 
                "symbol": symbol, 
                "strategy": "enhanced_digit_differs_average", 
                "user_id": self.user_id,
                "features": {
                    "martingale": self.mock_stats["martingale"]["enabled"],
                    "take_profit": self.mock_stats["take_profit"]["enabled"],
                    "stop_loss": self.mock_stats["stop_loss"]["enabled"],
                    "auto_rotation": self.mock_stats["market_rotation"]["enabled"]
                }
            }

        async def stop(self):
            self.is_running = False
            self.mock_stats["is_running"] = False
            self.mock_stats["is_connected"] = False
            return {"status": "stopped", "user_id": self.user_id, "session_stats": self.mock_stats}

        def reset_data(self):
            self.mock_stats["total_trades"] = 0
            self.mock_stats["successful_trades"] = 0
            self.mock_stats["total_pnl"] = 0.0
            self.mock_stats["daily_pnl"] = 0.0
            self.mock_stats["session_pnl"] = 0.0
            self.mock_stats["martingale"]["current_step"] = 0
            self.mock_stats["martingale"]["consecutive_losses"] = 0
            self.mock_stats["current_stake"] = self.mock_stats["base_stake"]
            return {"status": "success", "message": "All data and systems have been reset", "user_id": self.user_id}

        async def get_statistics(self):
            if self.is_running:
                import random
                # Simulate some enhanced activity
                self.mock_stats["total_trades"] = min(self.mock_stats["total_trades"] + 1, 50)
                self.mock_stats["uptime_minutes"] += 0.5
                
                # Simulate martingale progression
                if self.mock_stats["martingale"]["enabled"] and random.random() < 0.3:
                    self.mock_stats["martingale"]["current_step"] = min(
                        self.mock_stats["martingale"]["current_step"] + 1, 
                        self.mock_stats["martingale"]["max_steps"]
                    )
                    multiplier = self.mock_stats["martingale"]["multiplier"]
                    step = self.mock_stats["martingale"]["current_step"]
                    self.mock_stats["current_stake"] = self.mock_stats["base_stake"] * (multiplier ** step)
                
            return self.mock_stats

        async def force_trade(self):
            if not self.is_running:
                return {"status": "error", "message": "Bot not running"}
            
            return {
                "status": "success", 
                "message": "Enhanced force trade executed",
                "target_digit": 5,
                "stake_amount": self.mock_stats["current_stake"],
                "martingale_step": self.mock_stats["martingale"]["current_step"],
                "user_id": self.user_id
            }

        async def update_settings(self, **kwargs):
            if "base_stake" in kwargs:
                self.mock_stats["base_stake"] = kwargs["base_stake"]
                if self.mock_stats["martingale"]["current_step"] == 0:
                    self.mock_stats["current_stake"] = kwargs["base_stake"]
            
            if "martingale_enabled" in kwargs:
                self.mock_stats["martingale"]["enabled"] = kwargs["martingale_enabled"]
            if "martingale_multiplier" in kwargs:
                self.mock_stats["martingale"]["multiplier"] = kwargs["martingale_multiplier"]
            if "martingale_max_steps" in kwargs:
                self.mock_stats["martingale"]["max_steps"] = kwargs["martingale_max_steps"]
                
            if "take_profit_enabled" in kwargs:
                self.mock_stats["take_profit"]["enabled"] = kwargs["take_profit_enabled"]
            if "take_profit_amount" in kwargs:
                self.mock_stats["take_profit"]["amount"] = kwargs["take_profit_amount"]
                
            if "stop_loss_enabled" in kwargs:
                self.mock_stats["stop_loss"]["enabled"] = kwargs["stop_loss_enabled"]
            if "stop_loss_amount" in kwargs:
                self.mock_stats["stop_loss"]["amount"] = kwargs["stop_loss_amount"]
                
            if "auto_market_rotation" in kwargs:
                self.mock_stats["market_rotation"]["enabled"] = kwargs["auto_market_rotation"]
                
            return {"status": "settings_updated"}

    # Mock functions
    mock_user_bots = {}
    
    def get_user_bot(user_id: str):
        if user_id not in mock_user_bots:
            mock_user_bots[user_id] = MockEnhancedTradingBot(user_id)
        return mock_user_bots[user_id]
    
    def cleanup_inactive_bots():
        pass
    
    def validate_martingale_settings(multiplier, max_steps, base_stake, balance):
        total_loss = sum(base_stake * (multiplier ** i) for i in range(max_steps + 1))
        loss_percentage = (total_loss / balance * 100) if balance > 0 else 100
        
        return {
            "valid": loss_percentage <= 50,
            "max_loss": total_loss,
            "loss_percentage": loss_percentage,
            "message": f"Max potential loss: ${total_loss:.2f} ({loss_percentage:.1f}% of balance)"
        }

# Enhanced FastAPI app
app = FastAPI(title="Enhanced Deriv Trading Bot API - Martingale & Risk Management")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enhanced request models
class EnhancedBotStartRequest(BaseModel):
    symbol: Optional[str] = "R_100"
    token: str
    base_stake: Optional[float] = 1.79
    duration: Optional[int] = 5
    
    # Martingale settings
    martingale_enabled: Optional[bool] = False
    martingale_multiplier: Optional[float] = 2.0
    martingale_max_steps: Optional[int] = 5
    
    # Take profit / Stop loss
    take_profit_enabled: Optional[bool] = False
    take_profit_amount: Optional[float] = 50.0
    stop_loss_enabled: Optional[bool] = False
    stop_loss_amount: Optional[float] = -25.0
    
    # Market rotation
    auto_market_rotation: Optional[bool] = False
    trades_per_market: Optional[int] = 3
    
    @validator('martingale_multiplier')
    def validate_multiplier(cls, v):
        if v < 1.1 or v > 5.0:
            raise ValueError('Martingale multiplier must be between 1.1 and 5.0')
        return v
    
    @validator('martingale_max_steps')
    def validate_max_steps(cls, v):
        if v < 1 or v > 10:
            raise ValueError('Martingale max steps must be between 1 and 10')
        return v
    
    @validator('base_stake')
    def validate_stake(cls, v):
        if v < 0.35 or v > 1000:
            raise ValueError('Base stake must be between $0.35 and $1000')
        return v

class EnhancedSettingsRequest(BaseModel):
    base_stake: Optional[float] = None
    trade_cooldown: Optional[int] = None
    daily_loss_limit: Optional[float] = None
    
    # Martingale settings
    martingale_enabled: Optional[bool] = None
    martingale_multiplier: Optional[float] = None
    martingale_max_steps: Optional[int] = None
    
    # Take profit / Stop loss
    take_profit_enabled: Optional[bool] = None
    take_profit_amount: Optional[float] = None
    stop_loss_enabled: Optional[bool] = None
    stop_loss_amount: Optional[float] = None
    
    # Market rotation
    auto_market_rotation: Optional[bool] = None
    trades_per_market: Optional[int] = None
    
    @validator('martingale_multiplier')
    def validate_multiplier(cls, v):
        if v is not None and (v < 1.1 or v > 5.0):
            raise ValueError('Martingale multiplier must be between 1.1 and 5.0')
        return v

class MartingaleValidationRequest(BaseModel):
    multiplier: float
    max_steps: int
    base_stake: float
    current_balance: float

# Utility functions
def generate_user_id(user_agent: str = None, ip: str = None, token: str = None) -> str:
    """Generate a consistent user ID"""
    identifier_string = f"{user_agent or 'unknown'}:{ip or 'unknown'}:{token[:10] if token else 'notoken'}"
    return hashlib.md5(identifier_string.encode()).hexdigest()[:12]

def get_user_id_from_headers(user_agent: Optional[str] = None, x_forwarded_for: Optional[str] = None, x_user_session: Optional[str] = None) -> str:
    """Extract or generate user ID from request headers"""
    if x_user_session:
        return x_user_session[:12]
    return generate_user_id(user_agent, x_forwarded_for)

# Enhanced API Routes
@app.get("/")
async def root():
    return {
        "message": "Enhanced Average Last 5 Digits Trading Bot API", 
        "status": "running",
        "version": "3.0",
        "strategy": "Enhanced Average Last 5 Digits → DIGITDIFF",
        "features": [
            "martingale_system", 
            "take_profit_stop_loss", 
            "auto_market_rotation", 
            "enhanced_risk_management",
            "user_isolation",
            "real_time_monitoring"
        ],
        "risk_warning": "⚠️ Martingale strategies carry high risk of substantial losses. Trade responsibly."
    }

@app.post("/start")
async def start_enhanced_bot(request: EnhancedBotStartRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        # Get user-specific bot instance
        trading_bot = get_user_bot(user_id)
        
        # Validate martingale settings if enabled
        if request.martingale_enabled:
            # Use default balance if not available
            current_balance = getattr(trading_bot, 'current_balance', 1000.0)
            validation = validate_martingale_settings(
                request.martingale_multiplier,
                request.martingale_max_steps,
                request.base_stake,
                current_balance
            )
            
            if not validation["valid"]:
                return {
                    "status": "error",
                    "message": f"Martingale validation failed: {validation['message']}",
                    "validation": validation
                }
        
        # Start the enhanced bot
        result = await trading_bot.start(
            symbol=request.symbol,
            token=request.token,
            base_stake=request.base_stake,
            duration=request.duration,
            martingale_enabled=request.martingale_enabled,
            martingale_multiplier=request.martingale_multiplier,
            martingale_max_steps=request.martingale_max_steps,
            take_profit_enabled=request.take_profit_enabled,
            take_profit_amount=request.take_profit_amount,
            stop_loss_enabled=request.stop_loss_enabled,
            stop_loss_amount=request.stop_loss_amount,
            auto_market_rotation=request.auto_market_rotation,
            trades_per_market=request.trades_per_market
        )
        
        return result
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start enhanced bot: {str(e)}")

@app.post("/stop")
async def stop_enhanced_bot(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        result = await trading_bot.stop()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop bot: {str(e)}")

@app.get("/statistics")
async def get_enhanced_statistics(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        return await trading_bot.get_statistics()
    except Exception as e:
        # Return enhanced default stats
        return {
            "user_id": user_id,
            "is_running": False,
            "is_connected": False,
            "symbol": None,
            "strategy": "Enhanced Average Last 5 Digits",
            "total_trades": 0,
            "successful_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "daily_pnl": 0.0,
            "session_pnl": 0.0,
            "current_balance": 0.0,
            "current_target_digit": None,
            "trade_cycle_count": 0,
            "base_stake": 1.79,
            "current_stake": 1.79,
            "martingale": {
                "enabled": False,
                "multiplier": 2.0,
                "current_step": 0,
                "max_steps": 5,
                "consecutive_losses": 0
            },
            "take_profit": {
                "enabled": False,
                "amount": 50.0,
                "current_session": 0.0
            },
            "stop_loss": {
                "enabled": False,
                "amount": -25.0,
                "current_session": 0.0
            },
            "market_rotation": {
                "enabled": False,
                "current_market": None,
                "trades_on_current": 0,
                "trades_per_market": 3,
                "available_markets": ['R_10', 'R_25', 'R_50', 'R_75', 'R_100']
            },
            "tick_analysis": {
                "total_ticks_analyzed": 0,
                "digit_frequencies": {},
                "recent_ticks": [],
                "last_5_digits": [],
                "last_5_calculation": {
                    "digits_collected": 0,
                    "digits": [],
                    "ready_to_trade": False
                }
            },
            "uptime_minutes": 0,
            "connection_status": {
                "connected": False,
                "connection_attempts": 0,
                "max_attempts": 3
            },
            "error": str(e)
        }

@app.post("/force-trade")
async def execute_enhanced_force_trade(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        return await trading_bot.force_trade()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute enhanced trade: {str(e)}")

@app.post("/update-settings")
async def update_enhanced_settings(settings: EnhancedSettingsRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        settings_dict = settings.dict(exclude_none=True)
        
        # Validate martingale settings if provided
        if any(k.startswith('martingale_') for k in settings_dict.keys()) and settings_dict.get('martingale_enabled'):
            current_stats = await trading_bot.get_statistics()
            validation = validate_martingale_settings(
                settings_dict.get('martingale_multiplier', current_stats.get('martingale', {}).get('multiplier', 2.0)),
                settings_dict.get('martingale_max_steps', current_stats.get('martingale', {}).get('max_steps', 5)),
                settings_dict.get('base_stake', current_stats.get('base_stake', 1.79)),
                current_stats.get('current_balance', 1000.0)
            )
            
            if not validation["valid"]:
                return {
                    "status": "error",
                    "message": f"Martingale validation failed: {validation['message']}",
                    "validation": validation
                }
        
        await trading_bot.update_settings(**settings_dict)
        
        return {
            "status": "settings_updated", 
            "updated": settings_dict, 
            "user_id": user_id,
            "message": "Enhanced settings updated successfully"
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update enhanced settings: {str(e)}")

@app.post("/reset")
async def reset_enhanced_bot_data(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        result = trading_bot.reset_data()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset enhanced data: {str(e)}")

# New enhanced endpoints
@app.post("/validate-martingale")
async def validate_martingale_risk(request: MartingaleValidationRequest):
    """Validate martingale settings and calculate risk metrics"""
    try:
        validation = validate_martingale_settings(
            request.multiplier,
            request.max_steps,
            request.base_stake,
            request.current_balance
        )
        
        return {
            "status": "success",
            "validation": validation,
            "recommendations": {
                "safe_max_steps": max(1, int(request.current_balance * 0.1 / request.base_stake)),
                "safe_multiplier_range": "1.5 - 2.5",
                "recommended_base_stake": min(request.base_stake, request.current_balance * 0.01)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")

@app.get("/markets")
async def get_available_markets():
    """Get available markets for trading"""
    return {
        "markets": ['R_10', 'R_25', 'R_50', 'R_75', 'R_100'],
        "descriptions": {
            "R_10": "Rise/Fall - 10% volatility",
            "R_25": "Rise/Fall - 25% volatility", 
            "R_50": "Rise/Fall - 50% volatility",
            "R_75": "Rise/Fall - 75% volatility",
            "R_100": "Rise/Fall - 100% volatility"
        },
        "recommended_for_beginners": ["R_10", "R_25"],
        "high_volatility": ["R_75", "R_100"]
    }

@app.get("/risk-calculator")
async def calculate_risk_metrics(base_stake: float, multiplier: float, max_steps: int, balance: float):
    """Calculate detailed risk metrics for martingale strategy"""
    try:
        if balance <= 0:
            raise HTTPException(status_code=400, detail="Balance must be positive")
        
        # Calculate step-by-step progression
        progression = []
        total_risk = 0
        current_stake = base_stake
        
        for step in range(max_steps + 1):
            total_risk += current_stake
            progression.append({
                "step": step,
                "stake": round(current_stake, 2),
                "cumulative_risk": round(total_risk, 2),
                "percentage_of_balance": round((total_risk / balance) * 100, 2)
            })
            current_stake *= multiplier
        
        risk_level = "LOW" if total_risk/balance < 0.1 else "MEDIUM" if total_risk/balance < 0.3 else "HIGH" if total_risk/balance < 0.5 else "EXTREME"
        
        return {
            "total_risk": round(total_risk, 2),
            "risk_percentage": round((total_risk / balance) * 100, 2),
            "risk_level": risk_level,
            "progression": progression,
            "break_even_win_rate": round(100 / multiplier, 2),
            "warnings": [
                "Martingale strategies can lead to rapid capital depletion",
                "Past performance does not guarantee future results",
                "Never risk more than you can afford to lose"
            ] if risk_level in ["HIGH", "EXTREME"] else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk calculation failed: {str(e)}")

@app.get("/session-summary/{user_id}")
async def get_session_summary(user_id: str):
    """Get detailed session summary for a user"""
    try:
        trading_bot = get_user_bot(user_id)
        stats = await trading_bot.get_statistics()
        
        return {
            "user_id": user_id,
            "session_active": stats.get("is_running", False),
            "duration_minutes": stats.get("uptime_minutes", 0),
            "performance": {
                "total_trades": stats.get("total_trades", 0),
                "win_rate": stats.get("win_rate", 0),
                "session_pnl": stats.get("session_pnl", 0),
                "total_pnl": stats.get("total_pnl", 0)
            },
            "current_state": {
                "market": stats.get("symbol"),
                "current_stake": stats.get("current_stake", 0),
                "martingale_step": stats.get("martingale", {}).get("current_step", 0),
                "target_digit": stats.get("current_target_digit")
            },
            "risk_metrics": {
                "balance": stats.get("current_balance", 0),
                "daily_pnl": stats.get("daily_pnl", 0),
                "session_risk_percentage": round((abs(stats.get("session_pnl", 0)) / max(stats.get("current_balance", 1), 1)) * 100, 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session summary: {str(e)}")

# Legacy endpoints for backward compatibility
@app.get("/api/status")
async def legacy_get_status(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    return await get_enhanced_statistics(user_agent, x_forwarded_for, x_user_session)

@app.post("/api/start-bot")
async def legacy_start_bot(request: EnhancedBotStartRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    return await start_enhanced_bot(request, user_agent, x_forwarded_for, x_user_session)

@app.post("/api/stop-bot")
async def legacy_stop_bot(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    return await stop_enhanced_bot(user_agent, x_forwarded_for, x_user_session)

@app.get("/api/user-info")
async def get_enhanced_user_info(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    return {
        "user_id": user_id,
        "session_info": {
            "user_agent_hash": hashlib.md5((user_agent or "").encode()).hexdigest()[:8],
            "ip_hash": hashlib.md5((x_forwarded_for or "").encode()).hexdigest()[:8] if x_forwarded_for else None,
            "custom_session": x_user_session is not None
        },
        "features_available": [
            "martingale_system",
            "take_profit_stop_loss", 
            "auto_market_rotation",
            "enhanced_risk_management"
        ]
    }

@app.post("/api/cleanup")
async def cleanup_inactive_sessions():
    try:
        cleanup_inactive_bots()
        return {"status": "success", "message": "Inactive enhanced sessions cleaned up"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# Health check with enhanced features
@app.get("/health")
async def enhanced_health_check():
    return {
        "status": "healthy",
        "bot_available": True,
        "api_available": True,
        "strategy": "Enhanced Average Last 5 Digits",
        "version": "3.0",
        "features": {
            "martingale_system": True,
            "take_profit_stop_loss": True,
            "auto_market_rotation": True,
            "enhanced_risk_management": True,
            "user_isolation": True,
            "real_time_monitoring": True
        },
        "risk_warning": "⚠️ Enhanced features include high-risk strategies. Trade responsibly."
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Enhanced Average Last 5 Digits Trading Bot API...")
    print("🔥 NEW FEATURES:")
    print("   • Martingale System with Risk Validation")
    print("   • Take Profit & Stop Loss Automation")
    print("   • Auto Market Rotation (3 trades per market)")
    print("   • Enhanced Risk Management & Warnings")
    print("🔒 Each user gets isolated bot instances")
    print("📊 Real-time risk monitoring and validation")
    print("⚠️  WARNING: Martingale strategies carry high risk!")
    print("🌐 Frontend: http://localhost:8000")
    print("📋 API Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")