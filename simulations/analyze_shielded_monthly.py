import pandas as pd

def analyze_shielded_monthly():
    try:
        df = pd.read_csv("shielded_trades.csv")
    except FileNotFoundError:
        print("File 'shielded_trades.csv' not found. Run test_guard_longterm.py first.")
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
    
    # Overall Stats
    total_net = monthly_stats['Net PnL'].sum()
    total_gross = monthly_stats['Gross PnL'].sum()
    total_charges = monthly_stats['Charges'].sum()
    
    print("\n" + "="*50)
    print("MONTHLY PERFORMANCE (SHIELDED STRATEGY)")
    print("="*50)
    
    print(f"Total Months: {len(monthly_stats)}")
    print(f"Profitable Months: {len(monthly_stats[monthly_stats['Net PnL'] > 0])}")
    print(f"Loss Making Months: {len(monthly_stats[monthly_stats['Net PnL'] <= 0])}")
    print("-" * 50)
    print(f"Total Gross PnL:  {total_gross:15.2f}")
    print(f"Total Charges:    {total_charges:15.2f} ({(total_charges/total_gross)*100:.1f}% of Gross)")
    print(f"Total Net PnL:    {total_net:15.2f}")
    print("-" * 50)
    
    print("\nBEST MONTH:")
    print(f"Date:   {max_month['Month_Year']}")
    print(f"Profit: {max_month['Net PnL']:.2f}")
    
    print("\nWORST MONTH:")
    print(f"Date:   {min_month['Month_Year']}")
    print(f"Loss:   {min_month['Net PnL']:.2f}")
    
    print("\nFULL MONTHLY BREAKDOWN (Last 12 Months):")
    print("-" * 65)
    print(f"{'Month':<10} | {'Gross PnL':>12} | {'Charges':>10} | {'Net PnL':>12}")
    print("-" * 65)
    
    print("-" * 65)
    
    # Yearly Summary
    df['Year'] = df['Date'].dt.year
    yearly_stats = df.groupby('Year').agg({
        'Net PnL': 'sum',
        'Gross PnL': 'sum',
        'Charges': 'sum',
        'Date': 'count' # Trades count roughly
    }).reset_index()
    
    print("\nYEARLY PERFORMANCE SUMMARY:")
    print("-" * 65)
    print(f"{'Year':<6} | {'Gross PnL':>12} | {'Charges':>10} | {'Net PnL':>12} | {'ROI %':>6}")
    print("-" * 65)
    
    capital = 50000 # Base capital reference
    for _, row in yearly_stats.iterrows():
        roi = (row['Net PnL'] / capital) * 100
        print(f"{row['Year']:<6} | {row['Gross PnL']:12.2f} | {row['Charges']:10.2f} | {row['Net PnL']:12.2f} | {roi:>6.0f}%")
    print("-" * 65)

    # Save monthly data
    monthly_stats.to_csv("shielded_monthly_pnl.csv", index=False)
    print("\nDetailed monthly data saved to 'shielded_monthly_pnl.csv'")

if __name__ == "__main__":
    analyze_shielded_monthly()
