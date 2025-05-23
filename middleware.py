import json
import logging
import os
from flask import Flask, request, jsonify
from datetime import datetime
import requests
import hashlib
import pyotp
from smartapi.smartConnect import SmartConnect

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class AngelOneTrader:
    def __init__(self):
        # Angel One API credentials - will be loaded from environment variables
        self.api_key = os.getenv('ANGEL_API_KEY', 'YOUR_ANGEL_ONE_API_KEY')
        self.username = os.getenv('ANGEL_USERNAME', 'YOUR_ANGEL_ONE_USERNAME')
        self.password = os.getenv('ANGEL_PASSWORD', 'YOUR_ANGEL_ONE_PASSWORD')
        self.totp_key = os.getenv('ANGEL_TOTP_KEY', 'YOUR_ANGEL_ONE_TOTP_KEY')
        
        self.smart_api = None
        self.auth_token = None
        self.refresh_token = None
        self.feed_token = None
        
        # Trading parameters
        self.default_quantity = 1  # Default quantity to trade
        self.product_type = "MIS"  # MIS for intraday, CNC for delivery
        self.order_type = "MARKET"  # MARKET or LIMIT
        
    def login(self):
        """Login to Angel One API"""
        try:
            self.smart_api = SmartConnect(api_key=self.api_key)
            
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_key).now()
            
            # Login
            data = self.smart_api.generateSession(self.username, self.password, totp)
            
            if data['status']:
                self.auth_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = data['data']['feedToken']
                logger.info("Successfully logged in to Angel One")
                return True
            else:
                logger.error(f"Login failed: {data}")
                return False
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False
    
    def get_symbol_token(self, symbol, exchange="NSE"):
        """Get symbol token for the given symbol"""
        try:
            # This is a simplified example - in practice, you'd maintain a symbol master
            # or use Angel One's instrument list API
            symbol_map = {
                "NIFTY": "99926000",
                "BANKNIFTY": "99926009",
                "RELIANCE": "2885",
                "TCS": "11536",
                "INFY": "1594",
                "HDFCBANK": "1333",
                "ICICIBANK": "4963",
                "SBIN": "3045",
                "ITC": "424",
                "HINDUNILVR": "356",
                # Add more symbols as needed
            }
            
            return symbol_map.get(symbol.upper())
            
        except Exception as e:
            logger.error(f"Error getting symbol token: {str(e)}")
            return None
    
    def place_order(self, symbol, action, quantity=None, price=None):
        """Place order on Angel One"""
        try:
            if not self.smart_api or not self.auth_token:
                if not self.login():
                    return {"status": False, "message": "Login failed"}
            
            # Get symbol token
            symbol_token = self.get_symbol_token(symbol)
            if not symbol_token:
                return {"status": False, "message": f"Symbol token not found for {symbol}"}
            
            # Set quantity
            if not quantity:
                quantity = self.default_quantity
            
            # Determine transaction type
            transaction_type = "BUY" if action.upper() == "BUY" else "SELL"
            
            # Prepare order parameters
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": symbol_token,
                "transactiontype": transaction_type,
                "exchange": "NSE",
                "ordertype": self.order_type,
                "producttype": self.product_type,
                "duration": "DAY",
                "quantity": str(quantity)
            }
            
            # Add price for limit orders
            if self.order_type == "LIMIT" and price:
                order_params["price"] = str(price)
            
            # Place order
            order_response = self.smart_api.placeOrder(order_params)
            
            if order_response and order_response.get('status'):
                order_id = order_response['data']['orderid']
                logger.info(f"Order placed successfully: {order_id}")
                return {
                    "status": True, 
                    "message": f"Order placed: {transaction_type} {quantity} {symbol}",
                    "order_id": order_id
                }
            else:
                logger.error(f"Order placement failed: {order_response}")
                return {"status": False, "message": f"Order failed: {order_response}"}
                
        except Exception as e:
            logger.error(f"Order placement error: {str(e)}")
            return {"status": False, "message": f"Error: {str(e)}"}

# Initialize trader
trader = AngelOneTrader()

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        "message": "TradingView to Angel One Middleware",
        "status": "running",
        "endpoints": {
            "webhook": "/webhook",
            "status": "/status",
            "login": "/login",
            "test": "/test"
        }
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive webhook from TradingView"""
    try:
        # Get JSON data from TradingView
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400
        
        logger.info(f"Received webhook data: {data}")
        
        # Extract trading information
        action = data.get('action')  # BUY or SELL
        symbol = data.get('symbol', 'NIFTY')
        signal = data.get('signal')  # G_BOX, R_BOX, etc.
        price = data.get('price')
        message = data.get('message')
        
        # Validate required fields
        if not action or action not in ['BUY', 'SELL']:
            return jsonify({"status": "error", "message": "Invalid action"}), 400
        
        # Custom trading logic based on signal type
        quantity = get_quantity_for_signal(signal)
        
        # Log the trade attempt
        logger.info(f"Processing trade: {action} {quantity} {symbol} - Signal: {signal}")
        
        # Place order
        result = trader.place_order(symbol, action, quantity, price)
        
        # Prepare response
        response = {
            "status": "success" if result.get("status") else "error",
            "message": result.get("message"),
            "timestamp": datetime.now().isoformat(),
            "signal": signal,
            "action": action,
            "symbol": symbol,
            "quantity": quantity
        }
        
        if result.get("order_id"):
            response["order_id"] = result["order_id"]
        
        return jsonify(response), 200 if result.get("status") else 400
        
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def get_quantity_for_signal(signal):
    """Determine quantity based on signal type"""
    # Customize quantities based on your risk management
    signal_quantities = {
        "G_BOX": 1,      # Regular bullish signal
        "R_BOX": 1,      # Regular bearish signal  
        "2G_BOX": 2,     # Strong bullish - higher quantity
        "2R_BOX": 2,     # Strong bearish - higher quantity
        "1G_BOX": 1,     # Transition signals
        "1R_BOX": 1,
        "2GR_BOX": 1,
        "2RG_BOX": 1
    }
    
    return signal_quantities.get(signal, 1)  # Default quantity = 1

@app.route('/status', methods=['GET'])
def status():
    """Check middleware status"""
    return jsonify({
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "logged_in": trader.auth_token is not None,
        "api_key_configured": trader.api_key != 'YOUR_ANGEL_ONE_API_KEY',
        "environment": os.getenv('RAILWAY_ENVIRONMENT', 'development')
    })

@app.route('/login', methods=['POST'])
def manual_login():
    """Manually trigger login"""
    success = trader.login()
    return jsonify({
        "status": "success" if success else "error",
        "message": "Login successful" if success else "Login failed",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/test', methods=['POST'])
def test_order():
    """Test order placement"""
    try:
        data = request.get_json() or {}
        symbol = data.get('symbol', 'NIFTY')
        action = data.get('action', 'BUY')
        quantity = data.get('quantity', 1)
        
        result = trader.place_order(symbol, action, quantity)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"status": False, "message": str(e)})

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    # Login on startup
    logger.info("Starting TradingView to Angel One Middleware...")
    trader.login()
    
    # Run Flask app
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
