import pandas as pd

def analyze_monthly():
    try:
        df = pd.read_csv("backtest_trades.csv")
    except FileNotFoundError:
        print("❌ 'backtest_trades.csv' not found. Run the backtest first.")
        return

    # Ensure Date column is datetime
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Extract Month-Year
    df['Month_Year'] = df['Date'].dt.to_period('M')
    
    # Group by Month
    monthly_stats = df.groupby('Month_Year').agg({
        'Net PnL': 'sum',
        'Gross PnL': 'sum',
        'Charges': 'sum'
    }).reset_index()
    
    # Find Best and Worst Months
    max_month = monthly_stats.loc[monthly_stats['Net PnL'].idxmax()]
    min_month = monthly_stats.loc[monthly_stats['Net PnL'].idxmin()]
    
    print("\n" + "="*40)
    print("MONTHLY PERFORMANCE ANALYSIS (10 Years)")
    print("="*40)
    
    print(f"Total Months: {len(monthly_stats)}")
    print(f"Profitable Months: {len(monthly_stats[monthly_stats['Net PnL'] > 0])}")
    print(f"Loss Making Months: {len(monthly_stats[monthly_stats['Net PnL'] <= 0])}")
    
    print("\nBEST MONTH:")
    print(f"Date:   {max_month['Month_Year']}")
    print(f"Profit: {max_month['Net PnL']:.2f}")
    
    print("\nWORST MONTH:")
    print(f"Date:   {min_month['Month_Year']}")
    print(f"Loss:   {min_month['Net PnL']:.2f}")
    
    print("\nRECENT MONTHS (Last 5):")
    print(monthly_stats.tail(5))
    
    # Save monthly data
    monthly_stats.to_csv("monthly_pnl.csv", index=False)
    print("\nMonthly data saved to 'monthly_pnl.csv'")

if __name__ == "__main__":
    analyze_monthly()
