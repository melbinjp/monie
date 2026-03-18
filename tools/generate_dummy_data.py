"""
Mock Data Generator 
Creates 10 years of 1-minute data for NIFTY 50.
"""
import pandas as pd
import numpy as np
import datetime

def generate_data(filename="nifty_10yrs_1min.csv"):
    print("Generating 10 Years of 1-Min Data... (This may take a moment)")
    
    start_date = datetime.date(2014, 1, 1)
    end_date = datetime.date(2023, 12, 31)
    
    # Generate business days
    dates = pd.bdate_range(start=start_date, end=end_date)
    
    data = []
    price = 6000.0  # Nifty in 2014
    
    for date in dates:
        # Intraday Simulation (09:15 to 15:30 = 375 minutes)
        # Create a daily trend
        daily_volatility = np.random.normal(0, 0.01) # 1% daily vol
        open_price = price * (1 + np.random.normal(0, 0.005)) # Gap up/down
        
        # Intraday minutes
        times = pd.date_range(start=f"{date} 09:15", end=f"{date} 15:30", freq="1min")
        
        # Simulate Random Walk for the day
        daily_prices = [open_price]
        for _ in range(len(times)-1):
            change = daily_prices[-1] * np.random.normal(0, 0.0005) # 0.05% per min
            daily_prices.append(daily_prices[-1] + change)
            
        # Append to master list
        for t, p in zip(times, daily_prices):
            data.append({
                "datetime": t,
                "open": p,
                "high": p * 1.0002,
                "low": p * 0.9998,
                "close": p,
                "volume": np.random.randint(1000, 50000)
            })
            
        # Update close price for next day
        price = daily_prices[-1]
        
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    print(f"Generated {len(df)} rows of data in {filename}")

if __name__ == "__main__":
    generate_data()
