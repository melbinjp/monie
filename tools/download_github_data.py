"""
GitHub Data Downloader
Downloads NIFTY 50 1-minute data (2015-2024) from public repository.
"""
import requests
import pandas as pd
import io

def download_data():
    # Try main branch first
    url = "https://raw.githubusercontent.com/sandeepkapri/Nifty50-Minute-Data/main/nifty50_candlestick_data.csv"
    print(f"Downloading from {url}...")
    
    try:
        response = requests.get(url)
        if response.status_code == 404:
             # Try master branch if main fails
            url = "https://raw.githubusercontent.com/sandeepkapri/Nifty50-Minute-Data/master/nifty50_candlestick_data.csv"
            print(f"Main not found. Trying master: {url}...")
            response = requests.get(url)
            
        if response.status_code != 200:
            print(f"Failed to download. Status Code: {response.status_code}")
            return

        # Load into DataFrame
        df = pd.read_csv(io.StringIO(response.text))
        
        # Standardize Columns
        # Expecting something like: index, date, time, open, high, low, close
        # Let's inspect and rename
        print(f"Original Columns: {df.columns.tolist()}")
        
        # Cleanup column names (strip spaces, lowercase)
        df.columns = [c.strip().lower() for c in df.columns]
        
        # Rename to standardized format
        # Common mapping for this specific dataset based on typical structure
        # If columns are ['date', 'open', 'high', 'low', 'close'], we just need to ensure datetime
        
        if 'date' in df.columns and 'time' in df.columns:
            # Combine Date and Time
            df['datetime'] = pd.to_datetime(df['date'] + ' ' + df['time'], dayfirst=True)
        elif 'date' in df.columns:
            # Maybe date column contains both
            df['datetime'] = pd.to_datetime(df['date'], dayfirst=True)
        elif 'datetime' in df.columns:
             df['datetime'] = pd.to_datetime(df['datetime'])
             
        # Select and Reorder
        required_cols = ['datetime', 'open', 'high', 'low', 'close']
        if 'volume' in df.columns:
            required_cols.append('volume')
        else:
            df['volume'] = 0 # Add dummy volume if missing
            required_cols.append('volume')
            
        final_df = df[required_cols].copy()
        
        # Sort by datetime
        final_df.sort_values('datetime', inplace=True)
        
        # Save
        outfile = "data/nifty_10year_1m.csv"
        final_df.to_csv(outfile, index=False)
        
        print(f"Successfully downloaded {len(final_df)} rows to {outfile}")
        print(f"Range: {final_df['datetime'].min()} to {final_df['datetime'].max()}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    download_data()
