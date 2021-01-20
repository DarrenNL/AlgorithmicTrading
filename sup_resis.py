import threading
import time
import datetime
import pandas as pd
import talib as ta
import numpy as np
import bisect
from math import floor

import alpaca_trade_api as tradeapi

# Import personal algorithm settings
from secrets import API_BASE_URL, API_KEY_ID, API_SECRET_KEY, ALL_STOCKS, PARAMETER_SETTINGS

class SupResis:
    def __init__(self):
        """
            Initalization, defines things to do at the start of the algorithm
        """
        self.alpaca = tradeapi.REST(API_KEY_ID, API_SECRET_KEY, API_BASE_URL, 'v2')
        
        # Universe selection
        self.allStocks = ALL_STOCKS

        # Strategy parameters
        self.params = PARAMETER_SETTINGS
        
        self.data = dict.fromkeys(self.allStocks,0)
        self.signals = dict.fromkeys(self.allStocks,0)
        self.target_position = dict.fromkeys(self.allStocks,0)
        
    def run(self):
        """
            A function to define things to do at every bar
        """
        # First cancel any existing orders so they don't impact our buying power
        orders = self.alpaca.list_orders(status='open')
        for order in orders:
            self.alpaca.cancel_order(order.id)
        
        # Wait for market to open
        print('Waiting for market to open...')
        tAMO = threading.Thread(target=self.awaitMarketOpen)
        tAMO.start()
        tAMO.join()
        print('Market opened.')
        
        # Rebalance the portfolio every minute, making necessary trades.
        while True:
            
            # Figure out when the market will close so we can prepare to sell beforehand.
            clock = self.alpaca.get_clock()
            closingTime = clock.next_close.replace(tzinfo=datetime.timezone.utc).timestamp()
            currTime = clock.timestamp.replace(tzinfo=datetime.timezone.utc).timestamp()
            self.timeToClose = closingTime - currTime
            
            if(self.timeToClose < (60 * 15)):
                # Close all positions when 15 minutes til market close.
                print('Market closing soon. Closing positions.')
                
                positions = self.alpaca.list_positions()
                for position in positions:
                    if (position.side == 'long'):
                        orderSide = 'sell'
                    else:
                        orderSide = 'buy'
                    qty = abs(int(float(position.qty)))
                    respSO = []
                    tSubmitOrder = threading.Thread(target=self.submitOrder(qty, position.symbol, orderSide, respSO))
                    tSubmitOrder.start()
                    tSubmitOrder.join()
                    
                #Run script again after market close for next trading day
                print('Sleeping until market close (15 minutes).')
                time.sleep(60*15)
            else:
                #Rebalance the portfolio
                tRunStrategy = threading.Thread(target=self.run_strategy)
                tRunStrategy.start()
                tRunStrategy.join()
                time.sleep(60*self.params['trade_freq'])

    def awaitMarketOpen(self):
        """
            Wait for market to open
        """
        isOpen = self.alpaca.get_clock().is_open
        while(not isOpen):
            clock = self.alpaca.get_clock()
            openingTime = clock.next_open.replace(tzinfo=datetime.timezone.utc).timestamp()
            currTime = clock.timestamp.replace(tzinfo=datetime.timezone.utc).timestamp()
            timeToOpen = int((openingTime - currTime) / 60)
            print(f'{timeToOpen} minutes till market open.')
            time.sleep(60)
            isOpen = self.alpaca.get_clock().is_open
    
    def run_strategy(self):
        """
            A function to define core strategy steps
        """
        orders = self.alpaca.list_orders(status='open')
        for order in orders:
            self.alpaca.cancel_order(order.id)
        
        self.get_data()
        self.generate_signals()
        self.generate_target_position()
        self.rebalance()

    def get_data(self):
        """
            A function that retrieves stock data and updates self.data
        """
        for stock in self.allStocks:
            bars = self.alpaca.get_barset(stock,self.params['indicator_freq'],self.params['indicator_lookback'])
            high = []
            low = []
            close = []
            for bar in bars[stock]:
                high.append(bar.h)
                low.append(bar.l)
                close.append(bar.c)
            self.data[stock] = dict([('high',np.array(high)),
                                    ('low',np.array(low)),
                                    ('close',np.array(close))])
            
    def generate_signals(self):
        """
            A function to define the signal generation from the main trading logic
        """
        for stock in self.allStocks:
            lower, upper = self.fibonacci_support(stock)
            ind2 = self.adx(stock)

            if lower == -1:
                self.signals[stock] =  -1
            elif upper == -1:
                self.signals[stock] =  1
            elif upper > 0.02 and lower > 0 and upper/lower > 3 and ind2 < 20:
                self.signals[stock] =  -1
            elif lower > 0.02 and upper > 0 and lower/upper > 3 and ind2 < 20:
                self.signals[stock] =  1
            else:
                self.signals[stock] =  self.signals[stock]

    def fibonacci_support(self,stock):
        """ 
            Computes the current Fibonnaci support and resistance levels. 
            Returns the distant of the last price point from both.
            Args:
                px (ndarray): input price array
            Returns:
                Tuple, distance from support and resistance levels.
        """
        px = self.data[stock]['close']
        def fibonacci_levels(px):
            return [min(px) + l*(max(px) - min(px)) for l in [0,0.236,0.382,0.5,0.618,1]]

        def find_interval(x, val):
            return (-1 if val < x[0] else 99) if val < x[0] or val > x[-1] \
                else  max(bisect.bisect_left(x,val)-1,0)

        last_price = px[-1]
        lower_dist = upper_dist = 0
        sups = fibonacci_levels(px[:-1])
        idx = find_interval(sups, last_price)

        if idx==-1:
            lower_dist = -1
            upper_dist = round(100.0*(sups[0]/last_price-1),2)
        elif idx==99:
            lower_dist = round(100.0*(last_price/sups[-1]-1),2)
            upper_dist = -1
        else:
            lower_dist = round(100.0*(last_price/sups[idx]-1),2)
            upper_dist = round(100.0*(sups[idx+1]/last_price-1),2)

        return lower_dist,upper_dist

    def adx(self,stock):
        """ 
            returns average directional index.
            Args:
                px (DataFrame): input price array with OHLC columns
                lookback (int): lookback window size
            Returns:
                Float, last value of the ADX.
        """
        px = self.data[stock]
        signal = ta.ADX(px['high'], px['low'], px['close'], timeperiod=self.params['ADX_period'])
        return signal[-1]

    def generate_target_position(self):
        """
            A function to define target portfolio
        """
        num_stocks = len(self.allStocks)
        weight = round(1.0/num_stocks,2)*self.params['leverage']*float(self.alpaca.get_account().portfolio_value)

        for stock in self.allStocks:
            if self.signals[stock] > self.params['buy_signal_threshold']:
                self.target_position[stock] = floor(weight/self.data[stock]['close'][-1])
            elif self.signals[stock] < self.params['sell_signal_threshold']:
                self.target_position[stock] = -floor(weight/self.data[stock]['close'][-1])
            else:
                self.target_position[stock] = 0

    def rebalance(self):
        """
            A function to rebalance - all execution logic goes here
        """
        
        # Create list of long and short stocks, then print out the lists
        self.long = []
        for stock in self.allStocks:
            if(self.target_position[stock] > 0):
                self.long.append(stock)
        print('We are taking a long position in : ' + str(self.long))
        
        current_portfolio = self.alpaca.list_positions()
        current_positions =  dict()
        for entity in current_portfolio:
            current_positions[entity.symbol] = int(float(entity.qty))
        for stock in self.allStocks:
            if self.target_position[stock] <= 0:
                if stock in current_positions:
                    tSO = threading.Thread(
                        target=self.alpaca.submit_order, 
                        args=[stock,current_positions[stock],'sell','market','day'])
                    tSO.start()
                    tSO.join()
            elif self.target_position[stock] > 0:
                if stock in current_positions:
                    if self.target_position[stock] > current_positions[stock]:
                        tSO = threading.Thread(
                            target=self.alpaca.submit_order, 
                            args=[stock,self.target_position[stock] - current_positions[stock],'buy','market','day'])
                        tSO.start()
                        tSO.join()
                    elif self.target_position[stock] < current_positions[stock]:
                        tSO = threading.Thread(
                            target=self.alpaca.submit_order, 
                            args=[stock,current_positions[stock] - self.target_position[stock],'sell','market','day'])
                        tSO.start()
                        tSO.join()
                elif stock in self.long:
                    tSO = threading.Thread(
                            target=self.alpaca.submit_order, 
                            args=[stock,self.target_position[stock],'buy','market','day'])
                    tSO.start()
                    tSO.join()

sr = SupResis()
sr.run()
