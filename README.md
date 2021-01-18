# AlgorithmicTrading

This is a long only strategy based on technical indicators from TA-LIB (work-in-progress).  
Real-time market data is obtained using Alpaca Data API, which is a consolidation of data sources from five different exchanges:

* IEX (Investors Exchange LLC)
* NYSE National, Inc.
* Nasdaq BX, Inc.
* Nasdaq PSX
* NYSE Chicago, Inc.

Trading is conducted using the Alpaca Trade API. Positions follow the momentum for levels break-outs, else buys near Fibonacci support and sells near resistance if confirmed by ADX based on custom indicator parameters.

### 3-Year Backtesting conducted using Blueshift  
![alt text](https://github.com/DarrenNL/AlgorithmicTrading/blob/main/3%20Year%20Backtest%20(2018-2020).png?raw=true)
